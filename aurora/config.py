"""Station configuration: YAML file -> typed dataclasses (NFR-10, NFR-11)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "configs"
DATA_DIR = ROOT / "data"


@dataclass(frozen=True)
class Genset:
    id: str
    rated_kw: float
    a: float               # L/h per kW rated when running (no-load term)
    b: float               # L per kWh produced (marginal term)
    min_load: float        # fraction of rated; below this the engine wet-stacks
    heat_recovery: float   # fraction of fuel energy recovered as useful heat

    def fuel_lph(self, p_kw: float, on: bool = True) -> float:
        return (self.a * self.rated_kw + self.b * p_kw) if on else 0.0


@dataclass(frozen=True)
class PV:
    kwp: float
    tilt_deg: float
    azimuth_deg: float
    albedo: float
    temp_coeff: float
    system_derate: float


@dataclass(frozen=True)
class Wind:
    turbines: int
    rated_kw: float
    hub_height_m: float
    cut_in_ms: float
    rated_ms: float
    cut_out_ms: float

    @property
    def total_kw(self) -> float:
        return self.turbines * self.rated_kw


@dataclass(frozen=True)
class Battery:
    capacity_kwh: float
    power_kw: float
    eta_charge: float
    eta_discharge: float
    soc_min: float
    soc_max: float
    soc_emergency: float
    enclosure_min_c: float
    wear_l_per_kwh: float


@dataclass(frozen=True)
class ThermalTank:
    capacity_kwh: float
    max_charge_kw: float
    max_discharge_kw: float
    loss_per_h: float
    soc_min: float


@dataclass(frozen=True)
class Fuel:
    tank_capacity_kl: float
    on_hand_kl: float
    safety_reserve_kl: float
    other_use_l_per_day: float
    resupply_date: date
    co2_kg_per_l: float


@dataclass(frozen=True)
class Control:
    step_min: int
    horizon_h: int
    storm_wind_ms: float
    storm_soc_target: float
    storm_tank_target: float
    reserve_frac_load: float


@dataclass(frozen=True)
class Station:
    key: str
    name: str
    location: str
    lat: float
    lon: float
    utc_offset_h: float
    gensets: tuple[Genset, ...]
    genset_start_cost_l: float
    genset_start_wear_l: float
    genset_min_up_h: float
    diesel_kwh_per_l: float
    pv: PV
    wind: Wind
    battery: Battery
    tank: ThermalTank
    p2h_max_kw: float
    p2h_eff: float
    boiler_max_kw: float
    boiler_eff: float
    loads: dict
    fuel: Fuel
    control: Control
    weather_years: tuple[int, ...]
    train_year: int
    val_year: int
    test_year: int
    raw: dict = field(repr=False, compare=False, default_factory=dict)

    @property
    def dt_h(self) -> float:
        return self.control.step_min / 60.0

    @property
    def steps_per_day(self) -> int:
        return int(24 * 60 / self.control.step_min)

    @property
    def is_south(self) -> bool:
        return self.lat < 0


def load_station(key_or_path: str | Path) -> Station:
    path = Path(key_or_path)
    if not path.suffix:
        path = CONFIG_DIR / f"{key_or_path}.yaml"
    c = yaml.safe_load(path.read_text())
    st = c["station"]
    resupply = c["fuel"]["resupply_date"]
    if isinstance(resupply, str):
        resupply = date.fromisoformat(resupply)
    return Station(
        key=st["key"], name=st["name"], location=st["location"], lat=st["lat"], lon=st["lon"],
        utc_offset_h=st.get("utc_offset_h", round(st["lon"] / 15)),
        gensets=tuple(Genset(**g) for g in c["gensets"]),
        genset_start_cost_l=c.get("genset_start_cost_l", 4.0),
        genset_start_wear_l=c.get("genset_start_wear_l", 0.0),
        genset_min_up_h=c.get("genset_min_up_h", 0.0),
        diesel_kwh_per_l=c.get("diesel_kwh_per_l", 10.0),
        pv=PV(**c["pv"]), wind=Wind(**c["wind"]), battery=Battery(**c["battery"]),
        tank=ThermalTank(**c["thermal_tank"]),
        p2h_max_kw=c["p2h"]["max_kw"], p2h_eff=c["p2h"]["efficiency"],
        boiler_max_kw=c["boiler"]["max_kw"], boiler_eff=c["boiler"]["efficiency"],
        loads=c["loads"],
        fuel=Fuel(**{**c["fuel"], "resupply_date": resupply}),
        control=Control(**c["control"]),
        weather_years=tuple(c["weather"]["years"]),
        train_year=c["weather"]["train_year"], val_year=c["weather"]["val_year"],
        test_year=c["weather"]["test_year"],
        raw=c,
    )


def station_keys() -> list[str]:
    return sorted(p.stem for p in CONFIG_DIR.glob("*.yaml"))
