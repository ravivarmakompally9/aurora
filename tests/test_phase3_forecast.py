"""Phase 3 gate: forecasts meet the PRD accuracy target and respect polar physics."""
import numpy as np
import pytest

from aurora.config import load_station
from aurora.forecasting.cv import evaluate
from aurora.forecasting.models import load_or_train
from aurora.twin.simulator import Twin


@pytest.fixture(scope="module")
def setup():
    st = load_station("bharati")
    tw = Twin(st)
    return st, tw, load_or_train(tw)


def test_load_mape_24h_below_10pct_on_test_year(setup):
    st, tw, f = setup
    r = evaluate(f, tw, st.test_year, every_h=24)
    assert r["load_mape_24h_pct"] < 10
    assert r["heat_mape_24h_pct"] < 10
    assert r["load_mape_24h_pct"] < r["load_persistence_mape_24h_pct"]


def test_quantiles_ordered_and_horizon_48h(setup):
    st, tw, f = setup
    t0 = int(np.flatnonzero(tw.index.year == st.test_year)[100])
    fc = f.forecast_frame(tw, t0)
    assert len(fc) == 192
    for n in ("load", "heat", "pv", "wind"):
        assert (fc[f"{n}_p10"] <= fc[f"{n}_p50"] + 1e-9).all()
        assert (fc[f"{n}_p50"] <= fc[f"{n}_p90"] + 1e-9).all()


def test_polar_night_pv_forecast_zero(setup):
    st, tw, f = setup
    t0 = int(np.flatnonzero((tw.index.year == st.test_year) & (tw.index.month == 6) & (tw.index.day == 20))[0])
    fc = f.forecast_frame(tw, t0)
    assert fc.pv_p90.max() < 0.02 * st.pv.kwp


def test_no_lookahead_in_load_lags(setup):
    st, tw, f = setup
    t0 = int(np.flatnonzero(tw.index.year == st.test_year)[5000])
    a = f.forecast_frame(tw, t0)
    saved = tw.el_fixed
    tampered = saved.copy()
    tampered[t0 + 1:] *= 3.0
    tw.el_fixed = tampered
    try:
        b = f.forecast_frame(tw, t0)
    finally:
        tw.el_fixed = saved
    assert np.allclose(a.load_p50, b.load_p50)


def test_storm_forecast_flags_blizzard_and_cut_out():
    st = load_station("bharati")
    tw = Twin(st, start="2023-01-01", end="2023-01-20")
    full = Twin(st)
    f = load_or_train(full)
    t0 = 96 * 5
    tw.inject("blizzard", t=t0 + 64, hours=30, peak_ms=34)
    fc = f.forecast_frame(tw, t0)
    assert fc.storm_prob.iloc[64 + 40:64 + 80].max() > 0.8
    assert fc.storm_prob.iloc[:32].max() < 0.5
    assert (fc.wind_p90[fc.hub_wind >= st.wind.cut_out_ms] == 0).all()
