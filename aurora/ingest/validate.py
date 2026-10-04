"""Data validation (FR-02): flag missing, frozen and impossible values, and impute them.

Quality flags: ok | missing | frozen | outlier. Imputed values come from a related estimate
when the caller has one (for example the short-range forecast), otherwise the last good value.
A bad critical sensor marks the data as degraded, which widens the guardrail's reserve.
"""
from __future__ import annotations

from collections import defaultdict, deque

RANGES = {
    "MET.temp_c": (-70, 20), "MET.wind_ms": (0, 60), "MET.ghi_wm2": (0, 1400),
    "PV.power_kw": (0, 2000), "WT.power_kw": (0, 2000),
    "BAT.soc_pct": (0, 100), "BAT.power_kw": (-2000, 2000), "TANK.soc_pct": (0, 100),
    "P2H.power_kw": (0, 2000), "BOILER.heat_kw": (0, 2000),
    "LOAD.el_kw": (0, 3000), "LOAD.heat_kw": (0, 3000), "FUEL.level_l": (-1e5, 1e7),
}
FROZEN_SAMPLES = 20          # identical non-zero readings in a row (1-min data) => frozen sensor
CRITICAL = ("MET.wind_ms", "MET.temp_c", "LOAD.el_kw", "BAT.soc_pct", "FUEL.level_l")


class Validator:
    def __init__(self):
        self.last_good: dict[str, float] = {}
        self.history: dict[str, deque] = defaultdict(lambda: deque(maxlen=FROZEN_SAMPLES))
        self.flags: dict[str, str] = {}

    def check(self, values: dict, estimates: dict | None = None) -> tuple[dict, dict]:
        estimates = estimates or {}
        clean, flags = {}, {}
        for m, v in values.items():
            flag = "ok"
            if v is None:
                flag = "missing"
            else:
                lo, hi = RANGES.get(m, (-1e12, 1e12))
                if not (lo <= v <= hi):
                    flag = "outlier"
                else:
                    h = self.history[m]
                    h.append(v)
                    if len(h) == FROZEN_SAMPLES and abs(v) > 1e-6 and max(h) == min(h) and not m.endswith("running"):
                        flag = "frozen"
            if flag == "ok":
                clean[m] = v
                self.last_good[m] = v
            else:
                clean[m] = estimates.get(m, self.last_good.get(m, 0.0))
            flags[m] = flag
        self.flags = flags
        return clean, flags

    @property
    def degraded(self) -> list[str]:
        return [m for m in CRITICAL if self.flags.get(m, "ok") != "ok"]
