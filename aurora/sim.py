"""Simulation lab: a full year of diesel-first vs AURORA on the digital twin (FR-28, FR-29, scenario A).

Months run in parallel processes; each month starts both strategies from the same state
(battery 60 %, tank 50 %), so the comparison is like-for-like. The year uses an hourly
48 h plan re-solved every 3 h; live mode uses the finer grid.
"""
from __future__ import annotations

import dataclasses
import json
import logging
import os
import pickle
import time
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pandas as pd

from aurora.config import DATA_DIR, ROOT, load_station
from aurora.forecasting.models import load_or_train
from aurora.optimizer.mpc import YEAR_BLOCKS, AuroraController
from aurora.twin.baseline import DieselFirst
from aurora.twin.kpi import compare, kpis
from aurora.twin.simulator import Twin

log = logging.getLogger(__name__)


def _month_bounds(tw: Twin, year: int, month: int) -> tuple[int, int]:
    idx = tw.index
    sel = np.flatnonzero((idx.year == year) & (idx.month == month))
    return int(sel[0]), int(sel[-1]) + 1


def _station(key: str, overrides: dict | None):
    st = load_station(key)
    return dataclasses.replace(st, **overrides) if overrides else st


def _run_month(args):
    key, year, month, replan_h, overrides = args
    st = _station(key, overrides)
    f = load_or_train(Twin(st))
    t_start = time.time()
    tb = Twin(st)
    t0, t1 = _month_bounds(tb, year, month)
    lb = tb.run(DieselFirst(), t0, t1)
    ta = Twin(st)
    ctrl = AuroraController(st, f, blocks=YEAR_BLOCKS, replan_every=int(replan_h / st.dt_h), time_limit_s=10,
                            mip_gap=0.02, threads=1, seed=month)
    la = ta.run(ctrl, t0, t1)
    return {"month": month, "base": lb, "aurora": la, "cards": ctrl.explainer.cards,
            "solve_mean_s": float(np.mean(ctrl.solve_times)), "solve_max_s": float(np.max(ctrl.solve_times)),
            "solves": len(ctrl.solve_times), "failures": ctrl.failures, "secs": time.time() - t_start}


def daily(st, lb: pd.DataFrame, la: pd.DataFrame) -> pd.DataFrame:
    year = int(la.index[len(la) // 2].year)
    # station-local days; the few hours past 31 Dec (UTC offset) stay in 31 Dec so totals match the KPIs
    cap = pd.Timestamp(f"{year}-12-31")

    def local(d):
        days = (d.index + pd.Timedelta(hours=st.utc_offset_h)).normalize().tz_localize(None)
        return days.where(days <= cap, cap)
    dt = st.dt_h
    out = pd.DataFrame({
        "base_fuel_l": lb.fuel_l.groupby(local(lb)).sum(),
        "aurora_fuel_l": la.fuel_l.groupby(local(la)).sum(),
        "base_ren_kwh": ((lb.pv_kw + lb.wind_kw - lb.curtail_kw) * dt).groupby(local(lb)).sum(),
        "aurora_ren_kwh": ((la.pv_kw + la.wind_kw - la.curtail_kw) * dt).groupby(local(la)).sum(),
        "demand_kwh": ((la.el_demand_kw + la.heat_kw) * dt).groupby(local(la)).sum(),
        "base_gen_h": (lb.gens_on * dt).groupby(local(lb)).sum(),
        "aurora_gen_h": (la.gens_on * dt).groupby(local(la)).sum(),
        "storm_h": ((la["mode"] == "storm") * dt).groupby(local(la)).sum(),
    })
    out["hours"] = la.fuel_l.groupby(local(la)).size() * dt
    out.index.name = "date"
    return out


def run_year(key: str = "bharati", year: int | None = None, workers: int = 10, replan_h: float = 3.0,
             overrides: dict | None = None, tag: str = "") -> dict:
    """`overrides` changes station fields for an experiment (e.g. genset_min_up_h); `tag` keeps its outputs separate."""
    st = _station(key, overrides)
    year = year or st.test_year
    load_or_train(Twin(st))  # make sure the model is cached before workers start
    for var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
        os.environ[var] = "1"  # one process per core; avoid thread oversubscription in the workers
    t = time.time()
    with ProcessPoolExecutor(max_workers=workers) as ex:
        parts = sorted(ex.map(_run_month, [(key, year, m, replan_h, overrides) for m in range(1, 13)]),
                       key=lambda r: r["month"])
    lb = pd.concat([p["base"] for p in parts])
    la = pd.concat([p["aurora"] for p in parts])
    kb, ka = kpis(st, lb), kpis(st, la)
    result = {
        "station": key, "year": year, "simulated": True, "wall_s": round(time.time() - t, 1),
        "replan_every_h": replan_h, "plan_grid": "hourly x 48 h",
        "genset_min_up_h": st.genset_min_up_h, "start_cost_l": st.genset_start_cost_l + st.genset_start_wear_l,
        "solver": {"solves": sum(p["solves"] for p in parts), "failures": sum(p["failures"] for p in parts),
                   "mean_s": round(float(np.mean([p["solve_mean_s"] for p in parts])), 3),
                   "max_s": round(max(p["solve_max_s"] for p in parts), 2)},
        "diesel_first": kb, "aurora": ka, "comparison": compare(st, kb, ka),
    }
    proc = DATA_DIR / "processed"
    proc.mkdir(parents=True, exist_ok=True)
    cards = [c for p in parts for c in p["cards"]]
    with open(proc / f"year_{key}_{year}{tag}_logs.pkl", "wb") as fh:  # save the expensive part first
        pickle.dump({"base": lb, "aurora": la, "cards": cards}, fh)
    out_json = ROOT / "docs" / f"year_{key}_{year}{tag}.json"
    out_json.write_text(json.dumps(result, indent=2, default=float))
    daily(st, lb, la).to_csv(proc / f"year_{key}_{year}{tag}_daily.csv")
    return result


def kpi_table(r: dict) -> str:
    rows = [("Fuel (L)", "fuel_l", "{:,.0f}"), ("  generators (L)", "fuel_gen_l", "{:,.0f}"),
            ("  boiler (L)", "fuel_boiler_l", "{:,.0f}"), ("CO2 (t)", "co2_t", "{:,.1f}"),
            ("Renewable fraction (power+heat)", "renewable_fraction", "{:.1%}"),
            ("Curtailed renewables", "curtailed_pct", "{:.1f}%"),
            ("Critical load served", "critical_served_pct", "{:.2f}%"),
            ("Tier-1 unserved (kWh)", "unserved_tier1_kwh", "{:.1f}"),
            ("Generator run-hours", "gen_run_hours", "{:,.0f}"), ("Low-load hours (<40%)", "gen_low_load_hours", "{:,.0f}"),
            ("Mean generator loading", "gen_mean_loading_pct", "{:.0f}%"), ("Generator starts", "gen_starts", "{:,}"),
            ("Heat recovered (MWh)", "heat_recovered_mwh", "{:,.0f}"), ("Heat dumped (MWh)", "heat_dumped_mwh", "{:,.0f}"),
            ("Power-to-heat (MWh)", "p2h_mwh", "{:,.0f}")]
    w = max(len(r[0]) for r in rows) + 2
    lines = [f"{'KPI':<{w}}{'Diesel-first':>14}{'AURORA':>14}"]
    for label, k, fmt in rows:
        lines.append(f"{label:<{w}}{fmt.format(r['diesel_first'][k]):>14}{fmt.format(r['aurora'][k]):>14}")
    c = r["comparison"]
    lines.append("")
    lines.append(f"Fuel saved: {c['fuel_saved_l']:,.0f} L ({c['fuel_saved_pct']:.1f}%), CO2 avoided {c['co2_avoided_t']:.1f} t, "
                 f"reserve days gained {c['reserve_days_gained']:.1f}  [SIMULATED]")
    return "\n".join(lines)
