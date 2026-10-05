"""Results analysis for judges: equipment step-up, savings breakdown and stress tests.

Every scenario is a full simulated year (2023 weather, Bharati-like station) of diesel-first vs AURORA.
Finished scenarios are skipped, so the script can be resumed. Results: docs/analysis/*.json and
docs/analysis/results.json (summary). Usage:
    uv run python scripts/analysis.py            # all scenarios (about 13 x 7 min on 10 cores)
    uv run python scripts/analysis.py --smoke    # one month per scenario, to check the setup
"""
from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path

from aurora.config import ROOT
from aurora.sim import run_year

OUT = ROOT / "docs" / "analysis"
NO_TANK = {"tank.capacity_kwh": 0.0, "tank.max_charge_kw": 0.0, "tank.max_discharge_kw": 0.0}
NO_BATT = {"battery.capacity_kwh": 0.0, "battery.power_kw": 0.0}
NO_WIND = {"wind.turbines": 0}
NO_PV = {"pv.kwp": 0.0}
OFF = {"battery": False, "flexible": False, "tank": False, "p2h": False}

SCENARIOS = {
    # 1. equipment step-up (the full station is the main year run)
    "eq_diesel": dict(label="Generators + waste-heat recovery only", overrides={**NO_TANK, **NO_BATT, **NO_WIND, **NO_PV}),
    "eq_tank": dict(label="+ thermal tank", overrides={**NO_BATT, **NO_WIND, **NO_PV}),
    "eq_battery": dict(label="+ battery", overrides={**NO_WIND, **NO_PV}),
    "eq_wind": dict(label="+ wind", overrides={**NO_PV}),
    # 2. savings breakdown: AURORA capabilities switched on one at a time (full equipment)
    "bd_commit": dict(label="Generator commitment and loading only", scenario={"features": OFF}),
    "bd_battery": dict(label="+ battery scheduling", scenario={"features": {**OFF, "battery": True}}),
    "bd_flexible": dict(label="+ flexible-load scheduling", scenario={"features": {**OFF, "battery": True, "flexible": True}}),
    "bd_tank": dict(label="+ waste-heat storage (tank)", scenario={"features": {"battery": True, "flexible": True, "tank": True, "p2h": False}}),
    # 3. stress tests
    "st_fcx2": dict(label="Weather-forecast error doubled", scenario={"nwp_error_scale": 2.0}),
    "st_cold3": dict(label="Colder year (2023 weather, 3 °C colder)", scenario={"temp_shift_c": -3.0}),
    "st_crew125": dict(label="25% more crew (summer 88, winter 30)",
                       overrides={"loads.crew.summer": 88, "loads.crew.winter": 30}, scenario={"retrain": True}),
    "st_halfbatt": dict(label="Half the battery (250 kWh / 100 kW)",
                        overrides={"battery.capacity_kwh": 250.0, "battery.power_kw": 100.0}),
    "st_crewpub": dict(label="Published Bharati crew (summer 47, winter 24)",
                       overrides={"loads.crew.summer": 47}, scenario={"retrain": True}),
}


def main():
    a = argparse.ArgumentParser()
    a.add_argument("--smoke", action="store_true", help="one month per scenario")
    a.add_argument("--only", nargs="*", help="run only these scenario keys")
    args = a.parse_args()
    logging.basicConfig(level=logging.WARNING)
    out = OUT / "smoke" if args.smoke else OUT
    keys = args.only or list(SCENARIOS)
    summary = {}
    for k in keys:
        spec = SCENARIOS[k]
        path = out / f"year_bharati_2023_{k}.json"
        if path.exists():
            r = json.loads(path.read_text())
        else:
            t = time.time()
            r = run_year("bharati", workers=10, overrides=spec.get("overrides"), scenario=spec.get("scenario"),
                         tag=f"_{k}", out_dir=out, months=[7] if args.smoke else range(1, 13))
            print(f"{k}: {time.time() - t:.0f} s", flush=True)
        c = r["comparison"]
        summary[k] = {"label": spec["label"], "fuel_saved_pct": c["fuel_saved_pct"], "fuel_saved_l": c["fuel_saved_l"],
                      "base_fuel_l": r["diesel_first"]["fuel_l"], "aurora_fuel_l": r["aurora"]["fuel_l"],
                      "aurora_starts": r["aurora"]["gen_starts"], "critical_served_pct": r["aurora"]["critical_served_pct"],
                      "failures": r["solver"]["failures"]}
        print(f"{k:12s} saved {c['fuel_saved_pct']:5.1f}%  base {r['diesel_first']['fuel_l']:9.0f} L  "
              f"aurora {r['aurora']['fuel_l']:9.0f} L  critical {r['aurora']['critical_served_pct']:.2f}%", flush=True)
    (out / "results.json").write_text(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
