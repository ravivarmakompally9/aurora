"""Phase 4 gate: optimiser speed, Storm Mode, guardrail, tier protection and fallback."""
import numpy as np
import pandas as pd
import pytest

from aurora.config import load_station
from aurora.forecasting.models import load_or_train
from aurora.guardrail.limits import Guardrail
from aurora.optimizer.mpc import LIVE_BLOCKS, YEAR_BLOCKS, AuroraController
from aurora.twin.simulator import Setpoint, Twin
from tests.test_phase2_twin import balance_errors


@pytest.fixture(scope="module")
def st_f():
    st = load_station("bharati")
    return st, load_or_train(Twin(st))


def test_live_48h_plan_solves_under_30s(st_f):
    st, f = st_f
    tw = Twin(st, start="2023-07-01", end="2023-07-04")
    c = AuroraController(st, f, blocks=LIVE_BLOCKS)
    c.decide(tw, 0)
    assert c.plan is not None and c.plan.ok
    assert c.plan.step_h.sum() == pytest.approx(48)
    assert max(c.solve_times) < 30


@pytest.mark.parametrize("start", ["2023-01-20", "2023-10-05"])  # summer, and a cold-season case that once failed
def test_storm_mode_prepares_before_blizzard(st_f, start):
    st, f = st_f
    tw = Twin(st, start=start, end=pd.Timestamp(start) + pd.Timedelta(days=5))
    onset = 64  # 16 h ahead
    tw.inject("blizzard", t=onset, hours=30, peak_ms=34)
    c = AuroraController(st, f, blocks=YEAR_BLOCKS, replan_every=4)
    log = tw.run(c, 0, onset + 160)
    blizzard = int(np.flatnonzero(tw.wind10 >= st.control.storm_wind_ms)[0])  # wind crosses the Storm Mode threshold
    first_storm = int(np.flatnonzero(log["mode"].to_numpy() == "storm")[0])
    assert blizzard - first_storm >= 12 / st.dt_h, "Storm Mode must activate at least 12 h before the blizzard"
    assert log.soc.iloc[blizzard] >= st.control.storm_soc_target - 0.05
    assert log.tank_soc.iloc[blizzard] >= st.control.storm_tank_target - 0.1
    in_storm = tw.wind10[log.t.to_numpy()] >= st.control.storm_wind_ms
    assert (log.gens_on[in_storm] >= 1).all(), "standby generator online whenever blizzard winds blow"
    over = tw.hub_wind[log.t.to_numpy()] >= st.wind.cut_out_ms
    assert (log.wind_kw[over] == 0).all()
    assert log.unserved_tier1.sum() == 0
    assert any(cd["title"] == "Storm Mode activated" for cd in c.explainer.cards)


def test_generator_failure_never_sheds_tier1(st_f):
    st, f = st_f
    tw = Twin(st, start="2023-07-15", end="2023-07-18")
    tw.inject("generator_failure", t=8, hours=48, gen=0)
    tw.inject("generator_failure", t=8, hours=48, gen=1)
    c = AuroraController(st, f, blocks=YEAR_BLOCKS, replan_every=4)
    log = tw.run(c, 0, 200)
    assert log.g1_kw.iloc[8:200].max() == 0 and log.g2_kw.iloc[8:200].max() == 0
    assert log.unserved_tier1.sum() == 0
    assert log.heat_unserved_kw.sum() == 0
    el, heat = balance_errors(log)
    assert el < 1e-6 and heat < 1e-6


def test_fallback_within_one_cycle(st_f):
    st, f = st_f
    tw = Twin(st, start="2023-03-01", end="2023-03-03")
    c = AuroraController(st, f, blocks=YEAR_BLOCKS, replan_every=4)
    tw.run(c, 0, 4)
    c.force_fail = True
    c.plan = None  # previous plan also lost (worst case)
    sp = c.decide(tw, 4)
    assert sp.mode == "fallback" and sp.source == "fallback"
    assert any(cd["title"] == "Fallback to diesel-first" for cd in c.explainer.cards)
    c.force_fail = False
    c.request_replan()
    assert c.decide(tw, 5).source == "aurora"


def test_guardrail_blocks_unsafe_setpoints():
    st = load_station("bharati")
    tw = Twin(st, start="2023-07-01", end="2023-07-02")
    tw.inject("generator_failure", t=0, hours=24, gen=0)
    g = Guardrail(st)
    sp = Setpoint(gen_on=[True, False, False], gen_kw=[100, 0, 0], batt_kw=0,
                  shed_kw={"el_tier1_kw": 10.0, "el_tier2_kw": 5.0})
    tw.state.soc_kwh = st.battery.soc_emergency * st.battery.capacity_kwh  # empty battery
    out, v = g.validate(tw, 0, sp)
    rules = {x["rule"] for x in v}
    assert not out.gen_on[0], "tripped unit must be removed"
    assert out.shed_kw["el_tier1_kw"] == 0 and out.shed_kw["el_tier2_kw"] == 0
    assert any(out.gen_on[1:]), "reserve must be restored by starting a healthy unit"
    assert {"equipment_unavailable", "tier_protection", "spinning_reserve"} <= rules


def test_all_generators_tripped_still_plans(st_f):
    """With every unit out, AURORA must keep planning (battery, renewables, shedding) instead of failing."""
    st, f = st_f
    tw = Twin(st, start="2023-01-15", end="2023-01-17")
    tw.reset(soc=st.battery.soc_emergency + 0.02)  # nearly empty battery: water quota cannot be met
    for g in range(len(st.gensets)):
        tw.inject("generator_failure", t=0, hours=12, gen=g)
    tw.inject("blizzard", t=8, hours=20, peak_ms=30)  # Storm Mode wants a standby unit that does not exist
    c = AuroraController(st, f, blocks=YEAR_BLOCKS, replan_every=4)
    log = tw.run(c, 0, 24)
    assert c.failures == 0 and (log["mode"] != "fallback").all()
    assert log.gen_kw.max() == 0


def test_guardrail_enforces_minimum_run_time():
    st = load_station("bharati")
    tw = Twin(st, start="2023-07-01", end="2023-07-02")
    g = Guardrail(st)
    tw.state.gen_on[:] = [True, False, False]
    tw.state.gen_on_since[:] = [-2, -10 ** 6, -10 ** 6]  # G1 started 30 min before t=0
    sp = Setpoint(gen_on=[False, False, False], gen_kw=[0, 0, 0], batt_kw=0)
    out, _ = g.validate(tw, 0, sp)
    assert out.gen_on[0], "a unit inside its minimum run time must not be stopped"


def test_analysis_switches_and_overrides(st_f):
    """Capabilities switched off for the savings breakdown are really unused; overrides change only a copy."""
    from aurora.sim import apply_overrides
    st, f = st_f
    st2 = apply_overrides(st, {"pv.kwp": 0.0, "loads.crew.summer": 47, "genset_min_up_h": 1.0})
    assert st2.pv.kwp == 0 and st2.loads["crew"]["summer"] == 47 and st2.genset_min_up_h == 1.0
    assert st.pv.kwp > 0 and st.loads["crew"]["summer"] != 47  # original untouched
    tw = Twin(st, start="2023-07-10", end="2023-07-12")
    c = AuroraController(st, f, blocks=YEAR_BLOCKS, replan_every=4,
                         features={"battery": False, "tank": False, "p2h": False, "flexible": False})
    log = tw.run(c, 0, 48)
    p = c.plan
    assert p.ch.max() < 1e-6 and p.dis.max() < 1e-6 and p.tank_ch.max() < 1e-6 and p.p2h.max() < 1e-6
    assert p.water.max() < 1e-6  # flexible loads follow the fixed schedule, not the optimiser
    assert (log.tank_ch_kw == 0).all() and (log.tank_dis_kw == 0).all()
    assert log.unserved_tier1.sum() == 0
