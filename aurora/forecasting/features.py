"""Weather-forecast synthesis and feature engineering for the 48 h forecasters.

The station receives a numerical weather prediction (NWP); in the prototype we synthesise
it from the realised weather with autocorrelated errors that grow with lead time
(documented in docs/data_card.md). Forecasts never see realised values beyond the issue time.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from aurora.config import Station
from aurora.twin.assets import pv_power, wind_power, solar_position


def sigma_temp(lead_h):
    return 0.5 + 0.06 * lead_h


def sigma_logwind(lead_h):
    return 0.08 + 0.006 * lead_h


def sigma_kt(lead_h):
    return 0.05 + 0.004 * lead_h


def wind_chill(t_c, v_ms):
    v = np.maximum(v_ms * 3.6, 4.8) ** 0.16
    return 13.12 + 0.6215 * t_c - 11.37 * v + 0.3965 * t_c * v


def target_index(t0: np.ndarray, horizon: int, stride: int) -> np.ndarray:
    """(n_issue, horizon) array of step indices t0 + stride*k; step 0 is the current step."""
    return t0[:, None] + stride * np.arange(horizon)[None, :]


NWP_CYCLE_H = 6  # weather centres issue a new run every 6 h; forecasts in between reuse it


def nwp(twin, t0: np.ndarray, horizon: int, stride: int, seed: int = 0) -> dict[str, np.ndarray]:
    """Synthetic NWP valid at each t0, for `horizon` steps of `stride` twin steps.

    Errors belong to the 6-hourly NWP run in force at t0 (seeded by that run), so consecutive
    re-plans see the same forecast until a new run arrives, as on a real station.
    """
    st = twin.st
    idx = np.minimum(target_index(t0, horizon, stride), twin.n - 1)
    cycle = int(round(NWP_CYCLE_H / st.dt_h))
    issue = t0 - t0 % cycle
    off = t0 - issue
    lead_h = (idx - issue[:, None]) * st.dt_h + st.dt_h
    rho = np.exp(-st.dt_h / 12.0)
    L = int(off.max()) + horizon * stride
    e = np.empty((3, len(t0), horizon))
    for ti in np.unique(issue):
        # one stream per variable, so every re-plan inside this run reads the same numbers
        z = np.stack([np.random.default_rng([seed, int(ti), v]).standard_normal(L) for v in range(3)])
        ar = np.empty_like(z)
        ar[:, 0] = z[:, 0]
        for k in range(1, L):
            ar[:, k] = rho * ar[:, k - 1] + np.sqrt(1 - rho ** 2) * z[:, k]
        rows = np.flatnonzero(issue == ti)
        cols = off[rows][:, None] + stride * np.arange(horizon)[None, :]
        e[:, rows, :] = ar[:, cols]
    wx = twin.wx
    temp = wx["temp_c"].to_numpy()[idx] + e[0] * sigma_temp(lead_h)
    wind10 = wx["wind10_ms"].to_numpy()[idx] * np.exp(e[1] * sigma_logwind(lead_h) - 0.5 * sigma_logwind(lead_h) ** 2)
    clear = wx["ghi_clear_wm2"].to_numpy()[idx]
    kt = np.where(clear > 1, wx["ghi_wm2"].to_numpy()[idx] / np.maximum(clear, 1), 0.0)
    ghi = np.clip(kt + e[2] * sigma_kt(lead_h), 0, 1.1) * clear
    return {"idx": idx, "lead_h": lead_h, "temp": temp, "wind10": wind10, "ghi": ghi}


def perturb_for_training(st: Station, wx: pd.DataFrame, lead_h: np.ndarray, rng) -> dict[str, np.ndarray]:
    """Independent forecast-like noise at a given lead, so models train on realistic inputs."""
    temp = wx["temp_c"].to_numpy() + rng.standard_normal(len(wx)) * sigma_temp(lead_h)
    s = sigma_logwind(lead_h)
    wind10 = wx["wind10_ms"].to_numpy() * np.exp(rng.standard_normal(len(wx)) * s - 0.5 * s ** 2)
    clear = wx["ghi_clear_wm2"].to_numpy()
    kt = np.where(clear > 1, wx["ghi_wm2"].to_numpy() / np.maximum(clear, 1), 0.0)
    ghi = np.clip(kt + rng.standard_normal(len(wx)) * sigma_kt(lead_h), 0, 1.1) * clear
    return {"temp": temp, "wind10": wind10, "ghi": ghi}


LOAD_FEATURES = ["hs1", "hc1", "hs2", "hc2", "ds", "dc", "meal", "crew", "experiment_kw", "temp", "wind10",
                 "wind_chill", "hdd_wind", "lag48", "lag168", "lead_h"]


def demand_features(twin, idx: np.ndarray, lead_h: np.ndarray, temp, wind10, target: np.ndarray) -> pd.DataFrame:
    """Rows for target steps `idx` (flattened). `target` is the station history array (lags)."""
    st = twin.st
    idx = idx.ravel()
    lh = twin.local_hour[idx]
    doy = twin.index[idx].dayofyear.to_numpy()
    a, d = 2 * np.pi * lh / 24, 2 * np.pi * doy / 365
    lag = lambda h: np.where(idx - int(h / st.dt_h) >= 0, target[np.maximum(idx - int(h / st.dt_h), 0)], np.nan)
    temp, wind10 = np.ravel(temp), np.ravel(wind10)
    h = st.loads["heat"]
    return pd.DataFrame({
        "hs1": np.sin(a), "hc1": np.cos(a), "hs2": np.sin(2 * a), "hc2": np.cos(2 * a),
        "ds": np.sin(d), "dc": np.cos(d),
        "meal": np.isin(np.floor(lh), (7, 12, 19)).astype(float),
        "crew": twin.crew[idx], "experiment_kw": twin.demand["experiment_kw"].to_numpy()[idx],
        "temp": temp, "wind10": wind10, "wind_chill": wind_chill(temp, wind10),
        "hdd_wind": np.maximum(0, h["indoor_c"] - temp) * (1 + h["wind_infiltration"] * wind10),
        "lag48": lag(48), "lag168": lag(168), "lead_h": np.ravel(lead_h),
    })


REN_FEATURES = ["physics_kw", "elevation", "kt_fc", "temp", "wind10", "hub_fc", "lead_h", "panel_clear"]


def renewable_physics(twin, idx: np.ndarray, temp, wind10, ghi):
    """Physics forecasts for PV and wind at target steps (flattened)."""
    st = twin.st
    flat = idx.ravel()
    sub = twin.wx.iloc[flat].copy()  # index = target times (may repeat across issues)
    sub["temp_c"] = np.ravel(temp)
    sub["wind10_ms"] = np.ravel(wind10)
    ratio = twin.wx["wind50_ms"].to_numpy()[flat] / np.maximum(twin.wx["wind10_ms"].to_numpy()[flat], 0.5)
    sub["wind50_ms"] = sub["wind10_ms"] * ratio
    sub["ghi_wm2"] = np.ravel(ghi)
    # panel snow cover is observed at issue time and recovers at the known rate
    sp = solar_position(st, twin.index)
    elev = sp["elevation"].to_numpy()[flat]
    pv = pv_power(st, sub, solpos=sp.iloc[flat])
    wd = wind_power(st, sub)
    from aurora.twin.assets import hub_wind
    hub = hub_wind(st, sub)
    clear = twin.wx["ghi_clear_wm2"].to_numpy()[flat]
    kt = np.where(clear > 1, np.ravel(ghi) / np.maximum(clear, 1), 0.0)
    return pv, wd, hub, elev, kt, sub["panel_clear"].to_numpy()
