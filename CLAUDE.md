# AURORA: notes for Claude Code and the team

AURORA is the SIH PS 26061 prototype: an offline AI energy manager for polar stations, running against a digital twin. The PRD is the source of truth for scope. Requirement IDs (FR-xx, NFR-xx) appear in docstrings.

## Commands
- `uv sync`: install Python 3.11 dependencies.
- `uv run pytest`: all phase-gate tests (about 3 min; the optimiser tests are the slow ones).
- `uv run aurora train --station bharati`: retrain and calibrate the forecasters (cached in `data/processed/`).
- `uv run aurora forecast-report`: writes `docs/forecast_report_<station>.json`.
- `uv run aurora year --station bharati`: full-year diesel-first vs AURORA run (about 6 min on 10 cores). Writes `docs/year_*.json` and `data/processed/year_*_daily.csv`. The fuel planner needs the daily file.
- `npm --prefix dashboard install && npm --prefix dashboard run build`, then `uv run aurora serve`: dashboard and API on http://127.0.0.1:8765.
- Dashboard development: run `uv run aurora serve`, then `npm --prefix dashboard run dev` (port 5173, proxies `/api` and `/ws`).

## Layout
- `aurora/twin/`: weather, loads, renewable physics, the simulator (`Twin`, `Setpoint`), the diesel-first baseline and KPIs.
- `aurora/forecasting/`: weather-forecast synthesis, quantile models, conformal calibration and CV.
- `aurora/optimizer/`: `milp.py` (Pyomo + HiGHS), `mpc.py` (`AuroraController`) and `explain.py` (reason cards).
- `aurora/guardrail/`, `aurora/storm_mode/`, `aurora/fuel_planner/`, `aurora/ingest/`: the rest of the PRD modules.
- `aurora/api/`: FastAPI app and the live session. `aurora/sim.py`: the year runner.
- `configs/*.yaml`: one file per station. Values are illustrative.

## Conventions
- Units are kW, kWh, litres, °C and m/s. The twin step is 15 min (`st.dt_h`). Indices are twin steps.
- The MILP assumes identical generators (it optimises the number of units online). Keep station configs that way or extend `milp.py`.
- Every user-facing number is simulated; say so in the UI and docs.
- Commit after each working step. Run `uv run pytest` before committing.
