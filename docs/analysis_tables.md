# AURORA analysis tables (generated)

All values are from full-year digital-twin simulations (2023 NASA POWER weather, Bharati-like station). Simulated, not measured. Regenerate with `uv run python scripts/analysis_report.py`.

## 1. Equipment step-up

Each row is a station with the listed equipment, run for a year under today's diesel-first rules and under AURORA.

| Station equipment | Diesel-first (L/yr) | AURORA (L/yr) | AURORA saving | AURORA vs today's station | Starts (AURORA) |
|---|---:|---:|---:|---:|---:|
| Generators + waste-heat recovery (today) | 355,204 | 324,863 | 8.5% | 8.5% | 167 |
| + 900 kWh thermal tank | 355,204 | 323,369 | 9.0% | 9.0% | 165 |
| + 500 kWh battery | 355,095 | 294,778 | 17.0% | 17.0% | 674 |
| + 2 × 30 kW wind | 304,812 | 241,769 | 20.7% | 31.9% | 558 |
| + 80 kWp solar (full prototype) | 275,831 | 213,908 | 22.4% | 39.8% | 560 |

*AURORA saving* compares the two control strategies on the same equipment. *AURORA vs today's station* compares with the diesel-only station run as today (first row, diesel-first column).

## 2. Where the saving comes from

Full station. Diesel-first uses 275,831 L/yr. AURORA's capabilities are switched on one at a time, in this order; each row is the extra saving from that step. Interactions mean a different order would split the total differently.

| Source (added in this order) | Litres/yr | % of diesel-first fuel | Share of AURORA's saving |
|---|---:|---:|---:|
| Generator commitment and loading | 15,503 | 5.6% | 25% |
| Battery scheduling | 22,311 | 8.1% | 36% |
| Flexible-load scheduling (water, laundry) | 4,073 | 1.5% | 7% |
| Waste-heat storage (thermal tank) | 20,317 | 7.4% | 33% |
| Power-to-heat | ≈ 0 (-280) | ≈ 0% | ≈ 0% |
| **Total** | **61,924** | **22.4%** | **100%** |

## 3. Stress tests

| Scenario | Diesel-first (L/yr) | AURORA (L/yr) | Saving | Change vs reference | Critical load served | Optimiser failures |
|---|---:|---:|---:|---:|---:|---:|
| Reference (as in README) | 275,831 | 213,908 | 22.4% | – | 100.00% | 0 |
| Weather-forecast error doubled | 275,831 | 215,290 | 21.9% | -0.5 pts | 100.00% | 0 |
| Colder year: 2023 weather 3 °C colder | 284,304 | 223,443 | 21.4% | -1.0 pts | 100.00% | 0 |
| 25% more crew (88 summer / 30 winter) | 296,484 | 233,331 | 21.3% | -1.1 pts | 100.00% | 0 |
| Half the battery (250 kWh / 100 kW) | 283,471 | 222,298 | 21.6% | -0.9 pts | 100.00% | 0 |
| Published Bharati crew (47 summer / 24 winter) | 261,398 | 204,253 | 21.9% | -0.6 pts | 100.00% | 0 |

## Reference year (full station)

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
