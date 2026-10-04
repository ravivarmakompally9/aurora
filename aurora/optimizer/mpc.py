"""AURORA controller: sense -> predict -> decide -> guard -> act (PRD §5, §6).

Every re-plan it forecasts 48 h at 15 min, assesses storm risk, solves the MILP on a
variable-resolution grid (fine near term, hourly later, PRD §16), and executes only the
current step after the safety guardrail approves it. If the optimiser fails it reuses the
previous valid plan for up to 6 h, then falls back to diesel-first rules (FR-16).
"""
from __future__ import annotations

import logging

import numpy as np

from aurora.config import Station
from aurora.guardrail.limits import Guardrail
from aurora.optimizer.explain import Explainer
from aurora.optimizer.milp import MAX_DAYS, SHED_TIERS, DispatchMILP, Plan, PlanInputs
from aurora.storm_mode import storm
from aurora.twin.baseline import DieselFirst
from aurora.twin.simulator import Setpoint

log = logging.getLogger(__name__)

LIVE_BLOCKS = [1] * 24 + [4] * 42   # 6 h at 15 min, then hourly to 48 h (66 plan steps)
YEAR_BLOCKS = [4] * 48              # hourly for the year-long comparison


def largest_step_kw(st: Station) -> float:
    el = st.loads["electric"]
    return float(max(el["tier1_life_support"]["water_max_kw"], max(el["tier3_science"]["experiment_kw"])))


class Grid:
    """Maps fine forecast steps (twin steps) onto variable-length plan steps."""

    def __init__(self, blocks: list[int]):
        self.blocks = np.array(blocks)
        self.starts = np.r_[0, np.cumsum(self.blocks)[:-1]]
        self.ends = np.cumsum(self.blocks)
        self.H = int(self.ends[-1])

    def agg(self, a: np.ndarray, how: str = "mean") -> np.ndarray:
        if how == "max":
            return np.maximum.reduceat(a, self.starts)
        return np.add.reduceat(a, self.starts) / self.blocks

    def block_of(self, j: int) -> int:
        return int(min(np.searchsorted(self.ends, j, side="right"), len(self.blocks) - 1))


def build_inputs(st: Station, twin, t: int, fc: dict, grid: Grid, sa: storm.StormAssessment) -> PlanInputs:
    T = len(grid.blocks)
    step_h = grid.blocks * st.dt_h
    idx_fine = fc["idx"]
    idx = idx_fine[grid.starts]
    b, tk = st.battery, st.tank
    park = grid.agg(sa.park.astype(float), "max") > 0
    turb = (~park).astype(float)
    load, load90 = grid.agg(fc["load_p50"]), grid.agg(fc["load_p90"])
    pv, wind = grid.agg(fc["pv_p50"]), grid.agg(fc["wind_p50"]) * turb
    ren10 = grid.agg(fc["pv_p10"] + fc["wind_p10"]) * np.where(turb > 0, 1, 0) + grid.agg(fc["pv_p10"]) * (1 - turb)
    reserve = (load90 - load) + np.maximum(0, pv + wind - ren10) + np.maximum(
        st.control.reserve_frac_load * load, largest_step_kw(st))

    # deferrable windows: day 0 = rest of today, later days in full when the horizon covers them
    d = np.minimum(twin.day_id[idx] - twin.day_id[t], MAX_DAYS - 1)
    left = twin.deferrable_left(t)
    wreq, wcap, lreq, lcap = (np.zeros(MAX_DAYS) for _ in range(4))
    wreq[0] = wcap[0] = left["water"]
    lreq[0] = lcap[0] = left["laundry"]
    for k in range(1, MAX_DAYS):
        sel = np.flatnonzero(d == k)
        if not len(sel):
            continue
        wcap[k], lcap[k] = twin.water_day[idx[sel[0]]], twin.laundry_day[idx[sel[0]]]
        if step_h[sel].sum() >= 24 - 1e-9:
            wreq[k], lreq[k] = wcap[k], lcap[k]

    soc_floor = np.full(T + 1, b.soc_min * b.capacity_kwh); soc_floor[0] = 0.0
    tank_floor = np.full(T + 1, tk.soc_min * tk.capacity_kwh); tank_floor[0] = 0.0
    min_units = np.zeros(T)
    storm.apply(st, sa, soc_floor, tank_floor, min_units, reserve, grid.block_of, int(round(1 / st.dt_h)))

    avail = np.array([[twin.gen_trip_until[g] < i for i in idx] for g in range(len(st.gensets))], dtype=float)
    return PlanInputs(
        load=load, load_p90=load90, heat=grid.agg(fc["heat_p50"]), pv=pv, wind=wind, ren_p10=ren10,
        tiers={k: grid.agg(twin.el[k][idx_fine]) for k in SHED_TIERS},
        day_of_step=d, water_req=wreq, water_cap=wcap, laundry_req=lreq, laundry_cap=lcap,
        soc0_kwh=twin.state.soc_kwh, tank0_kwh=twin.state.tank_kwh, gen_on0=twin.state.gen_on.astype(float),
        gen_avail=avail, soc_floor=soc_floor, tank_floor=tank_floor, min_units=min_units,
        reserve=reserve, turbines_on=turb)


class AuroraController:
    name = "aurora"

    def __init__(self, st: Station, forecaster, blocks: list[int] | None = None, replan_every: int = 1,
                 time_limit_s: float = 30.0, explain: bool = True, seed: int = 0, mip_gap: float = 0.01,
                 threads: int = 4):
        self.st, self.f = st, forecaster
        self.grid = Grid(blocks or LIVE_BLOCKS)
        self.replan_every = replan_every
        self.T = len(self.grid.blocks)
        self.milp = DispatchMILP(st, list(self.grid.blocks), time_limit_s, mip_gap, threads)
        self.guard = Guardrail(st)
        self.fallback = DieselFirst()
        self.explainer = Explainer(st, forecaster) if explain else None
        if self.explainer:
            self.explainer.bind_plan_lookup(self)
        self.plan: Plan | None = None
        self.plan_t = -10 ** 9
        self.fc: dict | None = None
        self.storm: storm.StormAssessment | None = None
        self.mode = "normal"
        self.solve_times: list[float] = []
        self.failures = 0
        self.force_fail = False   # test / demo hook: simulate optimiser failure
        self.seed = seed

    def plan_step(self, t: int) -> int:
        return self.grid.block_of(t - self.plan_t)

    def _replan(self, twin, t: int):
        out = self.f.forecast(twin, t, self.grid.H, 1, seed=self.seed + t)
        fc = {k: (v[0] if isinstance(v, np.ndarray) and v.ndim == 2 else v) for k, v in out.items()}
        sa = storm.assess(self.st, fc, self.st.dt_h, float(twin.wx["wind10_ms"].iloc[t]), was_active=self.mode == "storm")
        x = build_inputs(self.st, twin, t, fc, self.grid, sa)
        plan = self.milp.solve(x) if not self.force_fail else self.milp._failed("forced failure", 0.0, x)
        self.solve_times.append(plan.solve_s)
        self.fc, self.storm = fc, sa
        prev_mode = self.mode
        if plan.ok:
            self.plan, self.plan_t = plan, t
            self.mode = "storm" if sa.active else "normal"
        else:
            self.failures += 1
            stale_ok = self.plan is not None and (t - self.plan_t) < int(6 / self.st.dt_h)
            if not stale_ok:
                self.plan = None
            self.mode = ("storm" if sa.active else "normal") if stale_ok else "fallback"
            log.warning("optimiser failed at step %d (%s); %s", t, plan.status,
                        "reusing last plan" if stale_ok else "diesel-first fallback")
        if self.explainer:
            self.explainer.on_replan(twin, t, self, plan, prev_mode)

    def decide(self, twin, t: int) -> Setpoint:
        if t - self.plan_t >= self.replan_every or self.plan is None:
            self._replan(twin, t)
        if self.plan is None:
            sp = self.fallback.decide(twin, t)
            sp.mode, sp.source = "fallback", "fallback"
        else:
            k = self.plan_step(t)
            p = self.plan
            G = len(self.st.gensets)
            sp = Setpoint(
                gen_on=[bool(p.u[g, k] > 0.5) for g in range(G)],
                gen_kw=[float(p.p[g, k]) for g in range(G)],
                batt_kw=float(p.ch[k] - p.dis[k]), p2h_kw=float(p.p2h[k]),
                water_kw=float(p.water[k]), laundry_kw=float(p.laundry[k]),
                shed_kw={c: float(p.shed[c][k]) for c in SHED_TIERS},
                turbines_on=bool(p.inputs.turbines_on[k] > 0.5), use_tank=True,
                mode=self.mode, source="aurora")
        sp, violations = self.guard.validate(twin, t, sp)
        if self.explainer:
            self.explainer.on_step(twin, t, sp, violations)
        return sp
