"""Plain-language reason cards for every AURORA action (FR-26, PRD §8.5).

Each card says what changed, why (the forecast or constraint that drove it) and an
estimated fuel impact. Impacts are first-order estimates from the fuel curve, marked
"about" in the UI; the authoritative savings come from the side-by-side twin runs.
"""
from __future__ import annotations

import numpy as np

from aurora.config import Station


def _hhmm(ts) -> str:
    return ts.strftime("%a %H:%M")


class Explainer:
    def __init__(self, st: Station, forecaster):
        self.st, self.f = st, forecaster
        self.cards: list[dict] = []
        self.summary: dict = {}
        self.last_p2h_on = False
        self.last_water_on = False

    def _local(self, twin, t: int):
        import pandas as pd
        return twin.index[min(t, twin.n - 1)] + pd.Timedelta(hours=self.st.utc_offset_h)

    def card(self, twin, t, level, title, reason, fuel_l=None, kind="action"):
        c = {"time": twin.index[t].isoformat(), "local": _hhmm(self._local(twin, t)), "step": int(t), "level": level,
             "kind": kind, "title": title, "reason": reason,
             "fuel_impact_l": None if fuel_l is None else round(float(fuel_l), 1)}
        self.cards.append(c)
        if len(self.cards) > 400:
            self.cards = self.cards[-400:]
        return c

    # ---------- per re-plan ----------
    def on_replan(self, twin, t, ctrl, plan, prev_mode):
        st = self.st
        if ctrl.mode == "storm" and prev_mode != "storm":
            sa, p = ctrl.storm, ctrl.plan
            onset_t = t + sa.onset_k
            park = np.flatnonzero(sa.park)
            parts = [f"pre-charge battery to {st.control.storm_soc_target:.0%}",
                     f"pre-heat thermal tank to {st.control.storm_tank_target:.0%}",
                     "keep a standby generator online"]
            if len(park):
                parts.append(f"park turbines from {_hhmm(self._local(twin, t + int(park[0])))}")
            self.card(twin, t, "warning", "Storm Mode activated",
                      f"{sa.message} By {_hhmm(self._local(twin, onset_t))}: " + ", ".join(parts) + ".", kind="storm")
        elif prev_mode == "storm" and ctrl.mode == "normal":
            self.card(twin, t, "info", "Storm Mode ended", "Blizzard risk has passed. Normal optimisation resumed.", kind="storm")
        if ctrl.mode == "fallback" and prev_mode != "fallback":
            self.card(twin, t, "critical", "Fallback to diesel-first",
                      f"Optimiser unavailable ({plan.status}). Station runs on safe rule-based control until the next valid plan.",
                      kind="fallback")
        elif prev_mode == "fallback" and ctrl.mode != "fallback":
            self.card(twin, t, "info", "AURORA control restored", "A valid plan was found again.", kind="fallback")
        if plan.ok:
            self.summary = self._plan_summary(twin, t, ctrl, plan)

    def _plan_summary(self, twin, t, ctrl, plan) -> dict:
        x, dt = plan.inputs, plan.step_h
        base = estimate_diesel_first(self.st, x, dt)
        drivers = self.f.drivers(twin, t, "load", 24) if self.f is not None else {}
        return {
            "issued": twin.index[t].isoformat(), "horizon_h": float(dt.sum()), "solve_s": round(plan.solve_s, 2),
            "plan_fuel_l": round(float(plan.fuel_l.sum()), 1),
            "diesel_first_fuel_l": round(base, 1),
            "saving_l": round(base - float(plan.fuel_l.sum()), 1),
            "gen_unit_hours": round(float((plan.u.sum(axis=0) * dt).sum()), 1),
            "renewable_share_pct": round(100 * float(np.sum((x.pv + x.wind - plan.curt) * dt) / max(np.sum((x.load + x.heat) * dt), 1)), 1),
            "drivers": drivers_text(drivers),
        }

    # ---------- per executed step ----------
    def on_step(self, twin, t, sp, violations):
        st = self.st
        gens = st.gensets
        prev = twin.state.gen_on
        now = np.array(sp.gen_on, bool)
        for v in violations:
            if v["rule"] != "turbine_cut_out" or not self.cards or self.cards[-1]["title"] != "Turbines parked":
                self.card(twin, t, v["severity"], _rule_title(v["rule"]), v["detail"], kind="guardrail")
        stopped = [g for g in range(len(gens)) if prev[g] and not now[g]]
        started = [g for g in range(len(gens)) if now[g] and not prev[g]]
        ren = twin.pv_avail[t] + (twin.wind_avail[t] if sp.turbines_on else 0)
        soc = twin.state.soc_kwh / max(st.battery.capacity_kwh, 1)
        load = twin.el_fixed[t] + sp.water_kw + sp.laundry_kw
        if stopped and sp.source == "aurora":
            g = gens[stopped[0]]
            hrs = self._off_hours(twin, t, stopped[0])
            running = [gens[i].id for i in np.flatnonzero(now)]
            rest = f"{', '.join(running)} carries the rest at {100 * sum(sp.gen_kw) / max(sum(gens[i].rated_kw for i in np.flatnonzero(now)), 1):.0f}% load" if running else "no generator needed"
            self.card(twin, t, "info", f"Stopped {g.id}",
                      f"Solar and wind {ren:.0f} kW plus the battery at {soc:.0%} cover the {load:.0f} kW load; {rest}. "
                      f"Off for about {hrs:.1f} h.", fuel_l=g.a * g.rated_kw * hrs)
        if started and sp.source == "aurora":
            g = gens[started[0]]
            if sp.mode == "storm":
                why = "Standby unit for the blizzard: keeps reserve if the wind turbines park."
                fuel = None
            elif sp.batt_kw > 1:
                pct = 100 * sum(sp.gen_kw) / max(sum(gens[i].rated_kw for i in np.flatnonzero(now)), 1)
                why = (f"Battery at {soc:.0%} with low renewables. Running {g.id} at {pct:.0f}% load and charging the battery "
                       "is cheaper than many hours at low load; waste heat goes to the thermal tank.")
                fuel = None
            else:
                why = f"Load {load:.0f} kW exceeds solar, wind ({ren:.0f} kW) and battery support."
                fuel = None
            self.card(twin, t, "info", f"Started {g.id}", why, fuel_l=fuel)
        p2h_on = sp.p2h_kw > 5
        if p2h_on and not self.last_p2h_on and sp.source == "aurora":
            boiler_l = sp.p2h_kw * st.p2h_eff / (st.boiler_eff * st.diesel_kwh_per_l)
            self.card(twin, t, "info", "Surplus power to heat",
                      f"{sp.p2h_kw:.0f} kW of surplus electricity heats the thermal tank instead of being curtailed.",
                      fuel_l=boiler_l)
        self.last_p2h_on = p2h_on
        water_on = sp.water_kw > 0.25 * st.loads["electric"]["tier1_life_support"]["water_max_kw"]
        if water_on and not self.last_water_on and sp.source == "aurora":
            surplus = max(0.0, ren - twin.el_fixed[t])
            self.card(twin, t, "advisory", "Water production window",
                      f"Running the water plant now ({sp.water_kw:.0f} kW): "
                      + (f"{surplus:.0f} kW renewable surplus available." if surplus > 5 else "generator has spare efficient capacity."),
                      fuel_l=None, kind="schedule")
        self.last_water_on = water_on

    def _off_hours(self, twin, t, g) -> float:
        return 0.25  # refined by the controller's plan below when available

    def bind_plan_lookup(self, ctrl):
        def off_hours(twin, t, g):
            p = ctrl.plan
            if p is None:
                return 0.25
            k = ctrl.plan_step(t)
            u = p.u[g, k:]
            on_again = np.flatnonzero(u > 0.5)
            n = on_again[0] if len(on_again) else len(u)
            return float(p.step_h[k:k + n].sum())
        self._off_hours = off_hours


def _rule_title(rule: str) -> str:
    return {"spinning_reserve": "Guardrail: reserve restored", "turbine_cut_out": "Turbines parked",
            "battery_floor": "Guardrail: battery floor", "tier_protection": "Guardrail: protected load",
            "equipment_unavailable": "Guardrail: unit unavailable", "fuel_reserve": "Fuel below safety reserve",
            "reserve_shortfall": "Reserve shortfall", "no_generator": "No generator available"}.get(rule, rule)


def drivers_text(d: dict) -> list[str]:
    if not d:
        return []
    out = []
    w = d.get("weather", 0)
    if abs(w) >= 1:
        out.append(f"{'+' if w > 0 else '-'}{abs(w):.0f} kW from weather (wind chill {d['wind_chill_fc_c']:.0f} °C)")
    c = d.get("crew", 0)
    if abs(c) >= 1:
        diff = d["crew"] - d["crew_ref"]
        out.append(f"{'+' if c > 0 else '-'}{abs(c):.0f} kW from crew ({d['crew']:.0f} on station, {diff:+.0f} vs typical)")
    e = d.get("experiments", 0)
    if abs(e) >= 1:
        out.append(f"{'+' if e > 0 else '-'}{abs(e):.0f} kW from scheduled experiments")
    return out


def estimate_diesel_first(st: Station, x, step_h: np.ndarray) -> float:
    """Fuel the diesel-first rules would burn on the same forecast (for the plan summary)."""
    b = st.battery
    g0 = st.gensets[0]
    r, pmin = g0.rated_kw, g0.min_load * g0.rated_kw
    soc = x.soc0_kwh
    water_left = float(x.water_req[0])
    fuel = 0.0
    wmax = st.loads["electric"]["tier1_life_support"]["water_max_kw"]
    for k in range(len(x.load)):
        dt = float(step_h[k])
        w = min(wmax, water_left / dt) if water_left > 0 else 0.0
        water_left -= w * dt
        net = x.load[k] + w - x.pv[k] - x.wind[k]
        dis = min(b.power_kw, max(0.0, (soc - b.soc_min * b.capacity_kwh) * b.eta_discharge / dt), max(0.0, net - pmin))
        need = net - dis
        n = max(1, int(np.ceil(1.2 * max(0.0, need) / r)))
        per = min(r, max(need / n, pmin))
        excess = n * per - need
        ch = min(b.power_kw, max(0.0, excess), max(0.0, (b.soc_max * b.capacity_kwh - soc) / (b.eta_charge * dt)))
        soc += (ch * b.eta_charge - dis / b.eta_discharge) * dt
        lph = n * (g0.a * r + g0.b * per)
        rec = lph * g0.heat_recovery * st.diesel_kwh_per_l
        boiler = max(0.0, x.heat[k] - rec)
        fuel += (lph + boiler / (st.boiler_eff * st.diesel_kwh_per_l)) * dt
    return fuel
