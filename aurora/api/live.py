"""Live session: the station running in accelerated time (one 15-minute step per tick).

AURORA controls the twin. A diesel-first "shadow" twin sees the same weather and events,
so the dashboard can show live savings. Telemetry goes twin -> Modbus -> data hub ->
validator -> SQLite store, as it would on station.
"""
from __future__ import annotations

import asyncio
import logging
import threading
from datetime import date, timedelta

import numpy as np
import pandas as pd

from aurora.config import DATA_DIR, load_station
from aurora.forecasting.models import load_or_train
from aurora.fuel_planner import montecarlo
from aurora.ingest.store import Store
from aurora.ingest.telemetry import SensorFaults, gen_metrics, minute_samples, snapshot
from aurora.ingest.validate import Validator
from aurora.optimizer.mpc import LIVE_BLOCKS, AuroraController
from aurora.twin.baseline import DieselFirst
from aurora.twin.simulator import Twin

log = logging.getLogger(__name__)

SCENARIO_YEAR = 2026        # dates shown to users; weather comes from the twin's year
DEFAULT_START = "10-04 06:00"


class LiveSession:
    def __init__(self, key: str = "bharati", use_modbus: bool = False, modbus_port: int = 5020):
        self.key = key
        self.st = load_station(key)
        self.full = Twin(self.st)
        self.f = load_or_train(self.full)
        self.lock = threading.RLock()
        self._views: dict = {}  # last result of each read view, served while a step holds the lock
        self.metrics = gen_metrics(len(self.st.gensets))
        self.use_modbus = use_modbus
        self.modbus_port = modbus_port
        self.server = self.reader = None
        self.fuel_result: dict | None = None
        self.fuel_busy = False
        self.preset_busy = False
        self._fuel_lock = threading.Lock()   # one Monte Carlo run at a time
        self._fuel_gen = 0                   # request counter: newer requests supersede older ones
        self._fuel_result_gen = 0
        self.reset()

    # ---------- lifecycle ----------
    def reset(self, start: str | None = None):
        with self.lock:
            st = self.st
            year = st.test_year
            local = pd.Timestamp(f"{year}-{start or DEFAULT_START}")
            t_utc = (local - pd.Timedelta(hours=st.utc_offset_h)).tz_localize("UTC")
            self.year_shift = SCENARIO_YEAR - year
            self.twin = Twin(st, wx=self.full.wx, demand=self.full.demand)
            self.shadow = Twin(st, wx=self.full.wx, demand=self.full.demand)
            self.t0 = self.t = int(self.twin.index.get_indexer([t_utc], method="nearest")[0])
            self.ctrl = AuroraController(st, self.f, blocks=LIVE_BLOCKS, replan_every=1)
            self.ctrl.explainer.clock = self.display_time
            self.base = DieselFirst()
            self.validator = Validator()
            self.faults = SensorFaults()
            self.store = Store(DATA_DIR / "processed" / f"live_{self.key}.db")
            self.prev_values = None
            self.running = True
            self.speed = 1
            self.events: list[dict] = []
            self.fuel = {"on_hand_kl": st.fuel.on_hand_kl, "resupply": shift_date(st.fuel.resupply_date, 0), "delay_days": 0}
            self.last_plan_t = None
            self.telemetry_flags: dict = {}
            self.fuel_result = None
            self._views.clear()  # a fresh station: never serve views of the old one
        self.refresh_fuel(blocking=False)

    # ---------- time ----------
    def display_time(self, t: int | None = None) -> pd.Timestamp:
        t = self.t if t is None else t
        ts = self.twin.index[min(t, self.twin.n - 1)] + pd.Timedelta(hours=self.st.utc_offset_h)
        return ts.tz_localize(None) + pd.DateOffset(years=self.year_shift)

    def today(self) -> date:
        return self.display_time().date()

    # ---------- one control step ----------
    def step(self):
        with self.lock:
            t = self.t
            if t >= self.twin.n - 200:
                self.running = False
                return
            self.ctrl.replan_every = max(1, self.speed)
            sp = self.ctrl.decide(self.twin, t)
            rec = self.twin.step(t, sp)
            self.shadow.step(t, self.base.decide(self.shadow, t))
            self._telemetry(t, rec)
            if self.ctrl.plan_t == t and self.ctrl.plan is not None:
                self._store_plan(t)
            self.t += 1

    def _telemetry(self, t: int, rec: dict):
        values = self.faults.apply(t, snapshot(self.twin, rec))
        if self.server is not None:
            self.server.publish(values)
        clean, flags = self.validator.check(values, estimates=self._estimates(t))
        prev_flags, self.telemetry_flags = self.telemetry_flags, flags
        self.ctrl.guard.degraded = bool(self.validator.degraded)
        ts_end = self.twin.index[t] + pd.Timedelta(minutes=self.st.control.step_min)
        rows = minute_samples(self.prev_values, values, ts_end, self.st.control.step_min, np.random.default_rng(t))
        self.store.telemetry([(ts, m, v, flags.get(m, "ok")) for ts, m, v in rows])
        self.prev_values = clean
        for m, fl in flags.items():
            if fl != "ok" and prev_flags.get(m, "ok") != fl:
                self.events.append({"time": str(self.display_time()), "type": "sensor", "metric": m, "flag": fl,
                                    "message": f"Sensor {m} {fl}: value imputed"})
                self.store.event(self.twin.index[t], "sensor", "warning", f"{m} {fl}: value imputed")

    def _estimates(self, t: int) -> dict:
        fc = self.ctrl.fc
        if not fc:
            return {}
        return {"MET.wind_ms": float(fc["wind10"][min(1, len(fc["wind10"]) - 1)]),
                "MET.temp_c": float(fc["temp"][min(1, len(fc["temp"]) - 1)]),
                "LOAD.el_kw": float(fc["load_p50"][min(1, len(fc["load_p50"]) - 1)])}

    def _store_plan(self, t: int):
        fc, p = self.ctrl.fc, self.ctrl.plan
        issued = self.twin.index[t]
        times = self.twin.index[fc["idx"]]
        rows = []
        for var in ("load", "heat", "pv", "wind"):
            rows += [(times[i], var, float(fc[f"{var}_p10"][i]), float(fc[f"{var}_p50"][i]), float(fc[f"{var}_p90"][i]))
                     for i in range(0, len(times), 4)]
        self.store.forecasts(issued, rows, f"hgb-quantile-{self.f.train_years[0]}-cal{self.f.calib_year}")
        starts = self.twin.index[np.minimum(t + self.ctrl.grid.starts, self.twin.n - 1)]
        prow = [(starts[k], "GEN.units", float(p.u[:, k].sum()), "") for k in range(len(starts))]
        prow += [(starts[k], "BAT.kw", float(p.ch[k] - p.dis[k]), "") for k in range(len(starts))]
        self.store.plan(issued, prow)

    # ---------- events (FR-30) ----------
    def inject(self, kind: str, **kw) -> dict:
        """Apply an event. Returns the event plus `before`: the station overview just before it, so the
        dashboard can show exactly what the event changed."""
        with self.lock:
            t = self.t
            before = self._overview() if self.twin.log else None
            msg = ""
            if kind == "blizzard":
                lead_h = float(kw.get("lead_h", 16)); hours = float(kw.get("hours", 30))
                at = t + int(lead_h / self.st.dt_h)
                for tw in (self.twin, self.shadow):
                    tw.inject("blizzard", t=at, hours=hours, peak_ms=float(kw.get("peak_ms", 32)))
                msg = (f"Blizzard injected: winds start rising in {lead_h:.0f} h, peak {float(kw.get('peak_ms', 32)):.0f} m/s, "
                       f"{hours:.0f} h long")
            elif kind == "generator_failure":
                on = np.flatnonzero(self.twin.state.gen_on & self.twin.gen_available(t))
                avail = np.flatnonzero(self.twin.gen_available(t))
                if "gen" in kw:
                    g = int(kw["gen"])
                elif len(on):
                    g = int(on[0])
                else:
                    g = int(avail[0]) if len(avail) else 0
                hours = float(kw.get("hours", 24))
                for tw in (self.twin, self.shadow):
                    tw.inject("generator_failure", t=t, hours=hours, gen=g)
                was = "while running" if g in on else "while on standby; one fewer unit is available"
                msg = f"{self.st.gensets[g].id} tripped {was} (out for {hours:.0f} h)"
            elif kind == "sensor_loss":
                metric = kw.get("metric", "MET.wind_ms"); mode = kw.get("mode", "frozen")
                self.faults.add(metric, mode, t + int(float(kw.get("hours", 6)) / self.st.dt_h))
                msg = f"Sensor {metric} {mode} for {kw.get('hours', 6)} h"
            elif kind == "fuel_leak":
                litres = float(kw.get("litres", 3000))
                for tw in (self.twin, self.shadow):
                    tw.inject("fuel_leak", t=t, hours=float(kw.get("hours", 6)), litres=litres)
                msg = f"Fuel leak: {litres:,.0f} L over {kw.get('hours', 6)} h"
            elif kind == "resupply_delay":
                days = int(kw.get("days", 30))
                self.fuel["delay_days"] += days
                msg = f"Resupply delayed by {days} days"
            elif kind == "wind_surplus":
                hours = float(kw.get("hours", 24))
                for tw in (self.twin, self.shadow):
                    tw.inject("wind_surplus", t=t, hours=hours, speed_ms=float(kw.get("speed_ms", 14)))
                msg = f"Strong steady wind for {hours:.0f} h"
            elif kind == "optimizer_failure":
                hours = float(kw.get("hours", 2))
                self.ctrl.fail_until = t + int(hours / self.st.dt_h)
                self.ctrl.plan = None  # the last plan is lost too (worst case)
                msg = f"Optimiser crash simulated for {hours:.0f} h"
            else:
                raise ValueError(f"unknown event {kind}")
            self.ctrl.request_replan()  # re-plan at the next step with the new situation
            ev = {"time": str(self.display_time()), "type": kind, "message": msg}
            self._views.clear()  # the next read shows the event at once
            self.events.append(ev)
            self.store.event(self.twin.index[t], kind, "info", msg)
        if kind in ("resupply_delay", "fuel_leak"):
            self.refresh_fuel(blocking=False)
        return {**ev, "step": t, "before": before}

    # ---------- demo presets ----------
    PRESETS = {
        "reset": "Clean station: 4 Oct, 06:00, no events",
        "blizzard": "Blizzard rising in 16 h, running at 1 simulated hour per second",
        "ship_delay": "Supply ship delayed by 30 days",
    }

    def preset(self, name: str) -> dict:
        """One-click demo states for judges. Returns the screen to show next."""
        if name not in self.PRESETS:
            raise ValueError(f"unknown preset {name}")
        self.preset_busy = True  # the live loop stops between steps instead of competing for the lock
        try:
            with self.lock:
                return self._apply_preset(name)
        finally:
            self.preset_busy = False

    def _apply_preset(self, name: str) -> dict:
        self.reset()
        self.step()  # first plan, so every screen has data at once
        tab, ev = "overview", None
        if name == "blizzard":
            ev = self.inject("blizzard", lead_h=16, hours=30, peak_ms=32)
            self.step()
            self.speed, self.running, tab = 4, True, "forecast"
        elif name == "ship_delay":
            self.refresh_fuel(blocking=True)  # score before the delay, for the before/after comparison
            ev = self.inject("resupply_delay", days=30)
            self.refresh_fuel(blocking=True)
            tab = "fuel"
        out = {"preset": name, "description": self.PRESETS[name], "tab": tab}
        if ev:
            out.update(event=ev["type"], message=ev["message"], step=ev["step"], before=ev["before"])
        return out

    # ---------- fuel planner ----------
    def refresh_fuel(self, blocking: bool = True):
        """Re-score fuel with the current inputs. blocking=True waits for any run in progress and returns
        only when a result for the current inputs exists; background requests that a newer one superseded
        are skipped, and an older result never overwrites a newer one."""
        self._fuel_gen += 1
        gen = self._fuel_gen

        def work():
            with self._fuel_lock:
                if gen < self._fuel_result_gen or (not blocking and gen != self._fuel_gen):
                    return  # a newer request already produced (or will produce) the result
                self.fuel_busy = True
                try:
                    # plain reads, deliberately without the station lock: a preset holds that lock while it
                    # waits here, and taking it inside the fuel lock would deadlock
                    fuel_l = self.twin.state.fuel_l
                    today = self.today()
                    resupply = self.fuel["resupply"]
                    delay = self.fuel["delay_days"]
                    r = montecarlo.plan(self.key, today, fuel_l, resupply, delay, n=1000)
                    if gen >= self._fuel_result_gen:
                        self.fuel_result, self._fuel_result_gen = r, gen
                except Exception:
                    log.exception("fuel planner failed")
                finally:
                    self.fuel_busy = False
        if blocking:
            work()
        else:
            threading.Thread(target=work, daemon=True).start()

    # ---------- views ----------
    def _read(self, key: str, build) -> dict:
        """Serve a dashboard view without queueing behind a slow optimiser step: build it when the
        lock frees up within 50 ms, otherwise return the last result (a step later at most)."""
        cached = self._views.get(key)  # one read: reset() may clear the cache at any moment
        if cached is None:
            out = build()  # first request (or just after a reset): wait for it
        elif self.lock.acquire(timeout=0.05):
            try:
                out = build()  # the lock is re-entrant, so build() can take it again
            finally:
                self.lock.release()
        else:
            out = cached
            # cheap fields the user just changed must never look stale
            return {**out, "running": self.running, "speed": self.speed} if key == "overview" and out.get("ready") else out
        if out.get("ready", True):  # never keep a "starting up" view to serve later
            self._views[key] = out
        return out

    def overview(self) -> dict:
        return self._read("overview", self._overview)

    def _overview(self) -> dict:
        with self.lock:
            st, tw = self.st, self.twin
            if not tw.log:
                return {"station": self._station(), "time": str(self.display_time()), "ready": False}
            r, rb = tw.log[-1], self.shadow.log[-1]
            fa = sum(x["fuel_l"] for x in tw.log)
            fb = sum(x["fuel_l"] for x in self.shadow.log)
            day = [x for x in tw.log[-96:]]
            dt = st.dt_h
            ren = sum((x["pv_kw"] + x["wind_kw"] - x["curtail_kw"]) * dt for x in day)
            dem = sum((x["el_demand_kw"] + x["heat_kw"]) * dt for x in day)
            sa = self.ctrl.storm
            fr = self.fuel_result
            gens = [{"id": g.id, "kw": round(r[f"g{i + 1}_kw"], 1), "on": r[f"g{i + 1}_kw"] > 0,
                     "loading_pct": round(100 * r[f"g{i + 1}_kw"] / g.rated_kw), "available": bool(tw.gen_available(self.t)[i])}
                    for i, g in enumerate(st.gensets)]
            return {
                "ready": True, "station": self._station(), "time": str(self.display_time()), "step": self.t - self.t0,
                "running": self.running, "speed": self.speed, "mode": r["mode"],
                "sources": {"pv_kw": r["pv_kw"], "wind_kw": r["wind_kw"] - r["curtail_kw"] * (r["wind_kw"] / max(r["pv_kw"] + r["wind_kw"], 1e-9)),
                            "pv_avail_kw": r["pv_avail_kw"], "wind_avail_kw": r["wind_avail_kw"], "curtail_kw": r["curtail_kw"],
                            "gen_kw": r["gen_kw"], "batt_kw": r["batt_kw"], "turbines_on": bool(r["turbines_on"])},
                "gens": gens,
                "loads": {"el_kw": r["el_load_kw"], "water_kw": r["water_kw"], "laundry_kw": r["laundry_kw"], "p2h_kw": r["p2h_kw"],
                          "tiers": {k: round(float(tw.el[f"el_tier{k}_kw"][r["t"]]), 1) for k in (1, 2, 3, 4)},
                          "unserved_kw": sum(r[f"unserved_tier{k}"] for k in (1, 2, 3, 4))},
                "heat": {"demand_kw": r["heat_kw"], "recovered_kw": r["heat_rec_kw"], "p2h_kw": r["p2h_heat_kw"], "boiler_kw": r["boiler_kw"],
                         "tank_ch_kw": r["tank_ch_kw"], "tank_dis_kw": r["tank_dis_kw"], "dump_kw": r["heat_dump_kw"]},
                "storage": {"soc": r["soc"], "tank_soc": r["tank_soc"]},
                "weather": {"temp_c": float(tw.temp[r["t"]]), "wind_ms": float(tw.wind10[r["t"]]),
                            "hub_wind_ms": float(tw.hub_wind[r["t"]]), "ghi_wm2": float(tw.wx["ghi_wm2"].iloc[r["t"]]),
                            "sun_up": bool(tw.pv_avail[r["t"]] > 0.1 or tw.wx["ghi_wm2"].iloc[r["t"]] > 5)},
                "fuel": {"level_l": r["fuel_level_l"], "reserve_l": st.fuel.safety_reserve_kl * 1000,
                         "capacity_l": st.fuel.tank_capacity_kl * 1000,
                         "survival_score": fr["aurora"]["score"] if fr else None,
                         "survival_score_diesel_first": fr["diesel_first"]["score"] if fr else None,
                         "level": fr["level"] if fr else None,
                         "resupply": self.fuel["resupply"].isoformat(), "delay_days": self.fuel["delay_days"]},
                "renewable_share_24h": ren / max(dem, 1e-9),
                "live_savings": {"aurora_fuel_l": fa, "diesel_first_fuel_l": fb, "saved_l": fb - fa,
                                 "saved_pct": 100 * (fb - fa) / max(fb, 1e-9), "co2_avoided_kg": (fb - fa) * st.fuel.co2_kg_per_l,
                                 "hours": len(tw.log) * dt},
                "storm": sa.as_dict() if sa else None,
                "plan_summary": self.ctrl.explainer.summary if self.ctrl.explainer else {},
                "sensors": {m: f for m, f in self.telemetry_flags.items() if f != "ok"},
                "alerts": self._recent_alerts(),
                "events": self.events[-6:][::-1],
            }

    def _recent_alerts(self, hours: float = 12) -> list[dict]:
        """Warnings and critical cards from the last `hours`, newest first, one per title."""
        since = self.t - int(hours / self.st.dt_h)
        out, seen = [], set()
        for c in reversed(self.ctrl.explainer.cards):
            if c["step"] < since:
                break
            if c["level"] in ("warning", "critical") and c["title"] not in seen:
                seen.add(c["title"])
                out.append({**c, "local": self.display_time(c["step"]).strftime("%a %d %b %H:%M")})
        return out[:3]

    def _station(self) -> dict:
        st = self.st
        return {"key": st.key, "name": st.name, "location": st.location, "lat": st.lat, "lon": st.lon,
                "gensets": [{"id": g.id, "rated_kw": g.rated_kw} for g in st.gensets],
                "pv_kwp": st.pv.kwp, "wind_kw": st.wind.total_kw, "battery_kwh": st.battery.capacity_kwh,
                "tank_kwh": st.tank.capacity_kwh,
                "storm_targets": {"soc": st.control.storm_soc_target, "tank": st.control.storm_tank_target}}

    def forecast_view(self) -> dict:
        return self._read("forecast_view", self._forecast_view)

    def _forecast_view(self) -> dict:
        with self.lock:
            fc, p, tw = self.ctrl.fc, self.ctrl.plan, self.twin
            if fc is None:
                return {"ready": False}
            fine_t = [str(self.display_time(i)) for i in fc["idx"]]
            out = {"ready": True, "issued": str(self.display_time(self.ctrl.plan_t if p else self.t)), "times": fine_t}
            for var in ("load", "heat", "pv", "wind"):
                for q in ("p10", "p50", "p90"):
                    out[f"{var}_{q}"] = np.round(fc[f"{var}_{q}"], 2).tolist()
            out["storm_prob"] = np.round(fc["storm_prob"], 3).tolist()
            out["temp"] = np.round(fc["temp"], 1).tolist()
            out["wind10"] = np.round(fc["wind10"], 1).tolist()
            hist = tw.log[-96:]
            out["history"] = {"times": [str(self.display_time(x["t"])) for x in hist],
                              "load": [round(tw.el_fixed[x["t"]], 1) for x in hist],
                              "heat": [round(x["heat_kw"], 1) for x in hist],
                              "pv": [round(x["pv_avail_kw"], 1) for x in hist],
                              "wind": [round(x["wind_avail_kw"], 1) for x in hist],
                              "soc": [round(x["soc"], 3) for x in hist], "tank": [round(x["tank_soc"], 3) for x in hist],
                              "gen_kw": [round(x["gen_kw"], 1) for x in hist]}
            if p is not None:
                # expand the variable-length plan steps to 15-min resolution so charts keep a true time axis
                blocks = self.ctrl.grid.blocks
                rep = lambda a: np.round(np.repeat(np.asarray(a)[: len(blocks)], blocks), 3).tolist()
                n = int(blocks.sum())
                out["plan"] = {
                    "times": [str(self.display_time(self.ctrl.plan_t + i)) for i in range(n)],
                    "units": rep(p.u.sum(axis=0)), "gen_kw": rep(p.p.sum(axis=0)),
                    "batt_kw": rep(p.ch - p.dis),
                    "soc": rep(p.soc[1:] / max(self.st.battery.capacity_kwh, 1)),
                    "tank": rep(p.tank[1:] / max(self.st.tank.capacity_kwh, 1)),
                    "p2h_kw": rep(p.p2h), "boiler_kw": rep(p.boiler), "water_kw": rep(p.water),
                    "curtail_kw": rep(p.curt), "heat_rec_kw": rep(p.heat_rec),
                    "fuel_l_total": round(float(p.fuel_l.sum()), 1),
                    "solve_s": round(p.solve_s, 2), "status": p.status,
                }
            return out

    def decisions(self) -> dict:
        return self._read("decisions", self._decisions)

    def _decisions(self) -> dict:
        with self.lock:
            ex = self.ctrl.explainer
            cards = []
            for c in ex.cards[-150:][::-1]:
                c = dict(c)
                c["local"] = self.display_time(c["step"]).strftime("%a %d %b %H:%M")
                cards.append(c)
            return {"cards": cards, "summary": ex.summary, "mode": self.ctrl.mode,
                    "solver": {"last_s": self.ctrl.solve_times[-1] if self.ctrl.solve_times else None,
                               "mean_s": float(np.mean(self.ctrl.solve_times)) if self.ctrl.solve_times else None,
                               "failures": self.ctrl.failures}}


def shift_date(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year + years)
    except ValueError:
        return d + timedelta(days=365 * years)


async def run_loop(session: LiveSession, broadcast, tick_s: float = 1.0):
    """Advance the station `speed` steps per tick and push the overview to subscribers."""
    last_fuel_t = session.t
    while True:
        started = asyncio.get_running_loop().time()
        try:  # the loop must never die: log the error and keep the station running
            if session.t < last_fuel_t:  # the station was reset
                last_fuel_t = session.t
            if session.running:
                for _ in range(session.speed):
                    if not session.running or session.preset_busy:
                        break  # let a pause or a demo preset take over at once
                    await asyncio.to_thread(session.step)
                if session.t - last_fuel_t >= 24:  # refresh Fuel Survival Score every 6 simulated hours
                    session.refresh_fuel(blocking=False)
                    last_fuel_t = session.t
            await broadcast(session.overview())  # also while paused, so injected events and settings show at once
        except Exception:
            log.exception("live loop error at step %s", session.t)
        await asyncio.sleep(max(0.05, tick_s - (asyncio.get_running_loop().time() - started)))
