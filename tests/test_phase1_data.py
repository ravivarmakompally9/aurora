"""Phase 1 gate: data and physics behave like a polar station."""
import numpy as np
import pandas as pd
import pytest

from aurora.config import load_station, station_keys
from aurora.twin.assets import pv_power, wind_power
from aurora.twin.loads import build_demand
from aurora.twin.weather import inject_blizzard, load_weather, synthetic_hourly


@pytest.fixture(scope="module")
def bharati():
    st = load_station("bharati")
    wx = load_weather(st)
    return st, wx, build_demand(st, wx)


def test_all_station_configs_load():
    keys = station_keys()
    assert {"bharati", "maitri", "himadri"} <= set(keys)
    for k in keys:
        st = load_station(k)
        assert st.gensets and st.battery.soc_min < st.battery.soc_max


def test_weather_is_complete_15min(bharati):
    st, wx, _ = bharati
    assert wx.index.freq is None or pd.Timedelta(wx.index.freq) == pd.Timedelta(minutes=15)
    assert (wx.index[1] - wx.index[0]) == pd.Timedelta(minutes=15)
    assert not wx[["temp_c", "wind10_ms", "ghi_wm2"]].isna().any().any()
    assert len(wx) >= 3 * 365 * 96


def test_heat_rises_as_temperature_falls(bharati):
    st, wx, d = bharati
    cold = d.heat_kw[wx.temp_c < -25].mean()
    mild = d.heat_kw[wx.temp_c > -8].mean()
    assert cold > 1.3 * mild


def test_load_rises_with_crew(bharati):
    _, _, d = bharati
    assert d.el_fixed_kw[d.crew > 50].mean() > d.el_fixed_kw[d.crew < 30].mean() + 15
    assert d.water_kwh_day[d.crew > 50].mean() > d.water_kwh_day[d.crew < 30].mean()


def test_polar_night_pv_near_zero(bharati):
    st, wx, _ = bharati
    pv = pv_power(st, wx)
    june = wx.index.month == 6
    jan = wx.index.month == 1
    assert pv[june].mean() < 0.01 * st.pv.kwp
    assert pv[jan].mean() > 0.2 * st.pv.kwp


def test_wind_cuts_out_in_blizzard(bharati):
    st, wx, _ = bharati
    start = wx.index[96 * 200]
    storm = inject_blizzard(st, wx, start, hours=30, peak_ms=34)
    p = wind_power(st, storm)
    from aurora.twin.assets import hub_wind
    v = hub_wind(st, storm)
    assert np.all(p[v >= st.wind.cut_out_ms] == 0)
    assert storm.storm.iloc[96 * 200 + 40]


def test_synthetic_fallback_shapes():
    st = load_station("bharati")
    df = synthetic_hourly(st)
    assert {"temp_c", "wind10_ms", "ghi_wm2"} <= set(df.columns)
    assert df.ghi_wm2[df.index.month == 6].mean() < 5
