"""Record the live digital twin for the static demo website (GitHub Pages).

Runs the real LiveSession (forecasts, MILP plans, guardrail, fuel planner) through three
scenarios and saves what each dashboard endpoint returned at every step, so the dashboard
can replay them in the browser with no server. Every figure is simulated, as in the live app.

    uv run python scripts/export_demo.py            # writes dashboard/public/demo/*.json
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from aurora.api.live import LiveSession  # noqa: E402
from aurora.config import DATA_DIR  # noqa: E402

OUT = ROOT / "dashboard" / "public" / "demo"
FORECAST_EVERY = 8  # twin steps between forecast/decision snapshots (2 simulated hours)


def tidy(x):
    """Round floats so the files stay small; keep structure as the API returns it."""
    if isinstance(x, float):
        return round(x, 2) if abs(x) >= 1 else round(x, 4)
    if isinstance(x, dict):
        return {k: tidy(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [tidy(v) for v in x]
    return x


def wait_fuel(s: LiveSession) -> dict:
    """Score fuel with the session's current settings (waits for any refresh already running)."""
    while s.fuel_busy:
        time.sleep(0.2)
    s.refresh_fuel(blocking=True)
    settings = {**s.fuel, "on_hand_kl": round(s.twin.state.fuel_l / 1000, 2), "resupply": s.fuel["resupply"].isoformat()}
    return {"settings": settings, "busy": False, "result": s.fuel_result}


def record(s: LiveSession, steps: int, label: str) -> dict:
    frames, forecasts, decisions = [], {}, {}
    fuel = wait_fuel(s)
    t0 = time.time()
    for i in range(steps + 1):
        if i:
            s.step()
        frames.append(s.overview())
        if i % FORECAST_EVERY == 0 or i == steps:
            forecasts[i] = s.forecast_view()
            decisions[i] = s.decisions()
        if i % 12 == 0:
            print(f"  {label}: step {i}/{steps}  ({time.time() - t0:.0f} s)", flush=True)
    return {"frames": frames, "forecast": forecasts, "decisions": decisions, "fuel": fuel}


def year_view(s: LiveSession) -> dict | None:
    st = s.st
    path = ROOT / "docs" / f"year_{s.key}_{st.test_year}.json"
    daily_path = DATA_DIR / "processed" / f"year_{s.key}_{st.test_year}_daily.csv"
    if not path.exists() or not daily_path.exists():
        return None
    r = json.loads(path.read_text())
    daily = pd.read_csv(daily_path)
    r["daily"] = {c: daily[c].round(1).tolist() for c in daily.columns if c != "date"}
    r["daily"]["date"] = daily["date"].tolist()
    return r


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    s = LiveSession("bharati")
    s.running = False  # this script drives the steps itself
    scenarios = {}

    print("normal day")
    s.reset(); s.running = False
    s.step()  # first plan, so the first recorded frame is not "starting up"
    scenarios["normal"] = ("A normal spring day at the station", record(s, 96, "normal"))

    print("blizzard")
    s.reset(); s.running = False
    s.step()
    s.inject("blizzard", lead_h=16, hours=30, peak_ms=32)
    scenarios["blizzard"] = ("Blizzard rising in 16 h: Storm Mode prepares the station", record(s, 112, "blizzard"))

    print("ship delay")
    s.reset(); s.running = False
    s.step()
    s.inject("resupply_delay", days=30)
    scenarios["ship_delay"] = ("Supply ship delayed by 30 days", record(s, 24, "ship_delay"))

    index = {"generated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "station": s.key,
             "simulated": True, "scenarios": {}}
    for key, (title, data) in scenarios.items():
        (OUT / f"{key}.json").write_text(json.dumps(tidy(data), separators=(",", ":"), default=float))
        index["scenarios"][key] = {"title": title, "frames": len(data["frames"])}
    y = year_view(s)
    if y is not None:
        (OUT / "year.json").write_text(json.dumps(tidy(y), separators=(",", ":"), default=float))
    index["year"] = y is not None
    (OUT / "index.json").write_text(json.dumps(index, indent=1))
    for f in sorted(OUT.glob("*.json")):
        print(f"{f.name}: {f.stat().st_size / 1e6:.2f} MB")


if __name__ == "__main__":
    main()
