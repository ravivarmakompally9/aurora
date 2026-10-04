"""Phase 2 gate: the twin conserves energy, runs a year fast, and handles injected events."""
import time

import numpy as np
import pytest

from aurora.config import load_station
from aurora.twin.baseline import DieselFirst
from aurora.twin.kpi import kpis
from aurora.twin.simulator import Twin


def balance_errors(log):
    el = (log.gen_kw + log.pv_kw + log.wind_kw - log.curtail_kw - log.batt_kw
          - (log.el_load_kw + log.p2h_kw - log.filter(like="unserved_tier").sum(axis=1)))
    heat = (log.heat_rec_kw + log.p2h_heat_kw + log.tank_dis_kw + log.boiler_kw + log.heat_unserved_kw
            - (log.heat_kw + log.tank_ch_kw + log.heat_dump_kw))
    return np.abs(el).max(), np.abs(heat).max()


@pytest.fixture(scope="module")
def year():
    st = load_station("bharati")
    tw = Twin(st, start="2023-01-01", end="2023-12-31 23:45")
    t = time.time()
    log = tw.run(DieselFirst())
    return st, tw, log, time.time() - t


def test_baseline_year_under_a_minute(year):
    _, tw, log, secs = year
    assert len(log) == tw.n == 365 * 96
    assert secs < 60


def test_energy_and_heat_balance_close_every_step(year):
    _, _, log, _ = year
    el, heat = balance_errors(log)
    assert el < 1e-6 and heat < 1e-6


def test_baseline_serves_all_critical_load(year):
    st, _, log, _ = year
    k = kpis(st, log)
    assert k["critical_served_pct"] == 100.0
    assert k["fuel_l"] > 0 and 0 < k["renewable_fraction"] < 1


def test_water_production_always_completes(year):
    _, tw, log, _ = year
    day = tw.day_id[log.t.to_numpy()]
    produced = log.groupby(day).water_kw.sum() * tw.st.dt_h
    needed = tw.demand.water_kwh_day.groupby(day).first()
    full_days = log.groupby(day).size() == 96
    assert np.allclose(produced[full_days], needed[full_days], rtol=1e-6)


def test_generator_failure_keeps_tier1(year):
    st = load_station("bharati")
    tw = Twin(st, start="2023-07-01", end="2023-07-04")
    tw.inject("generator_failure", t=0, hours=72, gen=0)
    log = tw.run(DieselFirst())
    assert log.g1_kw.max() == 0
    assert log.unserved_tier1.sum() == 0
    el, heat = balance_errors(log)
    assert el < 1e-6 and heat < 1e-6


def test_blizzard_parks_wind_and_covers_panels():
    st = load_station("bharati")
    tw = Twin(st, start="2023-01-10", end="2023-01-14")
    before = tw.wind_avail.copy()
    tw.inject("blizzard", t=96, hours=30, peak_ms=34)
    peak = slice(96 + 50, 96 + 70)
    assert (tw.hub_wind[peak] >= st.wind.cut_out_ms).all()
    assert (tw.wind_avail[peak] == 0).all() and before[peak].max() >= 0
    assert tw.wx.panel_clear.iloc[96 + 80] < 1.0


def test_fuel_leak_drains_tank():
    st = load_station("bharati")
    a = Twin(st, start="2023-03-01", end="2023-03-02")
    b = Twin(st, start="2023-03-01", end="2023-03-02")
    b.inject("fuel_leak", t=4, hours=6, litres=3000)
    la, lb = a.run(DieselFirst()), b.run(DieselFirst())
    assert la.fuel_level_l.iloc[-1] - lb.fuel_level_l.iloc[-1] == pytest.approx(3000, rel=1e-6)
