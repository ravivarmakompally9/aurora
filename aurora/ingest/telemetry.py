"""Telemetry from the digital twin, as the station's sensors would report it (FR-01).

The twin steps every 15 minutes; telemetry is emitted at 1-minute resolution by
interpolating between steps with small sensor noise. Sensor-loss events (FR-30) make a
sensor go missing or freeze at its last value.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

METRICS = {
    # name: (unit, scale for 32-bit Modbus registers)
    "MET.temp_c": ("°C", 100), "MET.wind_ms": ("m/s", 100), "MET.ghi_wm2": ("W/m²", 10),
    "PV.power_kw": ("kW", 10), "WT.power_kw": ("kW", 10),
    "BAT.soc_pct": ("%", 100), "BAT.power_kw": ("kW", 10),
    "TANK.soc_pct": ("%", 100), "P2H.power_kw": ("kW", 10), "BOILER.heat_kw": ("kW", 10),
    "LOAD.el_kw": ("kW", 10), "LOAD.heat_kw": ("kW", 10), "FUEL.level_l": ("L", 1),
}


def gen_metrics(n_gens: int) -> dict:
    m = dict(METRICS)
    for i in range(1, n_gens + 1):
        m[f"G{i}.power_kw"] = ("kW", 10)
        m[f"G{i}.running"] = ("bool", 1)
    return m


def snapshot(twin, rec: dict) -> dict[str, float]:
    """Sensor values for one twin step record."""
    t = rec["t"]
    w = twin.wx.iloc[t]
    out = {
        "MET.temp_c": float(w["temp_c"]), "MET.wind_ms": float(w["wind10_ms"]), "MET.ghi_wm2": float(w["ghi_wm2"]),
        "PV.power_kw": rec["pv_kw"], "WT.power_kw": rec["wind_kw"],
        "BAT.soc_pct": 100 * rec["soc"], "BAT.power_kw": rec["batt_kw"],
        "TANK.soc_pct": 100 * rec["tank_soc"], "P2H.power_kw": rec["p2h_kw"], "BOILER.heat_kw": rec["boiler_kw"],
        "LOAD.el_kw": rec["el_load_kw"], "LOAD.heat_kw": rec["heat_kw"], "FUEL.level_l": rec["fuel_level_l"],
    }
    for i in range(len(twin.st.gensets)):
        out[f"G{i + 1}.power_kw"] = rec[f"g{i + 1}_kw"]
        out[f"G{i + 1}.running"] = float(rec[f"g{i + 1}_kw"] > 0)
    return out


@dataclass
class SensorFaults:
    """Active sensor faults: metric -> (kind, until_step, frozen_value)."""
    active: dict = field(default_factory=dict)

    def add(self, metric: str, kind: str, until_step: int, value: float | None = None):
        self.active[metric] = (kind, until_step, value)

    def apply(self, t: int, values: dict) -> dict:
        out = dict(values)
        for m, (kind, until, frozen) in list(self.active.items()):
            if t >= until:
                del self.active[m]
                continue
            if kind == "missing":
                out[m] = None
            elif kind == "frozen":
                if frozen is None:
                    frozen = values.get(m)
                    self.active[m] = (kind, until, frozen)
                out[m] = frozen
        return out


def minute_samples(prev: dict | None, cur: dict, t_end: pd.Timestamp, minutes: int, rng: np.random.Generator) -> list[tuple]:
    """Interpolate 1-minute readings across one twin step: [(timestamp, metric, value)]."""
    rows = []
    for k in range(minutes):
        ts = t_end - pd.Timedelta(minutes=minutes - 1 - k)
        a = (k + 1) / minutes
        for m, v in cur.items():
            if v is None:
                rows.append((ts, m, None))
                continue
            p = prev.get(m) if prev else None
            val = v if p is None else p + (v - p) * a
            if not m.endswith(("running", "level_l", "soc_pct")):
                val = val + rng.normal(0, 0.002 * max(abs(val), 1.0))
            rows.append((ts, m, float(val)))
    return rows
