"""Tier 1 (life support) is never shed while anything of lower priority is still powered.

The optimiser's "soft" constraints (spinning reserve, daily water quota, storm standby) can bend when
every generator has failed. These tests check that bending them never trades away Tier 1: life support
is cut only when there is physically not enough energy, and only after Tiers 4, 3, 2 and the
(postponable) water production are already fully cut.
"""
import numpy as np
import pandas as pd
import pytest

from aurora.config import load_station
from aurora.forecasting.models import load_or_train
from aurora.optimizer.milp import MAX_DAYS, SHED_TIERS, DispatchMILP, PlanInputs
from aurora.optimizer.mpc import YEAR_BLOCKS, AuroraController
from aurora.twin.simulator import TIERS, Twin

TIER_KW = {"el_tier4_kw": 10.0, "el_tier3_kw": 14.0, "el_tier2_kw": 12.0}
TIER1_KW = 24.0
T = len(YEAR_BLOCKS)


@pytest.fixture(scope="module")
def milp():
    st = load_station("bharati")
    return st, DispatchMILP(st, YEAR_BLOCKS, time_limit_s=30)


def inputs(st, renewables_kw: float) -> PlanInputs:
    """48 h with every generator out, an almost empty battery and constant renewables."""
    load = TIER1_KW + sum(TIER_KW.values())
    z = np.zeros(T)
    b = st.battery
    return PlanInputs(
        load=np.full(T, load), load_p90=np.full(T, load), heat=np.full(T, 100.0),
        pv=np.full(T, renewables_kw), wind=z.copy(), ren_p10=np.full(T, renewables_kw),
        tiers={k: np.full(T, v) for k, v in TIER_KW.items()},
        day_of_step=np.minimum(np.arange(T) // 24, MAX_DAYS - 1),
        water_req=np.array([300.0, 300.0, 0, 0]), water_cap=np.array([300.0, 300.0, 300.0, 0]),
        laundry_req=np.array([20.0, 20.0, 0, 0]), laundry_cap=np.array([20.0, 20.0, 20.0, 0]),
        soc0_kwh=b.soc_emergency * b.capacity_kwh + 1.0, tank0_kwh=0.0,
        gen_on0=np.zeros(len(st.gensets)), gen_avail=np.zeros((len(st.gensets), T)),
        soc_floor=np.r_[0.0, np.full(T, b.soc_min * b.capacity_kwh)], tank_floor=np.zeros(T + 1),
        min_units=np.ones(T),  # Storm Mode asks for a standby unit that does not exist
        min_on=np.zeros(T), reserve=np.full(T, 40.0), turbines_on=np.ones(T))


def test_plan_keeps_tier1_when_energy_covers_it(milp):
    st, m = milp
    x = inputs(st, renewables_kw=30.0)  # enough for Tier 1 (24 kW) but not for everything
    p = m.solve(x)
    assert p.ok
    t1 = np.array([m.m.t1unserved[t].value for t in range(T)])
    assert t1.max() < 1e-6, "Tier 1 must be fully served while energy allows"
    for k in ("el_tier4_kw", "el_tier3_kw"):
        assert np.allclose(p.shed[k], TIER_KW[k], atol=1e-4), f"{k} must be shed before Tier 1 is touched"


def test_plan_cuts_tier1_only_after_everything_else(milp):
    st, m = milp
    x = inputs(st, renewables_kw=20.0)  # less than Tier 1 alone: a physical shortfall
    p = m.solve(x)
    assert p.ok
    t1 = np.array([m.m.t1unserved[t].value for t in range(T)])
    assert t1.sum() > 0
    assert t1.max() <= TIER1_KW - 20.0 + 1e-4, "only the physically missing Tier 1 power may go unserved"
    for k in SHED_TIERS:
        assert np.allclose(p.shed[k], TIER_KW[k], atol=1e-4), f"{k} must be fully shed before any Tier 1 cut"
    assert p.water.sum() < 1e-6 and p.laundry.sum() < 1e-6, "deferrable loads are postponed before Tier 1"


def test_twin_never_cuts_tier1_while_lower_tiers_run():
    """Executed with AURORA in control: all units tripped, battery near empty, a calm polar-night day."""
    st = load_station("bharati")
    full = Twin(st)
    f = load_or_train(full)
    june = np.flatnonzero((full.index.year == st.test_year) & (full.index.month == 6))
    days = june[: len(june) // 96 * 96].reshape(-1, 96)
    calm = days[np.argmin(full.wind_avail[days].mean(axis=1))]
    start = full.index[calm[0]]
    tw = Twin(st, start=start, end=start + pd.Timedelta(hours=24))
    tw.reset(soc=st.battery.soc_emergency + 0.03)
    for g in range(len(st.gensets)):
        tw.inject("generator_failure", t=0, hours=36, gen=g)
    c = AuroraController(st, f, blocks=YEAR_BLOCKS, replan_every=4)
    log = tw.run(c, 0, 48)

    assert c.failures == 0, "the optimiser must keep planning with every unit out"
    assert ((log.shed_tier4 + log.unserved_tier4) > 0).any(), "scenario must actually force shedding"
    hit = log.unserved_tier1 > 1e-6
    lower = {c: tw.el[c][log.t.to_numpy()] for c in TIERS[:-1]}
    for col in TIERS[:-1]:
        cut = log[f"shed_{col[3:8]}"] + log[f"unserved_{col[3:8]}"]  # planned shedding + emergency cuts
        assert np.allclose(cut[hit], lower[col][hit.to_numpy()]), f"{col} still powered while Tier 1 was cut"
    assert (log.loc[hit, "water_kw"] < 1e-6).all() and (log.loc[hit, "laundry_kw"] < 1e-6).all()
    assert (log.loc[hit, "p2h_kw"] < 1e-6).all()
