"""Phase 5 gate: Fuel Survival Score, data validation, Modbus link and API."""
import asyncio
import os
from datetime import date

import pandas as pd
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


def test_year_daily_totals_match_kpis():
    from aurora.config import load_station
    from aurora.sim import daily
    from aurora.twin.baseline import DieselFirst
    from aurora.twin.simulator import Twin
    st = load_station("bharati")
    tw = Twin(st, start="2023-12-29", end="2023-12-31 23:45")
    lb = tw.run(DieselFirst())
    d = daily(st, lb, lb)
    assert d.index.max() == pd.Timestamp("2023-12-31")
    assert d.base_fuel_l.sum() == pytest.approx(lb.fuel_l.sum())


def test_dashboard_updates_while_paused(client):
    """An event injected while paused must reach the dashboard on the next push."""
    import json
    client.post("/api/sim/control", json={"action": "pause"})
    with client.websocket_connect("/ws/live") as ws:
        ws.receive_text()
        client.post("/api/sim/inject", json={"type": "resupply_delay", "params": {"days": 7}})
        for _ in range(20):
            msg = json.loads(ws.receive_text())["data"]
            if msg["events"] and "delayed by 7" in (msg["events"][0].get("message") or ""):
                break
        assert "delayed by 7" in msg["events"][0]["message"]


def test_overview_alerts_recent_and_unique(client):
    from aurora.api.main import STATE
    s = STATE["session"]
    ex = s.ctrl.explainer
    for _ in range(3):
        ex.cards.append({"time": "", "local": "", "step": s.t, "level": "warning", "kind": "storm",
                         "title": "Storm Mode activated", "reason": "x", "fuel_impact_l": None})
    ex.cards.insert(0, {"time": "", "local": "", "step": s.t - 500, "level": "critical", "kind": "x",
                        "title": "Old alert", "reason": "x", "fuel_impact_l": None})
    titles = [a["title"] for a in client.get("/api/state").json()["alerts"]]
    assert titles.count("Storm Mode activated") == 1 and "Old alert" not in titles


def test_views_work_after_injection_while_paused(client):
    """Injecting an event before the next step must not break any screen."""
    client.post("/api/sim/control", json={"action": "pause"})
    for kind in ("blizzard", "generator_failure", "optimizer_failure"):
        client.post("/api/sim/inject", json={"type": kind, "params": {}})
        for path in ("/api/state", "/api/forecast", "/api/decisions"):
            assert client.get(path).status_code == 200, (kind, path)


def test_live_trip_and_optimizer_crash_show_cards(client):
    from aurora.api.main import STATE
    s = STATE["session"]
    client.post("/api/sim/control", json={"action": "pause"})
    for _ in range(40):  # run until a generator is online so the trip is visible
        if s.twin.state.gen_on.any():
            break
        s.step()
    running = int(s.twin.state.gen_on.argmax())
    ev = client.post("/api/sim/inject", json={"type": "generator_failure", "params": {}}).json()
    assert "while running" in ev["message"]
    s.step()
    titles = [c["title"] for c in client.get("/api/decisions").json()["cards"]]
    assert f"{s.st.gensets[running].id} tripped" in titles
    client.post("/api/sim/inject", json={"type": "optimizer_failure", "params": {"hours": 1}})
    s.step()
    assert client.get("/api/state").json()["mode"] == "fallback"
    for _ in range(5):
        s.step()
    assert client.get("/api/state").json()["mode"] in ("normal", "storm")
    titles = [c["title"] for c in client.get("/api/decisions").json()["cards"]]
    assert "Fallback to diesel-first" in titles and "AURORA control restored" in titles


def test_demo_presets(client):
    r = client.post("/api/sim/preset", json={"name": "ship_delay"}).json()
    assert r["tab"] == "fuel"
    st = client.get("/api/state").json()
    assert st["fuel"]["delay_days"] == 30 and st["step"] >= 1
    r = client.post("/api/sim/preset", json={"name": "blizzard"}).json()
    assert r["tab"] == "forecast"
    st = client.get("/api/state").json()
    assert st["mode"] == "storm" and st["fuel"]["delay_days"] == 0  # preset starts from a clean station
    r = client.post("/api/sim/preset", json={"name": "reset"}).json()
    st = client.get("/api/state").json()
    assert st["mode"] == "normal" and st["events"] == [] and st["time"].startswith("2026-10-04")
    assert client.post("/api/sim/preset", json={"name": "nope"}).status_code == 400


def test_ship_delay_preset_waits_for_fresh_fuel_result(client):
    """The preset must return only after the fuel score reflects the delay (no race with the reset's refresh)."""
    from aurora.api.main import STATE
    s = STATE["session"]
    for _ in range(3):
        client.post("/api/sim/preset", json={"name": "ship_delay"})
        fr = s.fuel_result
        assert fr is not None and fr["aurora"]["planned_arrival"] >= "2027-02-04"
        assert client.get("/api/state").json()["fuel"]["survival_score"] < 0.5


def test_live_loop_keeps_running_after_presets(client):
    """Regression: a preset used to kill the live loop (cache cleared between check and read)."""
    import time
    from aurora.api.main import STATE
    s = STATE["session"]
    for name in ("blizzard", "reset", "ship_delay", "blizzard"):
        client.post("/api/sim/preset", json={"name": name})
    client.post("/api/sim/control", json={"action": "play"})
    t0 = s.t
    deadline = time.time() + 20
    while s.t == t0 and time.time() < deadline:
        time.sleep(0.2)
    assert s.t > t0, "the live loop must keep stepping after presets"
    client.post("/api/sim/control", json={"action": "pause"})


def test_events_return_before_snapshot(client):
    """The dashboard's Event impact panel compares this snapshot with the live state."""
    client.post("/api/sim/control", json={"action": "pause"})
    r = client.post("/api/sim/inject", json={"type": "fuel_leak", "params": {"litres": 2000, "hours": 4}}).json()
    assert r["before"]["ready"] and r["before"]["fuel"]["level_l"] > 0 and "step" in r
    p = client.post("/api/sim/preset", json={"name": "ship_delay"}).json()
    assert p["event"] == "resupply_delay" and p["before"]["fuel"]["delay_days"] == 0
    assert p["before"]["fuel"]["survival_score"] is not None  # baseline score exists for the comparison
    assert "before" not in client.post("/api/sim/preset", json={"name": "reset"}).json()
