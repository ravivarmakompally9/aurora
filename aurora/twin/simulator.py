"""Digital twin of a polar station microgrid (FR-28).

Each 15-minute step a controller returns a Setpoint. The twin then applies physics and
the station PLC's fast primary response: the battery absorbs mismatch first, online
generators flex within their limits, a standby generator auto-starts on a deficit,
renewables are curtailed on a surplus, and loads are shed tier 4 -> 1 only as a last resort.
Heat is balanced by recovered waste heat, power-to-heat, the thermal tank and the oil boiler.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from aurora.config import Station
from aurora.twin.assets import pv_power, wind_power, hub_wind
from aurora.twin.loads import build_demand, deferrable_limits
from aurora.twin.weather import inject_blizzard, load_weather

TIERS = ("el_tier4_kw", "el_tier3_kw", "el_tier2_kw", "el_tier1_kw")  # shedding order


@dataclass
class Setpoint:
    gen_on: list[bool]
    gen_kw: list[float]
    batt_kw: float = 0.0          # + charge, - discharge
    p2h_kw: float = 0.0
    boiler_kw: float = 0.0        # planned boiler output (e.g. pre-heating the tank before a storm)
    water_kw: float = 0.0
    laundry_kw: float = 0.0
    shed_kw: dict = field(default_factory=dict)  # planned shedding per tier column
    turbines_on: bool = True
    use_tank: bool = True
    mode: str = "normal"          # normal | storm | fallback
    source: str = "controller"


@dataclass
class TwinState:
    soc_kwh: float
    tank_kwh: float
    fuel_l: float
    gen_on: np.ndarray
    water_done: float = 0.0
    laundry_done: float = 0.0
    day: int = -1


class Twin:
    def __init__(self, st: Station, wx: pd.DataFrame | None = None, demand: pd.DataFrame | None = None,
                 start: str | pd.Timestamp | None = None, end: str | pd.Timestamp | None = None, seed: int = 0):
        self.st = st
        wx = load_weather(st) if wx is None else wx
        demand = build_demand(st, wx, seed) if demand is None else demand
        if start is not None or end is not None:
            sl = slice(pd.Timestamp(start, tz="UTC") if start else None, pd.Timestamp(end, tz="UTC") if end else None)
            wx, demand = wx.loc[sl], demand.loc[sl]
        self.wx, self.demand = wx, demand
        self.events: list[dict] = []
        self.gen_trip_until = np.full(len(st.gensets), -1)
        self._prepare()
        self.reset()

    # ---------- data ----------
    def _prepare(self):
        st, wx, d = self.st, self.wx, self.demand
        self.n = len(wx)
        self.index = wx.index
        self.pv_avail = pv_power(st, wx)
        self.wind_avail = wind_power(st, wx)
        self.hub_wind = hub_wind(st, wx)
        self.temp = wx["temp_c"].to_numpy()
        self.wind10 = wx["wind10_ms"].to_numpy()
        self.local_hour = wx["local_hour"].to_numpy()
        ld = wx["local_date"].to_numpy()
        self.day_id = np.cumsum(np.r_[0, ld[1:] != ld[:-1]])
        # steps remaining in the local day including the current one
        last = np.r_[np.flatnonzero(np.diff(self.day_id)), self.n - 1]
        self.steps_left = (last[self.day_id] - np.arange(self.n) + 1)
        self.el = {c: d[c].to_numpy() for c in TIERS}
        self.el_fixed = d["el_fixed_kw"].to_numpy()
        self.heat = d["heat_kw"].to_numpy()
        self.heat_t1 = d["heat_tier1_kw"].to_numpy()
        self.water_day = d["water_kwh_day"].to_numpy()
        self.laundry_day = d["laundry_kwh_day"].to_numpy()
        self.crew = d["crew"].to_numpy()
        self.defer_max = deferrable_limits(self.st)

    def reset(self, soc: float = 0.6, tank: float = 0.5, fuel_l: float | None = None):
        st = self.st
        self.state = TwinState(
            soc_kwh=soc * st.battery.capacity_kwh, tank_kwh=tank * st.tank.capacity_kwh,
            fuel_l=(st.fuel.on_hand_kl * 1000 if fuel_l is None else fuel_l),
            gen_on=np.zeros(len(st.gensets), bool))
        self.gen_trip_until[:] = -1
        self.leaks: list[tuple[int, int, float]] = []
        self.log: list[dict] = []

    # ---------- events (FR-30) ----------
    def inject(self, kind: str, t: int, hours: float = 30, **kw) -> dict:
        ev = {"type": kind, "t": t, "time": self.index[min(t, self.n - 1)], "hours": hours, **kw}
        if kind == "blizzard":
            self.wx = inject_blizzard(self.st, self.wx, self.index[t], hours, kw.get("peak_ms", 32.0))
            self.demand = self.demand.copy()
            self._refresh_weather_dependent()
        elif kind == "wind_surplus":
            # strong steady wind below cut-out (scenario E): surplus that should become heat, not curtailment
            n = int(hours / self.st.dt_h)
            wx = self.wx.copy()
            sl = slice(t, min(t + n, self.n))
            col = wx.columns.get_loc
            wx.iloc[sl, col("wind10_ms")] = np.maximum(wx["wind10_ms"].to_numpy()[sl], kw.get("speed_ms", 14.0))
            wx.iloc[sl, col("wind50_ms")] = wx["wind10_ms"].to_numpy()[sl] * 1.2
            from aurora.twin.weather import add_derived
            self.wx = add_derived(self.st, wx.drop(columns=["storm", "panel_clear", "local_hour", "local_date"]))
            self.demand = self.demand.copy()
            self._refresh_weather_dependent()
        elif kind == "generator_failure":
            g = kw.get("gen", 1)
            self.gen_trip_until[g] = t + int(hours / self.st.dt_h)
        elif kind == "fuel_leak":
            self.leaks.append((t, t + int(hours / self.st.dt_h), kw.get("litres", 3000.0)))
        elif kind in ("sensor_loss", "resupply_delay"):
            pass  # handled by the data hub and fuel planner
        else:
            raise ValueError(kind)
        self.events.append(ev)
        return ev

    def _refresh_weather_dependent(self):
        """Recompute renewables and heat demand after a weather event, keeping crew and noise."""
        st, wx = self.st, self.wx
        h = st.loads["heat"]
        occ = 0.8 + 0.2 * self.crew / st.loads["crew"]["summer"]

        def space(temp, wind):
            return h["ua_kw_per_k"] * np.maximum(0, h["indoor_c"] - temp) * (1 + h["wind_infiltration"] * wind) * occ

        new_temp, new_wind = wx["temp_c"].to_numpy(), wx["wind10_ms"].to_numpy()
        self.heat = np.maximum(0, self.heat + space(new_temp, new_wind) - space(self.temp, self.wind10))
        self.heat_t1 = self.heat * h["min_share_tier1"]
        self.temp, self.wind10 = new_temp, new_wind
        self.pv_avail = pv_power(st, wx)
        self.wind_avail = wind_power(st, wx)
        self.hub_wind = hub_wind(st, wx)
        self.demand["heat_kw"] = self.heat
        self.demand["heat_tier1_kw"] = self.heat_t1

    def gen_available(self, t: int) -> np.ndarray:
        return self.gen_trip_until < t

    # ---------- physics ----------
    def step(self, t: int, sp: Setpoint) -> dict:
        st, s = self.st, self.state
        dt = st.dt_h
        b, tk = st.battery, st.tank
        gens = st.gensets
        if self.day_id[t] != s.day:
            s.day, s.water_done, s.laundry_done = self.day_id[t], 0.0, 0.0

        # deferrable loads: controller choice, but the twin enforces completion by day end
        water = self._deferrable(t, sp.water_kw, "water")
        laundry = self._deferrable(t, sp.laundry_kw, "laundry")

        # renewables
        pv = self.pv_avail[t]
        wind = self.wind_avail[t] if sp.turbines_on else 0.0

        # electrical loads after planned shedding (tier 1 is never shed by plan)
        el = {c: self.el[c][t] for c in TIERS}
        shed = {c: min(el[c], sp.shed_kw.get(c, 0.0)) for c in TIERS if c != "el_tier1_kw"}
        el_load = sum(el.values()) - sum(shed.values()) + water + laundry
        p2h = max(0.0, min(sp.p2h_kw, st.p2h_max_kw))

        # generators: requested setpoints on available units
        avail = self.gen_available(t)
        on = np.array(sp.gen_on, bool) & avail
        rated = np.array([g.rated_kw for g in gens])
        pmin = np.array([g.min_load * g.rated_kw for g in gens])
        p_gen = np.where(on, np.clip(sp.gen_kw, pmin, rated), 0.0)

        # battery limits this step
        e_min_phys = b.soc_emergency * b.capacity_kwh
        e_max = b.soc_max * b.capacity_kwh
        cold = 1.0 if self.temp[t] > -40 else 0.8  # heated enclosure; derate only in extreme cold
        ch_max = min(b.power_kw * cold, max(0.0, (e_max - s.soc_kwh) / (b.eta_charge * dt)))
        dis_max = min(b.power_kw * cold, max(0.0, (s.soc_kwh - e_min_phys) * b.eta_discharge / dt))
        batt = float(np.clip(sp.batt_kw, -dis_max, ch_max))  # + charge

        # primary response to close the electrical balance
        imb = p_gen.sum() + pv + wind - el_load - p2h - batt  # >0 surplus, <0 deficit
        curtail = 0.0
        unserved = {c: 0.0 for c in TIERS}
        starts = 0
        if imb > 1e-9:
            take = min(imb, ch_max - batt); batt += take; imb -= take
            if imb > 1e-9 and on.any():
                room = np.where(on, p_gen - pmin, 0.0)
                cut = min(imb, room.sum())
                if cut > 0:
                    p_gen -= room * (cut / room.sum()); imb -= cut
            if imb > 1e-9:
                curtail = min(imb, pv + wind); imb -= curtail
            if imb > 1e-9:  # gens at min with nothing to absorb: divert to heat
                p2h += min(imb, st.p2h_max_kw - p2h); imb = 0.0
        elif imb < -1e-9:
            need = -imb
            give = min(need, dis_max + batt); batt -= give; need -= give
            if need > 1e-9 and on.any():
                room = np.where(on, rated - p_gen, 0.0)
                add = min(need, room.sum())
                if add > 0:
                    p_gen += room * (add / room.sum()); need -= add
            while need > 1e-9:  # PLC auto-starts a standby unit
                idle = np.flatnonzero(avail & ~on)
                if not len(idle):
                    break
                g = idle[0]
                on[g] = True
                p_gen[g] = min(rated[g], max(pmin[g], need))
                need -= p_gen[g]
            if need < 0:  # new unit's minimum load overshoots: store it, else curtail
                extra = -need
                take = min(extra, ch_max - batt); batt += take; extra -= take
                curtail = min(extra, pv + wind); extra -= curtail
                p2h += extra
                need = 0.0
            if need > 1e-9:  # shed tier 4 -> 1
                p2h_cut = min(need, p2h); p2h -= p2h_cut; need -= p2h_cut
                for c in TIERS:
                    if need <= 1e-9:
                        break
                    remaining = el[c] - shed.get(c, 0.0)
                    x = min(need, remaining); unserved[c] = x; need -= x

        # generator fuel and recovered heat
        fuel_gen_lph = np.where(on, np.array([g.a * g.rated_kw for g in gens]) + np.array([g.b for g in gens]) * p_gen, 0.0)
        heat_rec = float(np.sum(fuel_gen_lph * np.array([g.heat_recovery for g in gens]) * st.diesel_kwh_per_l))
        starts += int(np.sum(on & ~s.gen_on))

        # battery state
        if batt >= 0:
            s.soc_kwh += batt * b.eta_charge * dt
        else:
            s.soc_kwh += batt / b.eta_discharge * dt
        s.soc_kwh = float(np.clip(s.soc_kwh, 0.0, b.capacity_kwh))

        # heat balance
        hd = self.heat[t]
        free = heat_rec + p2h * st.p2h_eff
        tank_ch = tank_dis = dump = 0.0
        s.tank_kwh *= (1 - tk.loss_per_h * dt)
        tmin = tk.soc_min * tk.capacity_kwh
        room = min(tk.max_charge_kw, max(0.0, (tk.capacity_kwh - s.tank_kwh) / dt)) if sp.use_tank else 0.0
        # planned boiler heat is only burned where it is useful: meeting demand or charging the tank
        boiler = float(np.clip(sp.boiler_kw, 0.0, min(st.boiler_max_kw, max(0.0, hd + room - free))))
        heat_unserved = 0.0
        if free + boiler >= hd:
            surplus = free + boiler - hd
            tank_ch = min(surplus, room)
            dump = surplus - tank_ch
        else:
            gap = hd - free - boiler
            if sp.use_tank:
                tank_dis = min(gap, tk.max_discharge_kw, max(0.0, (s.tank_kwh - tmin) / dt))
            gap -= tank_dis
            extra = min(gap, st.boiler_max_kw - boiler)
            boiler += extra
            heat_unserved = gap - extra
        s.tank_kwh += (tank_ch - tank_dis) * dt
        fuel_boiler_lph = boiler / (st.boiler_eff * st.diesel_kwh_per_l)

        # fuel tank
        fuel_l = (fuel_gen_lph.sum() + fuel_boiler_lph) * dt
        leak = sum(v / max(1, b_ - a_) for a_, b_, v in self.leaks if a_ <= t < b_)
        other = st.fuel.other_use_l_per_day * dt / 24
        s.fuel_l -= fuel_l + leak + other
        s.gen_on = on.copy()

        loading = np.where(on, p_gen / rated, np.nan)
        rec = {
            "t": t, "pv_kw": pv, "wind_kw": wind, "pv_avail_kw": self.pv_avail[t], "wind_avail_kw": self.wind_avail[t],
            "curtail_kw": curtail, "gen_kw": float(p_gen.sum()), "gens_on": int(on.sum()), "starts": starts,
            "gen_low_load": int(np.sum(on & (p_gen < 0.4 * rated))),
            "batt_kw": batt, "soc": s.soc_kwh / b.capacity_kwh if b.capacity_kwh else 0.0,
            "el_load_kw": el_load, "el_demand_kw": sum(el.values()) + water + laundry,
            "water_kw": water, "laundry_kw": laundry, "p2h_kw": p2h,
            "shed_planned_kw": sum(shed.values()),
            **{f"unserved_{c[3:8]}": unserved[c] for c in TIERS},
            "heat_kw": hd, "heat_rec_kw": heat_rec, "p2h_heat_kw": p2h * st.p2h_eff, "tank_ch_kw": tank_ch,
            "tank_dis_kw": tank_dis, "boiler_kw": boiler, "heat_dump_kw": dump, "heat_unserved_kw": heat_unserved,
            "tank_soc": s.tank_kwh / tk.capacity_kwh if tk.capacity_kwh else 0.0,
            "fuel_gen_l": float(fuel_gen_lph.sum() * dt), "fuel_boiler_l": fuel_boiler_lph * dt,
            "fuel_l": fuel_l, "fuel_level_l": s.fuel_l, "leak_l": leak,
            "mean_loading": float(np.nanmean(loading)) if on.any() else np.nan,
            "mode": sp.mode, "source": sp.source, "turbines_on": sp.turbines_on,
            **{f"g{i + 1}_kw": float(p_gen[i]) for i in range(len(gens))},
        }
        self.log.append(rec)
        return rec

    def _deferrable(self, t: int, req: float, kind: str) -> float:
        s, dt = self.state, self.st.dt_h
        day_kwh = (self.water_day if kind == "water" else self.laundry_day)[t]
        done = s.water_done if kind == "water" else s.laundry_done
        left = max(0.0, day_kwh - done)
        pmax = self.defer_max[kind]
        must = left - (self.steps_left[t] - 1) * pmax * dt  # energy that cannot wait any longer
        p = min(max(req, must / dt, 0.0), pmax, left / dt)
        if kind == "water":
            s.water_done += p * dt
        else:
            s.laundry_done += p * dt
        return p

    def run(self, controller, t0: int = 0, t1: int | None = None, progress=None) -> pd.DataFrame:
        t1 = self.n if t1 is None else t1
        for t in range(t0, t1):
            sp = controller.decide(self, t)
            self.step(t, sp)
            if progress and t % 960 == 0:
                progress(t, t1)
        return self.frame()

    def frame(self) -> pd.DataFrame:
        df = pd.DataFrame(self.log)
        if len(df):
            df.index = self.index[df["t"].to_numpy()]
        return df

    # ---------- observation helpers for controllers ----------
    def deferrable_left(self, t: int) -> dict[str, float]:
        s = self.state
        day_changed = self.day_id[t] != s.day
        w_done = 0.0 if day_changed else s.water_done
        l_done = 0.0 if day_changed else s.laundry_done
        return {"water": max(0.0, self.water_day[t] - w_done), "laundry": max(0.0, self.laundry_day[t] - l_done)}
