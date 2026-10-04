"""AURORA API (FastAPI + WebSocket), serving the dashboard. Runs fully offline (NFR-01).

Start with `uv run aurora serve` (default http://127.0.0.1:8765).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import date

import pandas as pd
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from aurora.api.live import LiveSession, run_loop
from aurora.config import DATA_DIR, ROOT, load_station, station_keys
from aurora.guardrail.limits import TIER_INFO

log = logging.getLogger(__name__)
STATE: dict = {}
SOCKETS: set[WebSocket] = set()


async def broadcast(msg: dict):
    if not SOCKETS:
        return
    data = json.dumps({"type": "overview", "data": msg}, default=float)
    dead = []
    for ws in list(SOCKETS):
        try:
            await ws.send_text(data)
        except Exception:
            dead.append(ws)
    for ws in dead:
        SOCKETS.discard(ws)


@asynccontextmanager
async def lifespan(app: FastAPI):
    key = os.environ.get("AURORA_STATION", "bharati")
    session = await asyncio.to_thread(LiveSession, key)
    if os.environ.get("AURORA_MODBUS", "1") == "1":
        try:
            from aurora.ingest.modbus_sim import TwinModbusServer
            session.server = TwinModbusServer(session.metrics, port=int(os.environ.get("AURORA_MODBUS_PORT", 5020)))
            await session.server.start()
        except Exception as e:  # port busy etc.: keep running without the Modbus link
            log.warning("Modbus server not started: %s", e)
            session.server = None
    STATE["session"] = session
    task = asyncio.create_task(run_loop(session, broadcast, float(os.environ.get("AURORA_TICK_S", 1.0))))
    yield
    task.cancel()
    if session.server:
        await session.server.stop()


app = FastAPI(title="AURORA", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def S() -> LiveSession:
    s = STATE.get("session")
    if s is None:
        raise HTTPException(503, "station starting")
    return s


@app.get("/api/health")
def health():
    return {"ok": True, "session": "session" in STATE}


@app.get("/api/stations")
def stations():
    out = []
    for k in station_keys():
        st = load_station(k)
        out.append({"key": k, "name": st.name, "location": st.location, "lat": st.lat, "lon": st.lon,
                    "year_results": (ROOT / "docs" / f"year_{k}_{st.test_year}.json").exists()})
    return {"stations": out, "active": S().key}


@app.get("/api/state")
def state():
    return S().overview()


@app.get("/api/forecast")
def forecast():
    return S().forecast_view()


@app.get("/api/decisions")
def decisions():
    return S().decisions()


@app.get("/api/tiers")
def tiers():
    return [{"column": c, "tier": t, "loads": l, "rule": r} for c, (t, l, r) in TIER_INFO.items()]


@app.get("/api/fuel")
def fuel(refresh: bool = False):
    s = S()
    if refresh or s.fuel_result is None:
        s.refresh_fuel(blocking=True)
    return {"settings": {**s.fuel, "resupply": s.fuel["resupply"].isoformat()}, "busy": s.fuel_busy, "result": s.fuel_result}


class FuelSettings(BaseModel):
    on_hand_kl: float | None = None
    resupply: date | None = None
    delay_days: int | None = None


@app.post("/api/fuel/settings")
def fuel_settings(body: FuelSettings):
    """FR-03 manual inputs: fuel level, resupply date and delay."""
    s = S()
    with s.lock:
        if body.on_hand_kl is not None:
            delta = body.on_hand_kl * 1000 - s.twin.state.fuel_l
            s.twin.state.fuel_l += delta
            s.shadow.state.fuel_l += delta
            s.fuel["on_hand_kl"] = body.on_hand_kl
        if body.resupply is not None:
            s.fuel["resupply"] = body.resupply
        if body.delay_days is not None:
            s.fuel["delay_days"] = body.delay_days
    s.refresh_fuel(blocking=True)
    return fuel()


class Inject(BaseModel):
    type: str
    params: dict = {}


@app.post("/api/sim/inject")
def inject(body: Inject):
    try:
        return S().inject(body.type, **body.params)
    except ValueError as e:
        raise HTTPException(400, str(e))


class Control(BaseModel):
    action: str            # play | pause | speed | reset
    value: float | None = None


@app.post("/api/sim/control")
def control(body: Control):
    s = S()
    if body.action == "play":
        s.running = True
    elif body.action == "pause":
        s.running = False
    elif body.action == "speed":
        s.speed = int(max(1, min(8, body.value or 1)))
    elif body.action == "reset":
        s.reset()
    else:
        raise HTTPException(400, "unknown action")
    return {"running": s.running, "speed": s.speed}


@app.get("/api/year")
def year():
    s = S()
    st = s.st
    path = ROOT / "docs" / f"year_{s.key}_{st.test_year}.json"
    if not path.exists():
        raise HTTPException(404, "run `aurora year` first")
    r = json.loads(path.read_text())
    daily = pd.read_csv(DATA_DIR / "processed" / f"year_{s.key}_{st.test_year}_daily.csv")
    r["daily"] = {c: daily[c].round(1).tolist() for c in daily.columns if c != "date"}
    r["daily"]["date"] = daily["date"].tolist()
    return r


@app.get("/api/telemetry/{metric}")
def telemetry(metric: str, n: int = 240):
    return [{"t": t, "v": v, "q": q} for t, v, q in S().store.latest(metric, n)]


@app.websocket("/ws/live")
async def ws_live(ws: WebSocket):
    await ws.accept()
    SOCKETS.add(ws)
    try:
        await ws.send_text(json.dumps({"type": "overview", "data": S().overview()}, default=float))
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        SOCKETS.discard(ws)


DIST = ROOT / "dashboard" / "dist"
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        f = DIST / path
        return FileResponse(f if f.is_file() else DIST / "index.html")
