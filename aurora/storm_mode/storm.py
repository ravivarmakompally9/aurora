"""Storm Mode (FR-17, FR-18): prepare the station 12-24 h before a forecast blizzard.

When the forecast probability of blizzard wind crosses the threshold within 24 h, the plan
must reach a higher battery and thermal-tank level by onset, keep a standby generator
online through the storm, carry extra spinning reserve, and park the wind turbines before
cut-out (restarting them after).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from aurora.config import Station

WARN_PROB = 0.5        # probability that triggers Storm Mode
END_PROB = 0.3         # storm considered over below this
PARK_MARGIN_MS = 1.5   # park turbines this far below cut-out
RESERVE_MULT = 1.5
READY_BEFORE_H = 3   # storage targets met this long before predicted onset


@dataclass
class StormAssessment:
    active: bool
    onset_k: int | None          # plan step index of onset
    end_k: int | None
    hours_to_onset: float | None
    prob_max: float
    peak_wind_ms: float
    park: np.ndarray              # bool per plan step: turbines parked
    message: str

    def as_dict(self) -> dict:
        return {"active": self.active, "hours_to_onset": self.hours_to_onset, "prob_max": round(self.prob_max, 2),
                "peak_wind_ms": round(self.peak_wind_ms, 1), "message": self.message}


def assess(st: Station, fc: dict, step_h: float, wind_now_ms: float) -> StormAssessment:
    """`fc` holds 1-D forecast arrays for one issue time (storm_prob, wind10, hub_wind, lead_h)."""
    prob, wind10, hub = fc["storm_prob"], fc["wind10"], fc["hub_wind"]
    lead = np.arange(len(prob)) * step_h
    park = hub >= st.wind.cut_out_ms - PARK_MARGIN_MS
    now = wind_now_ms >= st.control.storm_wind_ms
    cand = np.flatnonzero((prob >= WARN_PROB) & (lead <= 24))
    if not now and not len(cand):
        return StormAssessment(False, None, None, None, float(prob.max(initial=0)), float(wind10.max(initial=0)), park,
                               "No blizzard expected in the next 24 h")
    onset = 0 if now else int(cand[0])
    end = onset
    while end + 1 < len(prob) and prob[end + 1] >= END_PROB:
        end += 1
    pmax = float(prob[onset:end + 1].max(initial=prob[onset]))
    peak = float(wind10[onset:end + 1].max(initial=wind10[onset]))
    hrs = float(lead[onset])
    if now:
        msg = f"Blizzard in progress: wind {wind_now_ms:.0f} m/s. Storm Mode holding reserves."
    else:
        msg = f"Blizzard probability {pmax:.0%} in {hrs:.0f} h (peak about {peak:.0f} m/s). Storm Mode activated."
    return StormAssessment(True, onset, end, hrs, pmax, peak, park, msg)


def apply(st: Station, a: StormAssessment, soc_floor: np.ndarray, tank_floor: np.ndarray,
          min_units: np.ndarray, reserve: np.ndarray, to_block, steps_per_h: int) -> None:
    """Tighten optimiser inputs in place for an active storm. `to_block` maps forecast steps to plan steps."""
    if not a.active:
        return
    b, tk = st.battery, st.tank
    on = to_block(a.onset_k)
    end = to_block(a.end_k)
    # reach the targets 3 h before predicted onset, so a storm arriving early still finds full storage
    ready = to_block(max(0, a.onset_k - READY_BEFORE_H * steps_per_h))
    soc_floor[ready:on + 1] = np.maximum(soc_floor[ready:on + 1], st.control.storm_soc_target * b.capacity_kwh)
    tank_floor[ready:on + 1] = np.maximum(tank_floor[ready:on + 1], st.control.storm_tank_target * tk.capacity_kwh)
    pre = to_block(max(0, a.onset_k - steps_per_h))  # standby genset online an hour before onset
    min_units[pre:end + 1] = np.maximum(min_units[pre:end + 1], 1)
    reserve[on:end + 1] *= RESERVE_MULT
