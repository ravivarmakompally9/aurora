# AURORA results analysis

**What this is:** the evidence behind AURORA's headline result.
- **Every number is from a full-year digital-twin simulation:** 2023 NASA POWER weather and a Bharati-like station, with diesel-first control against AURORA on identical weather, loads and equipment.
- **These are simulated results, not measurements at a real station.** [data_card.md](data_card.md) lists every assumption and which values are illustrative.
- **Tables are generated** from the result files by `scripts/analysis_report.py`, and `scripts/analysis.py` re-runs all scenarios (about 13 × 8 min on 10 cores). Copy the tables into slides as they are.

**Headline:** AURORA uses **22.4% less diesel** than diesel-first rules (61,924 L and 166 t CO₂ a year). Critical loads are served 100% of the time. The saving stays between **21.3% and 21.9%** under every stress test, and it is **8.5% even on today's diesel-only equipment**.

## Reference year

| KPI | Diesel-first | AURORA |
|---|---:|---:|
| Diesel used (L) | 275,831 | 213,908 |
| CO₂ (t) | 739 | 573 |
| Renewable fraction (power + heat) | 14.7% | 19.5% |
| Renewables curtailed | 24.7% | 0.0% |
| Critical load served | 100.00% | 100.00% |
| Generator run-hours | 9,367 | 3,060 |
| Low-load hours (<40%) | 7,453 | 246 |
| Mean generator loading | 35% | 87% |
| Generator starts | 332 | 560 |

Fuel saved 61,924 L (22.4%), CO₂ avoided 166 t, reserve days gained 84. Solver: 2,920 solves, 0 failures.

## 1. Starting from today's equipment

Indian stations today run on generators with waste-heat recovery. The first row is that station: no solar, no wind, no battery. Each following row adds one piece of equipment, and each is run for a year under both control strategies.

Each row is a station with the listed equipment, run for a year under today's diesel-first rules and under AURORA.

| Station equipment | Diesel-first (L/yr) | AURORA (L/yr) | AURORA saving | AURORA vs today's station | Starts (AURORA) |
|---|---:|---:|---:|---:|---:|
| Generators + waste-heat recovery (today) | 355,204 | 324,863 | 8.5% | 8.5% | 167 |
| + 900 kWh thermal tank | 355,204 | 323,369 | 9.0% | 9.0% | 165 |
| + 500 kWh battery | 355,095 | 294,778 | 17.0% | 17.0% | 674 |
| + 2 × 30 kW wind | 304,812 | 241,769 | 20.7% | 31.9% | 558 |
| + 80 kWp solar (full prototype) | 275,831 | 213,908 | 22.4% | 39.8% | 560 |

*AURORA saving* compares the two control strategies on the same equipment. *AURORA vs today's station* compares with the diesel-only station run as today (first row, diesel-first column).

What this shows:
- **AURORA helps even with no new equipment: 8.5%.** It runs fewer generators at better load. There is no battery, so the safety reserve has to come from running units, which limits how far it can go.
- **A heat tank alone adds little (+0.5 pts).** With no battery, generators run almost continuously and there is little spare waste heat to store.
- **The battery is the big step (8.5% → 17%).** It lets AURORA switch generators off, cycle-charge at efficient load, and hold reserve without spinning a second unit. Diesel-first barely benefits from the same battery (355,095 L against 355,204 L), so the gain comes from the control, not from the hardware alone.
- **Wind and solar add further savings for both strategies.** The full prototype station under AURORA uses **39.8% less fuel than today's station run today**. That combines new equipment and smarter control; AURORA's share alone is the 22.4%.

Starts: AURORA starts generators more often once a battery exists (558–674 a year), because it can switch units off. The 2-hour minimum run time and the 10 L-equivalent cost per start apply in every scenario. Run lengths were checked for the reference year: no run is shorter than 2 hours, apart from 2 cut off at the end of 31 December.

## 2. Where the 22.4% comes from

Full station. Diesel-first uses 275,831 L/yr. AURORA's capabilities are switched on one at a time, in this order; each row is the extra saving from that step. Interactions mean a different order would split the total differently.

| Source (added in this order) | Litres/yr | % of diesel-first fuel | Share of AURORA's saving |
|---|---:|---:|---:|
| Generator commitment and loading | 15,503 | 5.6% | 25% |
| Battery scheduling | 22,311 | 8.1% | 36% |
| Flexible-load scheduling (water, laundry) | 4,073 | 1.5% | 7% |
| Waste-heat storage (thermal tank) | 20,317 | 7.4% | 33% |
| Power-to-heat | ≈ 0 (-280) | ≈ 0% | ≈ 0% |
| **Total** | **61,924** | **22.4%** | **100%** |

How the split was measured:
- AURORA's capabilities were switched on one at a time in the order shown, and the year was re-run each time with the same diesel-first baseline.
- With every capability off, AURORA still plans generator commitment and loading: how many units run, at what output, with a safety reserve. That is the first row.
- Each later row is the extra saving from adding one capability.
- With interacting effects, a different order would split the total differently. The total does not change.

Reading it:
- **Battery scheduling (36%), waste-heat storage (33%) and generator commitment (25%) carry the saving.**
- **Waste-heat storage matters because the thermal tank lets generators stop:** heat recovered while a unit runs keeps the station warm afterwards, instead of the oil boiler burning extra fuel.
- **Power-to-heat contributes nothing measurable at Bharati's renewable size.** The battery already absorbs surplus wind and solar, and curtailment is 0%. It would matter with larger renewable capacity.

## 3. Stress tests

| Scenario | Diesel-first (L/yr) | AURORA (L/yr) | Saving | Change vs reference | Critical load served | Optimiser failures |
|---|---:|---:|---:|---:|---:|---:|
| Reference (as in README) | 275,831 | 213,908 | 22.4% | – | 100.00% | 0 |
| Weather-forecast error doubled | 275,831 | 215,290 | 21.9% | -0.5 pts | 100.00% | 0 |
| Colder year: 2023 weather 3 °C colder | 284,304 | 223,443 | 21.4% | -1.0 pts | 100.00% | 0 |
| 25% more crew (88 summer / 30 winter) | 296,484 | 233,331 | 21.3% | -1.1 pts | 100.00% | 0 |
| Half the battery (250 kWh / 100 kW) | 283,471 | 222,298 | 21.6% | -0.9 pts | 100.00% | 0 |
| Published Bharati crew (47 summer / 24 winter) | 261,398 | 204,253 | 21.9% | -0.6 pts | 100.00% | 0 |

- **No scenario lost more than 1.1 points of saving, and all served 100% of critical load with 0 optimiser failures.**
- **Doubled forecast error costs 0.5 points.** The plan is re-made every 3 h and safety margins use the P90 load and P10 renewables, so forecast mistakes are corrected quickly.
- **A colder year and more crew raise fuel use for both strategies and trim AURORA's share by about 1 point.** More of the energy goes to heat, where the boiler and waste heat leave less room to optimise.
- **Half the battery costs 0.9 points.** Storage is the main lever (section 2), but even a small battery keeps most of the benefit.
- **With Bharati's published crew numbers** (47 in summer instead of the illustrative 70), diesel-first uses 261,398 L a year and AURORA saves 21.9%.

## 4. Which values are illustrative, and is 276,000 L a year plausible?

The full list is in [data_card.md §8](data_card.md#8-which-values-are-illustrative).
- **Real:** weather.
- **Matches a public source:** the winter crew of 24.
- **Illustrative:** the summer crew (70 against the published 47), generator sizes, building heat loss and per-person loads, and all fuel-logistics inputs.
- **Hypothetical, not claimed to exist at Bharati:** the battery, thermal tank, power-to-heat, wind turbines and solar.

On the 276,000 L a year:
- **It is the right order of magnitude, but it is not validated.** The modelled station averages 93 kW electric and 140 kW heat, which needs about 756 L/day of fuel under diesel-first control, plus about 150 L/day assumed for vehicles.
- **The nearest public reference:** Australia's Mawson station (about 20 people) saved 288,000 L of diesel in 2014 from wind supplying about half its electricity, so its annual use is several hundred thousand litres.
- **No public annual figure was found for Bharati or Maitri.** Treat the absolute litres as illustrative and the **percentage savings** as the robust result.
- **What would settle it:** NCPOR's fuel and meter records would replace the synthetic loads directly.

## Changes found while preparing this analysis

The equipment step-up exposed two problems in the optimiser. Both are fixed, and every number above uses the fixed version:

1. **The spinning reserve covered the water plant's 120 kW start as a possible surprise.** AURORA schedules the water plant itself, so it is not a surprise. The reserve now covers the largest *unscheduled* load step (a 40 kW experiment). With a battery this changed little; without one, the old rule forced two generators to run around the clock. This change moved the reference saving from 21.4% to 22.4%.
2. **The optimiser had no dump load for surplus generator output.** With the battery and power-to-heat switched off, it could fail to find a plan. A dump load (as real stations have) now absorbs it at a small cost.

Sources for section 4:
- [New Atlas: Bharathi research base](https://newatlas.com/bharathi-research-base/28498/) (crew numbers, CHP units)
- [RenewEconomy: Renewables at the South Pole](https://reneweconomy.com.au/renewables-at-the-south-pole-49298/amp/) (Mawson wind savings)
