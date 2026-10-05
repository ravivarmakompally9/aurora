"""KPIs from PRD §4, computed from a twin log. All results are simulated, never real-station claims."""
from __future__ import annotations

import numpy as np
import pandas as pd

from aurora.config import Station


def kpis(st: Station, log: pd.DataFrame) -> dict:
    dt = st.dt_h
    e = lambda col: float(log[col].sum() * dt)  # kWh
    unserved_el = {c: e(c) for c in log.columns if c.startswith("unserved_")}
    el_demand = e("el_demand_kw")
    el_served = el_demand - log["shed_planned_kw"].sum() * dt - sum(unserved_el.values()) - (
        e("water_deferred_kw") if "water_deferred_kw" in log else 0.0)
    heat_served = e("heat_kw") - e("heat_unserved_kw")
    ren_avail = e("pv_avail_kw") + e("wind_avail_kw")
    ren_used = e("pv_kw") + e("wind_kw") - e("curtail_kw")
    crit_ok = (log["unserved_tier1"] < 1e-6) & (log["unserved_tier2"] < 1e-6) & (log["heat_unserved_kw"] < 1e-6)
    gen_cols = [c for c in log.columns if c.startswith("g") and c.endswith("_kw") and c[1:-3].isdigit()]
    rated = np.array([g.rated_kw for g in st.gensets])
    gen_load = log[gen_cols].to_numpy() / rated
    running = gen_load > 0
    fuel = float(log["fuel_l"].sum())
    days = len(log) * dt / 24
    return {
        "days": days,
        "fuel_l": fuel,
        "fuel_gen_l": float(log["fuel_gen_l"].sum()),
        "fuel_boiler_l": float(log["fuel_boiler_l"].sum()),
        "fuel_l_per_day": fuel / max(days, 1e-9),
        "co2_t": fuel * st.fuel.co2_kg_per_l / 1000,
        "renewable_fraction": ren_used / max(el_served + heat_served, 1e-9),
        "renewable_used_mwh": ren_used / 1000,
        "curtailed_mwh": e("curtail_kw") / 1000,
        "curtailed_pct": 100 * e("curtail_kw") / max(ren_avail, 1e-9),
        "critical_served_pct": 100 * float(crit_ok.mean()),
        "unserved_tier1_kwh": unserved_el.get("unserved_tier1", 0.0),
        "unserved_kwh": sum(unserved_el.values()),
        "water_deferred_kwh": e("water_deferred_kw") if "water_deferred_kw" in log else 0.0,
        "heat_unserved_kwh": e("heat_unserved_kw"),
        "gen_run_hours": float(running.sum() * dt),
        "gen_low_load_hours": float((running & (gen_load < 0.4)).sum() * dt),
        "gen_mean_loading_pct": 100 * float(gen_load[running].mean()) if running.any() else 0.0,
        "gen_starts": int(log["starts"].sum()),
        "heat_recovered_mwh": (e("heat_rec_kw") - e("heat_dump_kw")) / 1000,
        "heat_dumped_mwh": e("heat_dump_kw") / 1000,
        "p2h_mwh": e("p2h_kw") / 1000,
        "boiler_mwh": e("boiler_kw") / 1000,
    }


def compare(st: Station, base: dict, aurora: dict) -> dict:
    saved = base["fuel_l"] - aurora["fuel_l"]
    return {
        "fuel_saved_l": saved,
        "fuel_saved_pct": 100 * saved / max(base["fuel_l"], 1e-9),
        "co2_avoided_t": saved * st.fuel.co2_kg_per_l / 1000,
        "reserve_days_gained": saved / max(aurora["fuel_l_per_day"] + st.fuel.other_use_l_per_day, 1e-9),
    }
