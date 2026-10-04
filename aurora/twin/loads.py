"""Synthetic station demand: electrical load by priority tier and heat demand (PRD §9.2).

Loads react to temperature, wind and crew count so forecasting models learn real
relationships. Water production and laundry are deferrable within the local day; the
controller decides when they run, so they are returned as daily energy, not a profile.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from aurora.config import Station

MEAL_HOURS = (7, 12, 19)


def is_summer(st: Station, local_dates: pd.DatetimeIndex) -> np.ndarray:
    crew = st.loads["crew"]
    a = int(crew["summer_start"].replace("-", ""))
    b = int(crew["summer_end"].replace("-", ""))
    v = local_dates.month * 100 + local_dates.day
    v = np.asarray(v)
    return (v >= a) & (v <= b) if a <= b else (v >= a) | (v <= b)


def crew_count(st: Station, local_dates: pd.DatetimeIndex, seed: int = 0) -> np.ndarray:
    """Winter crew is fixed; summer crew varies week to week as field parties come and go."""
    crew = st.loads["crew"]
    summer = is_summer(st, local_dates)
    rng = np.random.default_rng(seed + 101)
    weeks = ((local_dates - local_dates[0]).days // 7).to_numpy()
    jitter = rng.integers(-6, 7, size=weeks.max() + 1)[weeks]
    jitter = np.round(jitter * crew["summer"] / 70).astype(int)
    return np.where(summer, np.maximum(crew["winter"], crew["summer"] + jitter), crew["winter"]).astype(float)


def activity(local_hour: np.ndarray) -> np.ndarray:
    h = np.floor(local_hour)
    return np.where((h >= 7) & (h <= 22), 1.0, 0.3)


def meal(local_hour: np.ndarray) -> np.ndarray:
    return np.isin(np.floor(local_hour), MEAL_HOURS).astype(float)


def experiment_schedule(st: Station, local_dates: pd.DatetimeIndex, local_hour: np.ndarray, seed: int = 0) -> np.ndarray:
    """Energy-heavy science runs (tier 3): known in advance, so forecasts may use them."""
    cfg = st.loads["electric"]["tier3_science"]
    rng = np.random.default_rng(seed + 202)
    kw = np.zeros(len(local_dates))
    steps_h = int(round(1 / st.dt_h))
    d = local_dates.to_numpy()
    day_starts = np.flatnonzero(np.r_[True, d[1:] != d[:-1]])
    p_day = cfg["experiments_per_week"] / 7
    for d0 in day_starts:
        if rng.random() < p_day:
            start_h = int(rng.integers(8, 17))
            dur = int(rng.integers(cfg["experiment_hours"][0], cfg["experiment_hours"][1] + 1))
            power = float(rng.uniform(*cfg["experiment_kw"]))
            i0 = d0 + int((start_h - local_hour[d0]) * steps_h)
            if i0 >= d0:
                kw[i0:i0 + dur * steps_h] += power
    return kw


def ar_noise(n: int, rng: np.random.Generator, sigma: float = 0.03, rho: float = 0.9) -> np.ndarray:
    e = rng.standard_normal(n) * sigma * np.sqrt(1 - rho ** 2)
    out = np.empty(n)
    out[0] = e[0]
    for i in range(1, n):
        out[i] = rho * out[i - 1] + e[i]
    return out


def build_demand(st: Station, wx: pd.DataFrame, seed: int = 0) -> pd.DataFrame:
    """Return demand at the control step aligned with the weather index."""
    rng = np.random.default_rng(seed + 303)
    lh = wx["local_hour"].to_numpy()
    ld = pd.DatetimeIndex(wx["local_date"])
    crew = crew_count(st, ld, seed)
    act, ml = activity(lh), meal(lh)
    el = st.loads["electric"]
    t1, t2, t3, t4 = el["tier1_life_support"], el["tier2_comms_safety"], el["tier3_science"], el["tier4_comfort"]
    n = len(wx)
    noise = 1 + ar_noise(n, rng)

    tier1 = (t1["ventilation_kw"] + t1["ventilation_kw_per_person"] * crew + t1["medical_fire_kw"]
             + t1["galley_kw_per_person_meal"] * crew * ml) * noise
    tier2 = np.full(n, float(t2["constant_kw"])) * (1 + 0.5 * (noise - 1))
    exp = experiment_schedule(st, ld, lh, seed)
    tier3 = (t3["constant_kw"] + exp) * (1 + 0.5 * (noise - 1))
    tier4 = t4["kw_per_person_active"] * crew * act * noise

    h = st.loads["heat"]
    temp, wind = wx["temp_c"].to_numpy(), wx["wind10_ms"].to_numpy()
    occ = 0.8 + 0.2 * crew / st.loads["crew"]["summer"]
    space = h["ua_kw_per_k"] * np.maximum(0.0, h["indoor_c"] - temp) * (1 + h["wind_infiltration"] * wind) * occ
    hot_water = h["hot_water_kw_per_person"] * crew * (0.4 + 0.9 * act * (1 + ml))
    heat = (space + hot_water) * (1 + 0.6 * (noise - 1))

    water_kwh = t1["water_kwh_base"] + t1["water_kwh_per_person"] * crew
    laundry_kwh = t4["laundry_kwh_per_person_week"] / 7 * crew

    return pd.DataFrame({
        "crew": crew, "experiment_kw": exp,
        "el_tier1_kw": tier1, "el_tier2_kw": tier2, "el_tier3_kw": tier3, "el_tier4_kw": tier4,
        "heat_kw": heat, "heat_tier1_kw": heat * h["min_share_tier1"],
        "water_kwh_day": water_kwh, "laundry_kwh_day": laundry_kwh,
    }, index=wx.index).assign(el_fixed_kw=lambda d: d.el_tier1_kw + d.el_tier2_kw + d.el_tier3_kw + d.el_tier4_kw)


def deferrable_limits(st: Station) -> dict[str, float]:
    el = st.loads["electric"]
    return {"water": float(el["tier1_life_support"]["water_max_kw"]), "laundry": float(el["tier4_comfort"]["laundry_max_kw"])}
