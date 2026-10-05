"""Diesel-first baseline: how polar stations are typically run today (FR-29).

Rules: the lead generator is always on, extra units start to keep a 20 % spinning reserve,
renewables are used first, the battery is a buffer that keeps generators at minimum load,
waste heat is used only when it coincides with demand (no thermal storage), surplus wind
and solar are curtailed, and water production and laundry run at fixed times.
"""
from __future__ import annotations

import math

import numpy as np

from aurora.twin.simulator import Setpoint, Twin

WATER_START_H = 9
LAUNDRY_START_H = 10


def fixed_schedule(twin: Twin, t: int, idx: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Water and laundry power at steps `idx` (from t onward) under the fixed daily schedule used today."""
    left = twin.deferrable_left(t)
    w_left, l_left = left["water"], left["laundry"]
    wmax, lmax = twin.defer_max["water"], twin.defer_max["laundry"]
    dt = twin.st.dt_h
    water, laundry = np.zeros(len(idx)), np.zeros(len(idx))
    day = twin.day_id[t]
    for i, k in enumerate(idx):
        if twin.day_id[k] != day:
            day = twin.day_id[k]
            w_left, l_left = twin.water_day[k], twin.laundry_day[k]
        lh = twin.local_hour[k]
        if lh >= WATER_START_H and w_left > 0:
            water[i] = min(wmax, w_left / dt); w_left -= water[i] * dt
        if lh >= LAUNDRY_START_H and l_left > 0:
            laundry[i] = min(lmax, l_left / dt); l_left -= laundry[i] * dt
    return water, laundry


class DieselFirst:
    name = "diesel_first"

    def decide(self, twin: Twin, t: int) -> Setpoint:
        st, s = twin.st, twin.state
        b, dt = st.battery, st.dt_h
        lh = twin.local_hour[t]
        left = twin.deferrable_left(t)
        water = twin.defer_max["water"] if lh >= WATER_START_H and left["water"] > 0 else 0.0
        laundry = twin.defer_max["laundry"] if lh >= LAUNDRY_START_H and left["laundry"] > 0 else 0.0

        net = twin.el_fixed[t] + water + laundry - twin.pv_avail[t] - twin.wind_avail[t]
        avail = np.flatnonzero(twin.gen_available(t))
        gens = st.gensets
        lead = gens[avail[0]] if len(avail) else gens[0]
        r, pmin = lead.rated_kw, lead.min_load * lead.rated_kw

        e_min = b.soc_min * b.capacity_kwh
        dis_max = min(b.power_kw, max(0.0, (s.soc_kwh - e_min) * b.eta_discharge / dt))
        supply = min(dis_max, max(0.0, net - pmin))
        g_need = net - supply
        n = max(1, math.ceil(1.2 * max(0.0, g_need) / r))
        n = min(n, max(1, len(avail)))
        per_unit = min(r, max(g_need / n, pmin))
        excess = n * per_unit - g_need

        on = [False] * len(gens)
        kw = [0.0] * len(gens)
        for g in avail[:n]:
            on[g] = True
            kw[g] = per_unit
        batt = -supply if supply > 0 else excess
        return Setpoint(gen_on=on, gen_kw=kw, batt_kw=batt, p2h_kw=0.0, water_kw=water, laundry_kw=laundry,
                        turbines_on=True, use_tank=False, mode="normal", source="baseline")
