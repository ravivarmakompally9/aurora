"""Fuel Survival Score (FR-19..FR-21, PRD §8.3).

"Will our fuel last until the ship arrives?" answered as a probability:
1. Sample N scenarios: each future day takes a historical weather day (block bootstrap of
   5-day blocks, same season +/-15 days, any of the three weather years), plus a random
   resupply delay on top of the planned date.
2. Run a fast daily dispatch surrogate for each scenario. The surrogate is a linear model of
   daily diesel use learned from the digital twin's full-year run of each strategy
   (electric demand, heat demand, renewables available), with bootstrapped residuals.
3. Score = share of scenarios whose fuel stays above the safety reserve until arrival.
Conservation actions are re-scored the same way and ranked by litres saved.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from functools import lru_cache

import numpy as np
import pandas as pd

from aurora.config import DATA_DIR, Station, load_station
from aurora.twin.loads import is_summer

BLOCK_DAYS = 5
SEASON_WINDOW = 15
DELAY_P_ZERO = 0.6          # chance the ship arrives on the planned date
DELAY_MEAN_DAYS = 7.0       # otherwise exponential delay (sea ice, weather), capped
DELAY_CAP_DAYS = 30


@dataclass
class DailyClimate:
    doy: np.ndarray          # (n_hist,)
    year: np.ndarray
    space_kwh: np.ndarray    # space-heat demand per unit occupancy factor
    wind_ms: np.ndarray
    ren_kwh: np.ndarray      # renewable energy available


@lru_cache(maxsize=8)
def climate(key: str) -> DailyClimate:
    from aurora.twin.simulator import Twin
    st = load_station(key)
    tw = Twin(st)
    h = st.loads["heat"]
    dt = st.dt_h
    day = tw.wx["local_date"]
    space = h["ua_kw_per_k"] * np.maximum(0, h["indoor_c"] - tw.temp) * (1 + h["wind_infiltration"] * tw.wind10)
    df = pd.DataFrame({"space": space * dt, "ren": (tw.pv_avail + tw.wind_avail) * dt, "wind": tw.wind10}, index=tw.index)
    g = df.groupby(day.to_numpy())
    agg = pd.DataFrame({"space": g.space.sum(), "ren": g.ren.sum(), "wind": g.wind.mean(), "n": g.size()})
    agg = agg[agg.n == st.steps_per_day]
    idx = pd.DatetimeIndex(agg.index)
    return DailyClimate(doy=idx.dayofyear.to_numpy(), year=idx.year.to_numpy(), space_kwh=agg.space.to_numpy(),
                        wind_ms=agg.wind.to_numpy(), ren_kwh=agg.ren.to_numpy())


def daily_demand(st: Station, dates: pd.DatetimeIndex) -> dict[str, np.ndarray]:
    """Weather-independent daily demand by calendar date (crew calendar drives it)."""
    el = st.loads["electric"]
    t1, t2, t3, t4 = el["tier1_life_support"], el["tier2_comms_safety"], el["tier3_science"], el["tier4_comfort"]
    crew = np.where(is_summer(st, dates), st.loads["crew"]["summer"], st.loads["crew"]["winter"]).astype(float)
    active_h = 16 + 8 * 0.3
    tier1 = 24 * (t1["ventilation_kw"] + t1["ventilation_kw_per_person"] * crew + t1["medical_fire_kw"]) \
        + 3 * t1["galley_kw_per_person_meal"] * crew + t1["water_kwh_base"] + t1["water_kwh_per_person"] * crew
    tier2 = 24 * t2["constant_kw"] * np.ones_like(crew)
    exp_mean = t3["experiments_per_week"] / 7 * np.mean(t3["experiment_kw"]) * np.mean(t3["experiment_hours"])
    tier3 = 24 * t3["constant_kw"] + exp_mean * np.ones_like(crew)
    tier4 = t4["kw_per_person_active"] * crew * active_h + t4["laundry_kwh_per_person_week"] / 7 * crew
    hot_water = st.loads["heat"]["hot_water_kw_per_person"] * crew * 24 * (0.4 + 0.9 * (16 / 24) * 1.1)
    occ = 0.8 + 0.2 * crew / st.loads["crew"]["summer"]
    return {"crew": crew, "tier1": tier1, "tier2": tier2, "tier3": tier3, "tier4": tier4, "hot_water": hot_water, "occ": occ}


@dataclass
class Surrogate:
    """Daily litres = b0 + b_el * electric kWh + b_heat * heat kWh + b_ren * renewable kWh available."""
    coef: np.ndarray
    resid: np.ndarray
    strategy: str

    def predict(self, el, heat, ren) -> np.ndarray:
        c = self.coef
        return np.maximum(0.0, c[0] + c[1] * el + c[2] * heat + c[3] * ren)


@lru_cache(maxsize=8)
def surrogates(key: str, year: int | None = None) -> dict[str, Surrogate]:
    st = load_station(key)
    year = year or st.test_year
    path = DATA_DIR / "processed" / f"year_{key}_{year}_daily.csv"
    if not path.exists():
        raise FileNotFoundError(f"{path} missing: run `aurora year --station {key}` first")
    d = pd.read_csv(path, parse_dates=["date"]).set_index("date")
    cl = climate(key)
    dem = daily_demand(st, pd.DatetimeIndex(d.index))
    # daily heat and renewables from the same simulated year
    lookup = pd.DataFrame({"space": cl.space_kwh, "ren": cl.ren_kwh},
                          index=pd.to_datetime([f"{y}-01-01" for y in cl.year]) + pd.to_timedelta(cl.doy - 1, "D"))
    j = lookup.reindex(d.index)
    ok = j.notna().all(axis=1).to_numpy()
    el = sum(dem[k] for k in ("tier1", "tier2", "tier3", "tier4"))
    heat = j.space.to_numpy() * dem["occ"] + dem["hot_water"]
    X = np.c_[np.ones(len(d)), el, heat, j.ren.to_numpy()][ok]
    out = {}
    for strat, col in (("aurora", "aurora_fuel_l"), ("diesel_first", "base_fuel_l")):
        y = d[col].to_numpy()[ok]
        coef, *_ = np.linalg.lstsq(X, y, rcond=None)
        out[strat] = Surrogate(coef, y - X @ coef, strat)
    return out


@dataclass
class Action:
    key: str
    title: str
    detail: str
    el_scale: dict          # tier -> multiplier
    heat_setpoint_drop_c: float = 0.0
    other_scale: float = 1.0


ACTIONS = [
    Action("setpoint", "Lower habitable setpoint by 1 °C", "Indoor 20 → 19 °C in living modules; labs unchanged.", {}, 1.0),
    Action("science", "Defer 30% of Tier-3 science load", "Reschedule non-urgent instrument runs until after resupply.", {"tier3": 0.7}),
    Action("comfort", "Cut Tier-4 comfort load by 25%", "Laundry batching, recreation and non-essential lighting.", {"tier4": 0.75}),
    Action("vehicles", "Reduce vehicle and incinerator fuel by 20%", "Consolidate field trips and burns.", {}, 0.0, 0.8),
]


def _sample_days(cl: DailyClimate, start: date, n_days: int, n: int, rng) -> np.ndarray:
    """(n, n_days) indices into the historical climate table, 5-day blocks within the season window."""
    out = np.empty((n, n_days), dtype=int)
    by_year = {y: np.flatnonzero(cl.year == y) for y in np.unique(cl.year)}
    years = np.array(sorted(by_year))
    doys = (pd.Timestamp(start) + pd.to_timedelta(np.arange(n_days), "D")).dayofyear.to_numpy()
    for b0 in range(0, n_days, BLOCK_DAYS):
        L = min(BLOCK_DAYS, n_days - b0)
        ys = years[rng.integers(0, len(years), n)]
        off = rng.integers(-SEASON_WINDOW, SEASON_WINDOW + 1, n)
        for i, y in enumerate(ys):
            rows = by_year[y]
            target = doys[b0] + off[i]
            pos = int(np.clip(np.searchsorted(cl.doy[rows], target), 0, len(rows) - L))
            out[i, b0:b0 + L] = rows[pos:pos + L]
    return out


def survival(key: str, today: date, fuel_l: float, resupply: date, extra_delay_days: int = 0,
             strategy: str = "aurora", n: int = 1000, seed: int = 0, action: Action | None = None,
             _cache: dict | None = None) -> dict:
    st = load_station(key)
    sur = surrogates(key)[strategy]
    cl = climate(key)
    rng = np.random.default_rng(seed)
    planned = (resupply - today).days + extra_delay_days
    horizon = max(1, planned + DELAY_CAP_DAYS + 1)
    if _cache is not None and "days" in _cache:
        days = _cache["days"]
    else:
        days = _sample_days(cl, today, horizon, n, rng)
        if _cache is not None:
            _cache["days"] = days
    dates = pd.date_range(today, periods=horizon, freq="D")
    dem = daily_demand(st, dates)
    el_parts = {k: dem[k] * (action.el_scale.get(k, 1.0) if action else 1.0) for k in ("tier1", "tier2", "tier3", "tier4")}
    el = sum(el_parts.values())
    h = st.loads["heat"]
    space = cl.space_kwh[days]
    if action and action.heat_setpoint_drop_c:
        # degree-days removed: UA * drop * (1 + infiltration * wind) * 24 h
        space = np.maximum(0, space - h["ua_kw_per_k"] * action.heat_setpoint_drop_c * 24 * (1 + h["wind_infiltration"] * cl.wind_ms[days]))
    heat = space * dem["occ"] + dem["hot_water"]
    ren = cl.ren_kwh[days]
    rng2 = np.random.default_rng(seed + 1)
    noise = sur.resid[rng2.integers(0, len(sur.resid), days.shape)]
    other = st.fuel.other_use_l_per_day * np.where(is_summer(st, dates), 1.6, 1.0) * (action.other_scale if action else 1.0)
    burn = np.maximum(0, sur.predict(el[None, :], heat, ren) + noise) + other[None, :]
    level = fuel_l - np.cumsum(burn, axis=1)                       # end of each day
    rng3 = np.random.default_rng(seed + 2)
    delay = np.where(rng3.random(n) < DELAY_P_ZERO, 0, np.minimum(rng3.exponential(DELAY_MEAN_DAYS, n), DELAY_CAP_DAYS)).astype(int)
    arrive = np.clip(planned + delay, 0, horizon - 1)
    reserve = st.fuel.safety_reserve_kl * 1000
    at_arrival = level[np.arange(n), arrive]
    min_before = np.array([level[i, : arrive[i] + 1].min() for i in range(n)])
    score = float(np.mean(min_before >= reserve))
    fan_days = min(horizon, planned + 21)
    q = np.percentile(level[:, :fan_days], [10, 50, 90], axis=0)
    return {
        "strategy": strategy, "score": score, "n": n,
        "fuel_now_l": fuel_l, "reserve_l": reserve,
        "planned_arrival": (today + timedelta(days=planned)).isoformat(),
        "expected_at_arrival_l": float(np.median(at_arrival)),
        "p10_at_arrival_l": float(np.percentile(at_arrival, 10)),
        "burn_l_per_day": float(np.median(burn[:, : max(planned, 1)].mean(axis=1))),
        "days_of_fuel_above_reserve": float(np.median(np.argmax(level < reserve, axis=1) + (level[:, -1] >= reserve) * horizon)),
        "fan": {"dates": [d.date().isoformat() for d in dates[:fan_days]],
                "p10": q[0].round(0).tolist(), "p50": q[1].round(0).tolist(), "p90": q[2].round(0).tolist()},
        "delay_days_p90": float(np.percentile(delay, 90)) + extra_delay_days,
        "burn_to_arrival_p50_l": float(np.percentile(burn[:, : max(planned, 1)].sum(axis=1), 50)),
        "burn_to_arrival_p90_l": float(np.percentile(burn[:, : max(planned, 1)].sum(axis=1), 90)),
    }


def plan(key: str, today: date, fuel_l: float, resupply: date, extra_delay_days: int = 0,
         n: int = 1000, threshold: float = 0.95, seed: int = 0) -> dict:
    """Score both strategies, rank conservation actions (FR-20) and recommend the next order (FR-21)."""
    st = load_station(key)
    cache: dict = {}
    base = survival(key, today, fuel_l, resupply, extra_delay_days, "aurora", n, seed, _cache=cache)
    df = survival(key, today, fuel_l, resupply, extra_delay_days, "diesel_first", n, seed, _cache=cache)
    actions = []
    for a in ACTIONS:
        r = survival(key, today, fuel_l, resupply, extra_delay_days, "aurora", n, seed, action=a, _cache=cache)
        saved = r["expected_at_arrival_l"] - base["expected_at_arrival_l"]
        actions.append({"key": a.key, "title": a.title, "detail": a.detail, "litres_saved": round(saved, 0),
                        "score_after": round(r["score"], 3)})
    actions.sort(key=lambda x: -x["litres_saved"])
    level = "ok" if base["score"] >= threshold else ("warning" if base["score"] >= 0.9 else "critical")
    # next order: one year of AURORA burn at P90 plus reserve, minus what remains at arrival
    year_burn = surrogate_year_burn(key, n, seed)
    order = max(0.0, year_burn["p90"] + st.fuel.safety_reserve_kl * 1000 - base["expected_at_arrival_l"])
    order = min(order, st.fuel.tank_capacity_kl * 1000 - base["p10_at_arrival_l"])
    return {"station": key, "today": today.isoformat(), "threshold": threshold, "level": level,
            "aurora": base, "diesel_first": df, "actions": actions,
            "recommended_order_l": round(order, -2),
            "order_range_l": [round(year_burn["p50"] + st.fuel.safety_reserve_kl * 1000 - base["expected_at_arrival_l"], -2),
                              round(order, -2)]}


@lru_cache(maxsize=8)
def surrogate_year_burn(key: str, n: int = 500, seed: int = 0) -> dict:
    """Litres AURORA burns in the 12 months after a January resupply (P50 / P90 over weather scenarios)."""
    r = survival(key, date(2027, 1, 15), 1e9, date(2028, 1, 15), 0, "aurora", n, seed)
    return {"p50": r["burn_to_arrival_p50_l"], "p90": r["burn_to_arrival_p90_l"]}
