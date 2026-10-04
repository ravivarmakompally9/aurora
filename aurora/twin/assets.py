"""Polar-aware renewable physics (FR-06, FR-07), shared by the twin and the forecasters.

PV: pvlib sun position, Erbs decomposition, tilted-plane irradiance with snow albedo,
cold-cell gain and panel snow cover. Wind: hub-height shear, cold-air density,
rime-icing derate and storm cut-out.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pvlib

from aurora.config import Station

_SOLPOS_CACHE: dict[tuple, pd.DataFrame] = {}


def solar_position(st: Station, index: pd.DatetimeIndex) -> pd.DataFrame:
    key = (st.lat, st.lon, index[0], index[-1], len(index))
    if key not in _SOLPOS_CACHE:
        # Evaluate at the middle of each step so 15-min averages line up with the sun.
        mid = index + pd.Timedelta(minutes=st.control.step_min / 2)
        sp = pvlib.solarposition.get_solarposition(mid, st.lat, st.lon)
        sp.index = index
        _SOLPOS_CACHE[key] = sp[["apparent_zenith", "zenith", "azimuth", "elevation"]]
    return _SOLPOS_CACHE[key]


def pv_power(st: Station, wx: pd.DataFrame, ghi: np.ndarray | None = None) -> np.ndarray:
    """AC output in kW. `ghi` overrides the weather column (used for forecasts)."""
    pv = st.pv
    if pv.kwp <= 0:
        return np.zeros(len(wx))
    sp = solar_position(st, wx.index)
    ghi = wx["ghi_wm2"].to_numpy() if ghi is None else ghi
    zen = sp["zenith"].to_numpy()
    up = sp["elevation"].to_numpy() > 0.5
    ghi = np.where(up, ghi, 0.0)
    erbs = pvlib.irradiance.erbs(ghi, zen, wx.index)
    poa = pvlib.irradiance.get_total_irradiance(
        pv.tilt_deg, pv.azimuth_deg, sp["apparent_zenith"].to_numpy(), sp["azimuth"].to_numpy(),
        erbs["dni"], ghi, erbs["dhi"], albedo=pv.albedo, model="isotropic")["poa_global"]
    poa = np.nan_to_num(np.asarray(poa, dtype=float), nan=0.0)
    t_cell = wx["temp_c"].to_numpy() + 0.025 * poa
    p = pv.kwp * poa / 1000 * (1 + pv.temp_coeff * (t_cell - 25)) * pv.system_derate
    p *= wx["panel_clear"].to_numpy() if "panel_clear" in wx else 1.0
    return np.clip(p, 0.0, pv.kwp * 1.05)


def hub_wind(st: Station, wx: pd.DataFrame, wind10: np.ndarray | None = None) -> np.ndarray:
    w10 = wx["wind10_ms"].to_numpy() if wind10 is None else wind10
    w50 = wx["wind50_ms"].to_numpy() if "wind50_ms" in wx else w10 * 1.25
    ratio = np.where(wx["wind10_ms"].to_numpy() > 0.5, w50 / np.maximum(wx["wind10_ms"].to_numpy(), 0.5), 1.25)
    alpha = np.clip(np.log(np.maximum(ratio, 1.0)) / np.log(5.0), 0.05, 0.3)
    return w10 * (st.wind.hub_height_m / 10.0) ** alpha


def icing_factor(wx: pd.DataFrame) -> np.ndarray:
    t, rh = wx["temp_c"].to_numpy(), wx["rh_pct"].to_numpy()
    return np.where((t > -10) & (t < 0) & (rh >= 95), 0.7, 1.0)


def wind_power(st: Station, wx: pd.DataFrame, wind10: np.ndarray | None = None, enabled: np.ndarray | None = None) -> np.ndarray:
    """kW from the turbine fleet. Zero above cut-out (FR-07) or when the guardrail parks turbines."""
    w = st.wind
    if w.total_kw <= 0:
        return np.zeros(len(wx))
    v = hub_wind(st, wx, wind10)
    rho = wx["pressure_kpa"].to_numpy() * 1000 / (287.05 * (wx["temp_c"].to_numpy() + 273.15)) / 1.225
    frac = np.clip((v ** 3 - w.cut_in_ms ** 3) / (w.rated_ms ** 3 - w.cut_in_ms ** 3), 0, 1)
    p = w.total_kw * np.minimum(frac * np.minimum(rho, 1.2), 1.0) * icing_factor(wx)
    p = np.where((v < w.cut_in_ms) | (v >= w.cut_out_ms), 0.0, p)
    if enabled is not None:
        p = np.where(enabled, p, 0.0)
    return p


def renewables(st: Station, wx: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({"pv_kw": pv_power(st, wx), "wind_kw": wind_power(st, wx),
                         "hub_wind_ms": hub_wind(st, wx)}, index=wx.index)
