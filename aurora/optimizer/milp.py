"""48 h mixed-integer dispatch of power and heat (PRD §8.2, FR-09..FR-13).

Built once per (station, horizon, step) with mutable parameters, then re-solved every
control cycle with HiGHS through Pyomo's persistent APPSI interface.

Decisions per step: generator on/off, start and output; battery charge/discharge; thermal
tank charge/discharge; power-to-heat; oil boiler; curtailment; heat dump; deferrable water
production and laundry; planned shedding per tier.
Objective: litres of diesel + start cost + battery wear + tier-weighted shedding + small
curtailment penalty + terminal value of stored energy.
Reserve is sized on P90 load and P10 renewables, so the plan is robust without stochastic
programming.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np
import pyomo.environ as pe
from pyomo.contrib.appsi.solvers import Highs

from aurora.config import Station

SHED_TIERS = ("el_tier4_kw", "el_tier3_kw", "el_tier2_kw")
SHED_WEIGHT = {"el_tier4_kw": 2.0, "el_tier3_kw": 6.0, "el_tier2_kw": 200.0}  # litres-equivalent per kWh
TIER1_WEIGHT = 1e6
HEAT_UNSERVED_WEIGHT = 1e4
SOC_SLACK_WEIGHT = 2.0
MAX_DAYS = 4


@dataclass
class PlanInputs:
    """Everything the optimiser needs for one solve (arrays of length T)."""
    load: np.ndarray            # P50 fixed electric load
    load_p90: np.ndarray
    heat: np.ndarray            # P50 heat demand
    pv: np.ndarray              # P50
    wind: np.ndarray            # P50
    ren_p10: np.ndarray         # P10 of pv + wind
    tiers: dict                 # tier column -> P50 kW share (for shedding bounds)
    day_of_step: np.ndarray     # 0..MAX_DAYS-1 relative local day index per step
    water_req: np.ndarray       # [MAX_DAYS] min energy to produce in each day window (kWh)
    water_cap: np.ndarray       # [MAX_DAYS] max energy in each window
    laundry_req: np.ndarray
    laundry_cap: np.ndarray
    soc0_kwh: float
    tank0_kwh: float
    gen_on0: np.ndarray
    gen_avail: np.ndarray       # (G, T) 0/1
    soc_floor: np.ndarray       # per-step soft floor (kWh); Storm Mode raises it at onset
    tank_floor: np.ndarray
    min_units: np.ndarray       # per-step minimum online generators (Storm Mode standby)
    reserve: np.ndarray         # spinning reserve requirement kW
    turbines_on: np.ndarray     # 0/1


@dataclass
class Plan:
    ok: bool
    status: str
    solve_s: float
    objective: float
    step_h: np.ndarray          # (T,) hours per plan step
    u: np.ndarray               # (G, T)
    p: np.ndarray               # (G, T)
    starts: np.ndarray          # (T,) units started
    ch: np.ndarray
    dis: np.ndarray
    soc: np.ndarray             # (T+1,) kWh
    tank: np.ndarray            # (T+1,)
    tank_ch: np.ndarray
    tank_dis: np.ndarray
    p2h: np.ndarray
    boiler: np.ndarray
    dump: np.ndarray
    curt: np.ndarray
    water: np.ndarray
    laundry: np.ndarray
    shed: dict
    fuel_l: np.ndarray          # per step litres
    heat_rec: np.ndarray
    inputs: PlanInputs | None = None


class DispatchMILP:
    """`blocks[t]` = number of twin steps in plan step t (variable resolution: fine first, coarse later).

    Identical generators are modelled by the number of units online (an integer), which removes the
    symmetry that makes per-unit formulations slow; the plan is split back to units afterwards.
    """

    def __init__(self, st: Station, blocks: list[int], time_limit_s: float = 30.0, mip_gap: float = 0.01, threads: int = 4):
        g0 = st.gensets[0]
        if any((g.rated_kw, g.a, g.b, g.min_load, g.heat_recovery) != (g0.rated_kw, g0.a, g0.b, g0.min_load, g0.heat_recovery)
               for g in st.gensets):
            raise NotImplementedError("DispatchMILP assumes identical generators")
        self.st, self.blocks = st, list(blocks)
        self.T = len(self.blocks)
        self.dt = np.array(self.blocks, dtype=float) * st.dt_h
        self.time_limit_s, self.mip_gap = time_limit_s, mip_gap
        self._build()
        self.solver = Highs()
        self.solver.config.time_limit = time_limit_s
        self.solver.config.mip_gap = mip_gap
        self.solver.config.load_solution = False
        self.solver.highs_options = {"threads": threads, "presolve": "on"}  # threads is fixed once HiGHS starts

    # ---------- model ----------
    def _build(self):
        st, T, dt = self.st, self.T, self.dt
        G = len(st.gensets)
        g0 = st.gensets[0]
        b, tk = st.battery, st.tank
        m = pe.ConcreteModel()
        m.T = pe.RangeSet(0, T - 1)
        m.T1 = pe.RangeSet(0, T)
        m.D = pe.RangeSet(0, MAX_DAYS - 1)
        m.K = pe.Set(initialize=SHED_TIERS)
        for name in ("el", "el90", "heat", "pv", "wind", "ren10"):
            setattr(m, name, pe.Param(m.T, mutable=True, initialize=0.0))
        m.tier = pe.Param(m.K, m.T, mutable=True, initialize=0.0)
        m.inday = pe.Param(m.D, m.T, mutable=True, initialize=0.0)
        m.wreq = pe.Param(m.D, mutable=True, initialize=0.0)
        m.wcap = pe.Param(m.D, mutable=True, initialize=0.0)
        m.lreq = pe.Param(m.D, mutable=True, initialize=0.0)
        m.lcap = pe.Param(m.D, mutable=True, initialize=0.0)
        m.soc0 = pe.Param(mutable=True, initialize=0.0)
        m.tank0 = pe.Param(mutable=True, initialize=0.0)
        m.n0 = pe.Param(mutable=True, initialize=0.0)
        m.navail = pe.Param(m.T, mutable=True, initialize=float(G))
        m.socfloor = pe.Param(m.T1, mutable=True, initialize=0.0)
        m.tankfloor = pe.Param(m.T1, mutable=True, initialize=0.0)
        m.minunits = pe.Param(m.T, mutable=True, initialize=0.0)
        m.reserve = pe.Param(m.T, mutable=True, initialize=0.0)
        m.turb = pe.Param(m.T, mutable=True, initialize=1.0)

        rated, pmin = g0.rated_kw, g0.min_load * g0.rated_kw
        fa, fb = g0.a * g0.rated_kw, g0.b
        hr = g0.heat_recovery * st.diesel_kwh_per_l
        defer = st.loads["electric"]
        wmax = defer["tier1_life_support"]["water_max_kw"]
        lmax = defer["tier4_comfort"]["laundry_max_kw"]

        m.n = pe.Var(m.T, within=pe.NonNegativeIntegers, bounds=(0, G))
        m.s = pe.Var(m.T, within=pe.NonNegativeReals)   # starts (integral at optimum since n is integer)
        m.p = pe.Var(m.T, within=pe.NonNegativeReals)
        m.ch = pe.Var(m.T, bounds=(0, b.power_kw))
        m.dis = pe.Var(m.T, bounds=(0, b.power_kw))
        m.soc = pe.Var(m.T1, bounds=(b.soc_emergency * b.capacity_kwh, b.soc_max * b.capacity_kwh))
        m.socslack = pe.Var(m.T1, within=pe.NonNegativeReals)
        m.tch = pe.Var(m.T, bounds=(0, tk.max_charge_kw))
        m.tdis = pe.Var(m.T, bounds=(0, tk.max_discharge_kw))
        m.tank = pe.Var(m.T1, bounds=(0, tk.capacity_kwh))
        m.tankslack = pe.Var(m.T1, within=pe.NonNegativeReals)
        m.p2h = pe.Var(m.T, bounds=(0, st.p2h_max_kw))
        m.boiler = pe.Var(m.T, bounds=(0, st.boiler_max_kw))
        m.dump = pe.Var(m.T, within=pe.NonNegativeReals)
        m.hunserved = pe.Var(m.T, within=pe.NonNegativeReals)
        m.curt = pe.Var(m.T, within=pe.NonNegativeReals)
        m.water = pe.Var(m.T, bounds=(0, wmax))
        m.laundry = pe.Var(m.T, bounds=(0, lmax))
        m.shed = pe.Var(m.K, m.T, within=pe.NonNegativeReals)
        m.t1unserved = pe.Var(m.T, within=pe.NonNegativeReals)
        m.resbatt = pe.Var(m.T, within=pe.NonNegativeReals)
        m.endshort = pe.Var(within=pe.NonNegativeReals)
        m.tankshort = pe.Var(within=pe.NonNegativeReals)

        m.c_pmax = pe.Constraint(m.T, rule=lambda m, t: m.p[t] <= rated * m.n[t])
        m.c_pmin = pe.Constraint(m.T, rule=lambda m, t: m.p[t] >= pmin * m.n[t])
        m.c_avail = pe.Constraint(m.T, rule=lambda m, t: m.n[t] <= m.navail[t])
        m.c_start = pe.Constraint(m.T, rule=lambda m, t: m.s[t] >= m.n[t] - (m.n[t - 1] if t > 0 else m.n0))
        m.c_minunits = pe.Constraint(m.T, rule=lambda m, t: m.n[t] >= m.minunits[t])

        m.c_curt = pe.Constraint(m.T, rule=lambda m, t: m.curt[t] <= m.pv[t] + m.wind[t] * m.turb[t])
        m.c_shed = pe.Constraint(m.K, m.T, rule=lambda m, k, t: m.shed[k, t] <= m.tier[k, t])
        m.c_t1 = pe.Constraint(m.T, rule=lambda m, t: m.t1unserved[t] <= m.el[t])
        m.c_el = pe.Constraint(m.T, rule=lambda m, t:
                               m.p[t] + m.pv[t] + m.wind[t] * m.turb[t] - m.curt[t] + m.dis[t]
                               == m.el[t] - sum(m.shed[k, t] for k in m.K) - m.t1unserved[t]
                               + m.water[t] + m.laundry[t] + m.ch[t] + m.p2h[t])
        m.c_heat = pe.Constraint(m.T, rule=lambda m, t:
                                 hr * (fa * m.n[t] + fb * m.p[t]) + st.p2h_eff * m.p2h[t] + m.tdis[t] + m.boiler[t]
                                 + m.hunserved[t] == m.heat[t] + m.tch[t] + m.dump[t])

        m.c_soc0 = pe.Constraint(expr=m.soc[0] == m.soc0)
        m.c_soc = pe.Constraint(m.T, rule=lambda m, t:
                                m.soc[t + 1] == m.soc[t] + (b.eta_charge * m.ch[t] - m.dis[t] / b.eta_discharge) * dt[t])
        m.c_socfloor = pe.Constraint(m.T1, rule=lambda m, t: m.soc[t] + m.socslack[t] >= m.socfloor[t])
        m.c_tank0 = pe.Constraint(expr=m.tank[0] == m.tank0)
        m.c_tank = pe.Constraint(m.T, rule=lambda m, t:
                                 m.tank[t + 1] == m.tank[t] * (1 - tk.loss_per_h * dt[t]) + (m.tch[t] - m.tdis[t]) * dt[t])
        m.c_tankfloor = pe.Constraint(m.T1, rule=lambda m, t: m.tank[t] + m.tankslack[t] >= m.tankfloor[t])

        # spinning reserve: online headroom + battery headroom (power and 30 min of energy)
        m.c_resb1 = pe.Constraint(m.T, rule=lambda m, t: m.resbatt[t] <= b.power_kw - m.dis[t])
        m.c_resb2 = pe.Constraint(m.T, rule=lambda m, t:
                                  m.resbatt[t] <= (m.soc[t] - b.soc_emergency * b.capacity_kwh) * b.eta_discharge / 0.5)
        m.c_reserve = pe.Constraint(m.T, rule=lambda m, t: rated * m.n[t] - m.p[t] + m.resbatt[t] >= m.reserve[t])

        # deferrable energy per local-day window inside the horizon
        m.c_wmin = pe.Constraint(m.D, rule=lambda m, d: sum(m.inday[d, t] * m.water[t] * dt[t] for t in m.T) >= m.wreq[d])
        m.c_wmax = pe.Constraint(m.D, rule=lambda m, d: sum(m.inday[d, t] * m.water[t] * dt[t] for t in m.T) <= m.wcap[d])
        m.c_lmin = pe.Constraint(m.D, rule=lambda m, d: sum(m.inday[d, t] * m.laundry[t] * dt[t] for t in m.T) >= m.lreq[d])
        m.c_lmax = pe.Constraint(m.D, rule=lambda m, d: sum(m.inday[d, t] * m.laundry[t] * dt[t] for t in m.T) <= m.lcap[d])

        # terminal value: energy drawn from storage below its starting level must be paid back later
        val_el = 0.30   # L per kWh of battery energy (marginal diesel)
        val_th = 1 / (st.boiler_eff * st.diesel_kwh_per_l)
        m.c_end = pe.Constraint(expr=m.endshort >= m.soc0 - m.soc[T])
        m.c_tend = pe.Constraint(expr=m.tankshort >= m.tank0 - m.tank[T])

        boiler_l = 1 / (st.boiler_eff * st.diesel_kwh_per_l)
        wear = b.wear_l_per_kwh
        m.obj = pe.Objective(expr=
            sum(((fa * m.n[t] + fb * m.p[t]) + boiler_l * m.boiler[t]) * dt[t] for t in m.T)
            + st.genset_start_cost_l * sum(m.s[t] for t in m.T)
            + sum(wear * (m.ch[t] + m.dis[t]) * dt[t] for t in m.T)
            + sum(SHED_WEIGHT[k] * m.shed[k, t] * dt[t] for k in m.K for t in m.T)
            + sum((TIER1_WEIGHT * m.t1unserved[t] + HEAT_UNSERVED_WEIGHT * m.hunserved[t]) * dt[t] for t in m.T)
            + sum((0.001 * m.curt[t] + 1e-4 * m.dump[t]) * dt[t] for t in m.T)
            + SOC_SLACK_WEIGHT * sum(m.socslack[t] + 0.2 * m.tankslack[t] for t in m.T1)
            + val_el * m.endshort + val_th * m.tankshort,
            sense=pe.minimize)
        self.m = m
        self.rated, self.fa, self.fb, self.hr = rated, fa, fb, hr

    # ---------- solve ----------
    def set_inputs(self, x: PlanInputs):
        m, T = self.m, self.T
        for t in range(T):
            m.el[t] = float(x.load[t]); m.el90[t] = float(x.load_p90[t]); m.heat[t] = float(x.heat[t])
            m.pv[t] = float(x.pv[t]); m.wind[t] = float(x.wind[t]); m.ren10[t] = float(x.ren_p10[t])
            m.minunits[t] = float(x.min_units[t]); m.reserve[t] = float(x.reserve[t]); m.turb[t] = float(x.turbines_on[t])
            m.navail[t] = float(x.gen_avail[:, t].sum())
            for k in SHED_TIERS:
                m.tier[k, t] = float(x.tiers[k][t])
            for d in range(MAX_DAYS):
                m.inday[d, t] = 1.0 if x.day_of_step[t] == d else 0.0
        for t in range(T + 1):
            m.socfloor[t] = float(x.soc_floor[t]); m.tankfloor[t] = float(x.tank_floor[t])
        for d in range(MAX_DAYS):
            m.wreq[d] = float(x.water_req[d]); m.wcap[d] = float(x.water_cap[d])
            m.lreq[d] = float(x.laundry_req[d]); m.lcap[d] = float(x.laundry_cap[d])
        b = self.st.battery
        m.soc0 = float(np.clip(x.soc0_kwh, b.soc_emergency * b.capacity_kwh, b.soc_max * b.capacity_kwh))
        m.tank0 = float(np.clip(x.tank0_kwh, 0, self.st.tank.capacity_kwh))
        m.n0 = float(np.sum(x.gen_on0))

    def solve(self, x: PlanInputs) -> Plan:
        self.set_inputs(x)
        t0 = time.perf_counter()
        try:
            res = self.solver.solve(self.m)
            status = str(res.termination_condition).split(".")[-1]
            has_sol = res.best_feasible_objective is not None
            if has_sol:
                res.solution_loader.load_vars()
        except Exception as e:  # solver crash -> caller falls back (FR-16)
            return self._failed(f"error: {e}", time.perf_counter() - t0, x)
        secs = time.perf_counter() - t0
        if not has_sol:
            return self._failed(status, secs, x)
        return self._extract(status, secs, float(res.best_feasible_objective), x)

    def _failed(self, status, secs, x) -> Plan:
        z = np.zeros(self.T)
        G = len(self.st.gensets)
        return Plan(False, status, secs, np.nan, self.dt, np.zeros((G, self.T)), np.zeros((G, self.T)), z,
                    z, z, np.zeros(self.T + 1), np.zeros(self.T + 1), z, z, z, z, z, z, z, z, {}, z, z, x)

    def _extract(self, status, secs, obj, x) -> Plan:
        m, T = self.m, self.T
        G = len(self.st.gensets)
        v = lambda var: np.array([pe.value(var[t]) for t in range(T)], dtype=float)
        n = np.round(v(m.n)).astype(int)
        ptot = v(m.p) * (n > 0)
        u = split_units(n, x.gen_on0.astype(bool), x.gen_avail > 0.5)
        p = u * np.where(n > 0, ptot / np.maximum(n, 1), 0.0)[None, :]
        boiler = v(m.boiler)
        fuel = ((self.fa * n + self.fb * ptot) + boiler / (self.st.boiler_eff * self.st.diesel_kwh_per_l)) * self.dt
        return Plan(
            ok=True, status=status, solve_s=secs, objective=obj, step_h=self.dt, u=u, p=p, starts=v(m.s),
            ch=v(m.ch), dis=v(m.dis),
            soc=np.array([pe.value(m.soc[t]) for t in range(T + 1)]),
            tank=np.array([pe.value(m.tank[t]) for t in range(T + 1)]),
            tank_ch=v(m.tch), tank_dis=v(m.tdis), p2h=v(m.p2h), boiler=boiler, dump=v(m.dump), curt=v(m.curt),
            water=v(m.water), laundry=v(m.laundry),
            shed={k: np.array([pe.value(m.shed[k, t]) for t in range(T)]) for k in SHED_TIERS},
            fuel_l=fuel, heat_rec=self.hr * (self.fa * n + self.fb * ptot), inputs=x)


def split_units(n: np.ndarray, on0: np.ndarray, avail: np.ndarray) -> np.ndarray:
    """Turn 'n units online' into a unit schedule: keep running units running, start in rotation order."""
    G, T = avail.shape
    u = np.zeros((G, T))
    prev = on0.copy()
    for t in range(T):
        keep = [g for g in range(G) if prev[g] and avail[g, t]][: n[t]]
        add = [g for g in range(G) if avail[g, t] and g not in keep][: max(0, n[t] - len(keep))]
        for g in keep + add:
            u[g, t] = 1
        prev = u[:, t] > 0.5
    return u
