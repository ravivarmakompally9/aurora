"""Command line: `uv run aurora <command>`."""
from __future__ import annotations

import argparse
import json
import logging


def main(argv=None):
    p = argparse.ArgumentParser(prog="aurora", description="AURORA polar energy management (SIH PS 26061)")
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("fetch-weather", help="download NASA POWER hourly weather for a station")
    a.add_argument("--station", default="bharati")
    a = sub.add_parser("train", help="train and calibrate the forecasters")
    a.add_argument("--station", default="bharati")
    a = sub.add_parser("forecast-report", help="time-series validation report (docs/forecast_report_*.json)")
    a.add_argument("--station", default="bharati")
    a = sub.add_parser("year", help="full-year diesel-first vs AURORA comparison on the digital twin")
    a.add_argument("--station", default="bharati")
    a.add_argument("--year", type=int)
    a.add_argument("--workers", type=int, default=10)
    a.add_argument("--replan-h", type=float, default=3.0)
    a.add_argument("--min-up-h", type=float, help="override the generator minimum run time (experiment)")
    a.add_argument("--start-wear-l", type=float, help="override the per-start wear cost (experiment)")
    a.add_argument("--tag", default="", help="suffix for output files, e.g. _minup1")
    a = sub.add_parser("serve", help="run the API server")
    a.add_argument("--host", default="127.0.0.1")
    a.add_argument("--port", type=int, default=8765)
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("pyomo").setLevel(logging.WARNING)  # HiGHS progress tables would bury real errors

    from aurora.config import load_station
    if args.cmd == "fetch-weather":
        from aurora.twin.weather import fetch_nasa_power
        print(fetch_nasa_power(load_station(args.station)))
    elif args.cmd == "train":
        from aurora.forecasting.models import load_or_train
        from aurora.twin.simulator import Twin
        f = load_or_train(Twin(load_station(args.station)), retrain=True)
        print("calibration margins (kW):", json.dumps(f.margins))
    elif args.cmd == "forecast-report":
        from aurora.forecasting.cv import report
        from aurora.twin.simulator import Twin
        st = load_station(args.station)
        print(json.dumps(report(st, Twin(st)), indent=2))
    elif args.cmd == "year":
        from aurora.sim import kpi_table, run_year
        ov = {k: v for k, v in (("genset_min_up_h", args.min_up_h), ("genset_start_wear_l", args.start_wear_l)) if v is not None}
        r = run_year(args.station, args.year, args.workers, args.replan_h, ov or None, args.tag)
        print(kpi_table(r))
        print(f"\nsolver: {r['solver']}  wall {r['wall_s']} s")
    elif args.cmd == "serve":
        import uvicorn
        uvicorn.run("aurora.api.main:app", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
