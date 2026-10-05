"""Build the slide-ready tables in docs/analysis_tables.md from the simulation results.

Reads docs/year_bharati_2023.json (full station, all capabilities) and docs/analysis/*.json
(written by scripts/analysis.py). Every number in the tables comes from those files.
"""
from __future__ import annotations

import json

from aurora.config import ROOT

DOCS = ROOT / "docs"
A = DOCS / "analysis"


def load(tag: str | None) -> dict:
    path = DOCS / "year_bharati_2023.json" if tag is None else A / f"year_bharati_2023_{tag}.json"
    return json.loads(path.read_text())


def L(v: float) -> str:
    return f"{v:,.0f}"


def pct(v: float, d: int = 1) -> str:
    return f"{v:.{d}f}%"


def main():
    full = load(None)
    base_ref = full["diesel_first"]["fuel_l"]
    out = ["# AURORA analysis tables (generated)", "",
           "All values are from full-year digital-twin simulations (2023 NASA POWER weather, Bharati-like station). "
           "Simulated, not measured. Regenerate with `uv run python scripts/analysis_report.py`.", ""]

    # 1. equipment step-up
    steps = [("eq_diesel", "Generators + waste-heat recovery (today)"), ("eq_tank", "+ 900 kWh thermal tank"),
             ("eq_battery", "+ 500 kWh battery"), ("eq_wind", "+ 2 × 30 kW wind"), (None, "+ 80 kWp solar (full prototype)")]
    today = load("eq_diesel")["diesel_first"]["fuel_l"]
    out += ["## 1. Equipment step-up", "",
            "Each row is a station with the listed equipment, run for a year under today's diesel-first rules and under AURORA.",
            "",
            "| Station equipment | Diesel-first (L/yr) | AURORA (L/yr) | AURORA saving | AURORA vs today's station | Starts (AURORA) |",
            "|---|---:|---:|---:|---:|---:|"]
    for tag, label in steps:
        r = load(tag)
        b, a = r["diesel_first"]["fuel_l"], r["aurora"]["fuel_l"]
        out.append(f"| {label} | {L(b)} | {L(a)} | {pct(100 * (b - a) / b)} | {pct(100 * (today - a) / today)} | "
                   f"{r['aurora']['gen_starts']} |")
    out += ["", "*AURORA saving* compares the two control strategies on the same equipment. *AURORA vs today's station* "
            "compares with the diesel-only station run as today (first row, diesel-first column).", ""]

    # 2. savings breakdown (cumulative, in this order)
    order = [("bd_commit", "Generator commitment and loading"), ("bd_battery", "Battery scheduling"),
             ("bd_flexible", "Flexible-load scheduling (water, laundry)"), ("bd_tank", "Waste-heat storage (thermal tank)"),
             (None, "Power-to-heat")]
    total = base_ref - full["aurora"]["fuel_l"]
    prev = base_ref
    out += ["## 2. Where the saving comes from", "",
            f"Full station. Diesel-first uses {L(base_ref)} L/yr. AURORA's capabilities are switched on one at a time, in this order; "
            "each row is the extra saving from that step. Interactions mean a different order would split the total differently.",
            "",
            "| Source (added in this order) | Litres/yr | % of diesel-first fuel | Share of AURORA's saving |",
            "|---|---:|---:|---:|"]
    for tag, label in order:
        a = load(tag)["aurora"]["fuel_l"] if tag else full["aurora"]["fuel_l"]
        d = prev - a
        if abs(d) < 0.0025 * base_ref:  # below 0.25% of fuel: run-to-run noise, not a real effect
            out.append(f"| {label} | ≈ 0 ({L(d)}) | ≈ 0% | ≈ 0% |")
        else:
            out.append(f"| {label} | {L(d)} | {pct(100 * d / base_ref)} | {pct(100 * d / total, 0)} |")
        prev = a
    out.append(f"| **Total** | **{L(total)}** | **{pct(100 * total / base_ref)}** | **100%** |")
    out.append("")

    # 3. stress tests
    ref_pct = full["comparison"]["fuel_saved_pct"]
    stress = [(None, "Reference (as in README)"), ("st_fcx2", "Weather-forecast error doubled"),
              ("st_cold3", "Colder year: 2023 weather 3 °C colder"), ("st_crew125", "25% more crew (88 summer / 30 winter)"),
              ("st_halfbatt", "Half the battery (250 kWh / 100 kW)"), ("st_crewpub", "Published Bharati crew (47 summer / 24 winter)")]
    out += ["## 3. Stress tests", "",
            "| Scenario | Diesel-first (L/yr) | AURORA (L/yr) | Saving | Change vs reference | Critical load served | Optimiser failures |",
            "|---|---:|---:|---:|---:|---:|---:|"]
    for tag, label in stress:
        r = load(tag) if tag else full
        c = r["comparison"]
        delta = "–" if tag is None else f"{c['fuel_saved_pct'] - ref_pct:+.1f} pts"
        out.append(f"| {label} | {L(r['diesel_first']['fuel_l'])} | {L(r['aurora']['fuel_l'])} | {pct(c['fuel_saved_pct'])} | "
                   f"{delta} | {pct(r['aurora']['critical_served_pct'], 2)} | {r['solver']['failures']} |")
    out.append("")

    # reference KPI table
    k = [("Diesel used (L)", "fuel_l", L), ("CO₂ (t)", "co2_t", lambda v: f"{v:,.0f}"),
         ("Renewable fraction (power + heat)", "renewable_fraction", lambda v: pct(100 * v)),
         ("Renewables curtailed", "curtailed_pct", pct), ("Critical load served", "critical_served_pct", lambda v: pct(v, 2)),
         ("Generator run-hours", "gen_run_hours", L), ("Low-load hours (<40%)", "gen_low_load_hours", L),
         ("Mean generator loading", "gen_mean_loading_pct", lambda v: pct(v, 0)), ("Generator starts", "gen_starts", L)]
    out += ["## Reference year (full station)", "", "| KPI | Diesel-first | AURORA |", "|---|---:|---:|"]
    for label, key, f in k:
        out.append(f"| {label} | {f(full['diesel_first'][key])} | {f(full['aurora'][key])} |")
    c = full["comparison"]
    out += ["", f"Fuel saved {L(c['fuel_saved_l'])} L ({pct(c['fuel_saved_pct'])}), CO₂ avoided {c['co2_avoided_t']:.0f} t, "
            f"reserve days gained {c['reserve_days_gained']:.0f}. Solver: {full['solver']['solves']:,} solves, "
            f"{full['solver']['failures']} failures.", ""]
    (DOCS / "analysis_tables.md").write_text("\n".join(out))
    print("\n".join(out))


if __name__ == "__main__":
    main()
