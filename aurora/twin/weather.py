"""Weather input for the digital twin.

Real data: NASA POWER hourly reanalysis (MERRA-2 based) for the station coordinates,
downloaded once and stored in data/raw so the system runs offline (NFR-01).
Fallback: a seeded synthetic generator with katabatic winds and blizzards.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from aurora.config import DATA_DIR, Station

log = logging.getLogger(__name__)

POWER_URL = "https://power.larc.nasa.gov/api/temporal/hourly/point"
POWER_PARAMS = ["T2M", "WS10M", "WS50M", "ALLSKY_SFC_SW_DWN", "CLRSKY_SFC_SW_DWN", "PS", "RH2M"]
RENAME = {"T2M": "temp_c", "WS10M": "wind10_ms", "WS50M": "wind50_ms", "ALLSKY_SFC_SW_DWN": "ghi_wm2",
          "CLRSKY_SFC_SW_DWN": "ghi_clear_wm2", "PS": "pressure_kpa", "RH2M": "rh_pct"}

BLIZZARD_WIND_MS = 15.0  # 10 m wind at which drifting snow and blizzard conditions start


def raw_path(st: Station) -> Path:
    y0, y1 = min(st.weather_years), max(st.weather_years)
    return DATA_DIR / "raw" / f"{st.key}_nasa_power_{y0}_{y1}.csv"


def fetch_nasa_power(st: Station, timeout: float = 120.0) -> Path:
    """Download hourly NASA POWER data (UTC) for every configured year."""
    import httpx

    frames = []
    for year in st.weather_years:
        params = {
            "parameters": ",".join(POWER_PARAMS), "community": "RE",
            "longitude": st.lon, "latitude": st.lat,
            "start": f"{year}0101", "end": f"{year}1231",
            "format": "JSON", "time-standard": "UTC",
        }
        r = httpx.get(POWER_URL, params=params, timeout=timeout)
        r.raise_for_status()
        p = r.json()["properties"]["parameter"]
        df = pd.DataFrame(p)
        df.index = pd.to_datetime(df.index, format="%Y%m%d%H", utc=True)
        frames.append(df)
        log.info("fetched %s %s: %d rows", st.key, year, len(df))
    out = pd.concat(frames).sort_index()
    out = out.replace(-999.0, np.nan)
    path = raw_path(st)
    path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(path, index_label="time_utc")
    meta = {"source": "NASA POWER hourly API", "url": POWER_URL, "community": "RE",
            "lat": st.lat, "lon": st.lon, "years": list(st.weather_years), "parameters": POWER_PARAMS}
    path.with_suffix(".json").write_text(json.dumps(meta, indent=2))
    return path


def synthetic_hourly(st: Station, seed: int = 7) -> pd.DataFrame:
    """Seeded hourly weather with seasonal cycle, AR(1) anomalies, katabatic diurnal wind and blizzards."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range(f"{min(st.weather_years)}-01-01", f"{max(st.weather_years)}-12-31 23:00", freq="h", tz="UTC")
    n = len(idx)
    doy = idx.dayofyear.to_numpy()
    hour = ((idx.hour + st.utc_offset_h) % 24).to_numpy()
    peak = 15 if st.is_south else 197
    t_summer, t_winter = (-1.0, -18.0) if st.is_south else (5.0, -14.0)
    tm = (t_summer + t_winter) / 2 + (t_summer - t_winter) / 2 * np.cos(2 * np.pi * (doy - peak) / 365)
    ta = np.zeros(n); lw = np.zeros(n); lc = np.zeros(n)
    e = rng.standard_normal((3, n))
    for i in range(1, n):
        ta[i] = 0.97 * ta[i - 1] + 0.55 * e[0, i]
        lw[i] = 0.94 * lw[i - 1] + 0.30 * e[1, i]
        lc[i] = 0.90 * lc[i - 1] + 0.45 * e[2, i]
    wmean = 7.0 if st.is_south else 5.0
    wind = wmean * np.exp(lw - 0.045) * (1 + 0.12 * np.cos(2 * np.pi * (hour - 4) / 24))
    cloud = 1 / (1 + np.exp(-(lc + 0.1)))
    storm = np.zeros(n, bool)
    i = 0
    while i < n:
        if rng.random() < 0.004:
            dur = int(rng.integers(14, 44))
            k = np.arange(min(dur, n - i))
            wind[i:i + len(k)] = np.maximum(wind[i:i + len(k)], 14 + 19 * np.sin(np.pi * (k + 0.5) / dur))
            cloud[i:i + len(k)] = 1.0
            storm[i:i + len(k)] = True
            i += dur
        i += 1
    temp = tm + ta + 3.5 * storm
    df = pd.DataFrame({"temp_c": temp, "wind10_ms": wind, "wind50_ms": wind * 1.25,
                       "pressure_kpa": 98.5 + 0.8 * np.sin(lw), "rh_pct": 70 + 20 * cloud}, index=idx)
    import pvlib
    sp = pvlib.solarposition.get_solarposition(idx, st.lat, st.lon)
    cs = pvlib.clearsky.haurwitz(sp["apparent_zenith"])["ghi"].to_numpy()
    df["ghi_clear_wm2"] = cs
    df["ghi_wm2"] = cs * (1 - 0.75 * cloud ** 3.4)
    return df


def load_hourly(st: Station, allow_synthetic: bool = True) -> tuple[pd.DataFrame, str]:
    path = raw_path(st)
    if path.exists():
        df = pd.read_csv(path, index_col="time_utc", parse_dates=True)
        df.index = pd.to_datetime(df.index, utc=True)
        return df.rename(columns=RENAME), "nasa_power"
    if not allow_synthetic:
        raise FileNotFoundError(f"{path} missing; run `aurora fetch-weather --station {st.key}`")
    log.warning("No NASA POWER file for %s, using synthetic weather", st.key)
    return synthetic_hourly(st), "synthetic"


def load_weather(st: Station, allow_synthetic: bool = True) -> pd.DataFrame:
    """Weather at the control step (15 min), gap-filled, with derived storm and snow-cover fields."""
    hourly, source = load_hourly(st, allow_synthetic)
    hourly = hourly.interpolate(limit_direction="both")
    end = hourly.index[-1] + pd.Timedelta(minutes=60 - st.control.step_min)
    idx = pd.date_range(hourly.index[0], end, freq=f"{st.control.step_min}min")
    df = hourly.reindex(hourly.index.union(idx)).interpolate(method="time", limit_direction="both").reindex(idx)
    df[["ghi_wm2", "ghi_clear_wm2"]] = df[["ghi_wm2", "ghi_clear_wm2"]].clip(lower=0)
    df.attrs["source"] = source
    return add_derived(st, df)


def add_derived(st: Station, df: pd.DataFrame) -> pd.DataFrame:
    """Storm flag, panel snow cover, and the station-clock calendar used by loads and forecasts."""
    df = df.copy()
    df["storm"] = (df["wind10_ms"] >= BLIZZARD_WIND_MS).to_numpy()
    # Drifting snow covers panels during blizzards; crew clearing and sublimation recover ~2.5 %/h.
    cover = np.ones(len(df))
    rec = 0.025 * st.dt_h
    s = df["storm"].to_numpy()
    for i in range(1, len(df)):
        cover[i] = min(cover[i - 1], 0.35) if s[i] else min(1.0, cover[i - 1] + rec)
    df["panel_clear"] = cover
    local = df.index + pd.Timedelta(hours=st.utc_offset_h)
    df["local_hour"] = local.hour + local.minute / 60
    df["local_date"] = local.normalize().tz_localize(None)
    return df


def inject_blizzard(st: Station, df: pd.DataFrame, start: pd.Timestamp, hours: float = 30, peak_ms: float = 32.0) -> pd.DataFrame:
    """FR-30: overlay a blizzard (wind ramps to peak, sky closes, temperature rises a few degrees)."""
    df = df.copy()
    n = int(hours / st.dt_h)
    i0 = df.index.get_indexer([start], method="nearest")[0]
    sl = slice(i0, min(i0 + n, len(df)))
    k = np.arange(sl.stop - sl.start)
    shape = np.sin(np.pi * (k + 0.5) / n)
    df.iloc[sl, df.columns.get_loc("wind10_ms")] = np.maximum(df["wind10_ms"].to_numpy()[sl], 12 + (peak_ms - 12) * shape)
    df.iloc[sl, df.columns.get_loc("wind50_ms")] = df["wind10_ms"].to_numpy()[sl] * 1.2
    df.iloc[sl, df.columns.get_loc("ghi_wm2")] = df["ghi_wm2"].to_numpy()[sl] * 0.15
    df.iloc[sl, df.columns.get_loc("temp_c")] = df["temp_c"].to_numpy()[sl] + 4 * shape
    df.iloc[sl, df.columns.get_loc("rh_pct")] = 95.0
    return add_derived(st, df.drop(columns=["storm", "panel_clear", "local_hour", "local_date"]))
