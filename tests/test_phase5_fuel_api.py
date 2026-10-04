"""Phase 5 gate: Fuel Survival Score, data validation, Modbus link and API."""
import asyncio
import os
from datetime import date

import pytest

from aurora.fuel_planner import montecarlo as mc
from aurora.ingest.validate import FROZEN_SAMPLES, Validator


def test_survival_score_falls_with_resupply_delay():
    scores = [mc.survival("bharati", date(2026, 10, 4), 120000, date(2027, 1, 5), d, n=400)["score"] for d in (0, 15, 30)]
    assert scores[0] >= scores[1] >= scores[2]
    assert scores[0] > 0.9 and scores[2] < 0.5


def test_aurora_scores_higher_than_diesel_first():
    a = mc.survival("bharati", date(2026, 10, 4), 120000, date(2027, 1, 5), 0, "aurora", n=400)
    b = mc.survival("bharati", date(2026, 10, 4), 120000, date(2027, 1, 5), 0, "diesel_first", n=400)
    assert a["score"] >= b["score"] and a["burn_l_per_day"] < b["burn_l_per_day"]


def test_delay_produces_ranked_actions_with_litres():
    r = mc.plan("bharati", date(2026, 10, 4), 120000, date(2027, 1, 5), 30, n=400)
    assert r["level"] == "critical"
    single = [a for a in r["actions"] if a["key"] != "all"]
    assert all(a["litres_saved"] > 0 for a in single)
    assert [a["litres_saved"] for a in single] == sorted((a["litres_saved"] for a in single), reverse=True)
    assert r["actions"][-1]["litres_saved"] >= single[0]["litres_saved"]
    assert r["recommended_order_l"] > 0


def test_frozen_sensor_flagged_and_imputed():
    v = Validator()
    for i in range(30):
        v.check({"MET.wind_ms": 10 + 0.1 * i})
    flags = []
    for _ in range(FROZEN_SAMPLES + 2):
        clean, fl = v.check({"MET.wind_ms": 12.3}, estimates={"MET.wind_ms": 18.0})
        flags.append(fl["MET.wind_ms"])
    assert flags[-1] == "frozen" and clean["MET.wind_ms"] == 18.0
    assert "MET.wind_ms" in v.degraded


def test_missing_and_outlier_do_not_crash():
    v = Validator()
    v.check({"MET.temp_c": -20.0, "LOAD.el_kw": 80.0})
    clean, fl = v.check({"MET.temp_c": None, "LOAD.el_kw": 9e9})
    assert fl == {"MET.temp_c": "missing", "LOAD.el_kw": "outlier"}
    assert clean == {"MET.temp_c": -20.0, "LOAD.el_kw": 80.0}


def test_modbus_round_trip():
    from aurora.ingest.modbus_sim import ModbusReader, TwinModbusServer
    from aurora.ingest.telemetry import gen_metrics
    m = gen_metrics(3)

    async def go():
        s = TwinModbusServer(m, port=5031)
        await s.start()
        s.publish({"MET.wind_ms": 23.45, "BAT.power_kw": -120.3, "MET.temp_c": None})
        r = ModbusReader(m, port=5031)
        out = await r.read()
        r.close()
        await s.stop()
        return out
    out = asyncio.run(go())
    assert out["MET.wind_ms"] == pytest.approx(23.45) and out["BAT.power_kw"] == pytest.approx(-120.3)
    assert out["MET.temp_c"] is None


@pytest.fixture(scope="module")
def client():
    os.environ["AURORA_MODBUS"] = "0"
    os.environ["AURORA_TICK_S"] = "0.2"
    from fastapi.testclient import TestClient
    from aurora.api.main import app
    with TestClient(app) as c:
        c.post("/api/sim/control", json={"action": "pause"})
        yield c


def test_api_end_to_end(client):
    from aurora.api.main import STATE
    s = STATE["session"]
    for _ in range(3):
        s.step()
    o = client.get("/api/state").json()
    assert o["ready"] and o["mode"] in ("normal", "storm", "fallback")
    assert o["loads"]["unserved_kw"] == 0
    f = client.get("/api/forecast").json()
    assert f["ready"] and len(f["times"]) == 192 and len(f["plan"]["times"]) == 192
    d = client.get("/api/decisions").json()
    assert "cards" in d and d["summary"]
    fuel = client.get("/api/fuel?refresh=true").json()
    assert 0 <= fuel["result"]["aurora"]["score"] <= 1
    assert client.get("/api/telemetry/MET.wind_ms").json()


def test_api_injections(client):
    from aurora.api.main import STATE
    s = STATE["session"]
    for kind in ("blizzard", "generator_failure", "sensor_loss", "wind_surplus", "fuel_leak"):
        r = client.post("/api/sim/inject", json={"type": kind, "params": {}})
        assert r.status_code == 200, r.text
    s.step()
    s.step()
    assert client.get("/api/state").json()["loads"]["unserved_kw"] == 0
    r = client.post("/api/fuel/settings", json={"delay_days": 30})
    assert r.json()["result"]["aurora"]["score"] < 0.95
    assert client.post("/api/sim/inject", json={"type": "nope", "params": {}}).status_code == 400
