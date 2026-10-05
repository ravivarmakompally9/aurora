"""Safety guardrail (FR-14, FR-15, PRD §11): the AI proposes, the guardrail disposes.

Every setpoint is checked against hard limits before it reaches the station. Violations are
corrected (never silently): the corrected setpoint and a list of what changed are returned.
"""
from __future__ import annotations

import numpy as np

from aurora.config import Station
from aurora.twin.simulator import Setpoint

TIER_INFO = {
    "el_tier1_kw": ("Tier 1", "Life support: ventilation, galley, medical, fire safety, water production", "Never shed"),
    "el_tier2_kw": ("Tier 2", "Communications and safety: satellite comms, emergency lighting, control systems",
                    "Shed only if Tier 1 is at risk"),
    "el_tier3_kw": ("Tier 3", "Science: instruments, labs, data servers", "Shed or rescheduled in deficit"),
    "el_tier4_kw": ("Tier 4", "Comfort: laundry, recreation, non-essential lighting", "Shed first"),
}


class Guardrail:
    def __init__(self, st: Station):
        self.st = st
        el = st.loads["electric"]
        # largest load that can switch on unexpectedly (the water plant is scheduled, so it is not a surprise step)
        self.largest_step = float(max(el["tier3_science"]["experiment_kw"]))
        self.degraded = False  # set by the data hub when a critical sensor is bad: widen the reserve (PRD §11.3)

    def validate(self, twin, t: int, sp: Setpoint) -> tuple[Setpoint, list[dict]]:
        st, s = self.st, twin.state
        b = st.battery
        out: list[dict] = []
        gens = st.gensets
        rated = np.array([g.rated_kw for g in gens])
        pmin = np.array([g.min_load * g.rated_kw for g in gens])
        avail = twin.gen_available(t)
        on = np.array(sp.gen_on, bool)
        kw = np.array(sp.gen_kw, float)

        # equipment ratings
        bad = on & ~avail
        if bad.any():
            on &= avail
            out.append(self._v("equipment_unavailable", "warning",
                               f"{', '.join(gens[i].id for i in np.flatnonzero(bad))} unavailable; removed from dispatch"))
        # minimum run time (equipment protection): a unit started less than min-up ago keeps running,
        # whoever started it (plan, guardrail or the PLC's emergency auto-start)
        up_steps = int(round(st.genset_min_up_h / st.dt_h))
        if up_steps and s.gen_on_since is not None:
            young = s.gen_on & avail & (t - s.gen_on_since < up_steps) & ~on
            if young.any():
                on |= young
                kw = np.where(young, pmin, kw)
        kw = np.where(on, np.clip(kw, pmin, rated), 0.0)

        # tier 1 is never shed; tier 2 only by the PLC in a real deficit, never by plan
        for c in ("el_tier1_kw", "el_tier2_kw"):
            if sp.shed_kw.get(c, 0.0) > 1e-6:
                out.append(self._v("tier_protection", "warning", f"Planned shedding of {TIER_INFO[c][0]} blocked"))
                sp.shed_kw[c] = 0.0

        # turbines must not run above cut-out
        if sp.turbines_on and twin.hub_wind[t] >= st.wind.cut_out_ms - 1.0:
            sp.turbines_on = False
            out.append(self._v("turbine_cut_out", "info", f"Hub wind {twin.hub_wind[t]:.0f} m/s: turbines parked"))

        # battery emergency floor
        e_floor = b.soc_emergency * b.capacity_kwh
        if sp.batt_kw < 0:
            max_dis = max(0.0, (s.soc_kwh - e_floor) * b.eta_discharge / st.dt_h)
            if -sp.batt_kw > max_dis + 1e-6:
                sp.batt_kw = -max_dis
                out.append(self._v("battery_floor", "warning", "Discharge limited to keep the emergency battery reserve"))

        # spinning reserve: online headroom + battery headroom must cover the largest load step
        load_now = twin.el_fixed[t] + sp.water_kw + sp.laundry_kw + sp.p2h_kw
        ren_now = twin.pv_avail[t] + (twin.wind_avail[t] if sp.turbines_on else 0.0)
        batt_cap = min(b.power_kw, max(0.0, (s.soc_kwh - e_floor) * b.eta_discharge / 0.5))  # 30 min at full power
        expected_dis = max(0.0, load_now - ren_now - kw.sum())  # what the battery will actually supply
        batt_head = max(0.0, batt_cap - expected_dis)
        step_req = self.largest_step * (1.3 if self.degraded else 1.0)
        started = []
        while ((rated * on).sum() - kw.sum() + batt_head < step_req
               or (rated * on).sum() + batt_cap + 0.5 * ren_now < 1.1 * load_now):
            idle = np.flatnonzero(avail & ~on)
            if not len(idle):
                out.append(self._v("reserve_shortfall", "critical", "Spinning reserve below requirement and no generator available"))
                break
            g = idle[0]
            on[g] = True
            kw[g] = pmin[g]
            started.append(gens[g].id)
        if started:
            out.append(self._v("spinning_reserve", "warning", f"Started {', '.join(started)} to restore spinning reserve"))
        if not on.any() and not avail.any():
            out.append(self._v("no_generator", "critical", "No generator available: running on battery and renewables"))

        # fuel safety reserve
        if s.fuel_l < st.fuel.safety_reserve_kl * 1000:
            out.append(self._v("fuel_reserve", "critical", "Fuel level below the safety reserve"))

        sp.gen_on, sp.gen_kw = on.tolist(), kw.tolist()
        return sp, out

    @staticmethod
    def _v(rule: str, severity: str, detail: str) -> dict:
        return {"rule": rule, "severity": severity, "detail": detail}
