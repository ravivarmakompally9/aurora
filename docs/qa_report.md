# QA report: judge-style test pass

**Date:** 5 Oct 2026

**Scope:**
- Every dashboard screen, checked for console and network errors.
- The full 5-minute demo script.
- Numbers checked for agreement across screens.
- Dark mode, light mode, and a 768 px tablet window.

**Result:** 16 issues found and fixed. 8 regression tests added, so `uv run pytest` now runs 40 tests, all passing. The year comparison and forecast report were re-run, and the screenshots were re-taken.

## Bugs fixed

| # | Severity | What a judge would have seen | Cause | Fix |
|---|---|---|---|---|
| 1 | Critical | After clicking **D · Ship delayed** while paused, the Overview still said **99%, Safe** (the real score was 0%) | The dashboard only received updates while the simulation was running | The server now pushes the overview every second even when paused. A "Latest event" line confirms each injection |
| 2 | Critical | Forecast & plan screen failed (HTTP 500) after any event injected while paused | Injection forced a re-plan by setting the plan time to −10⁹, which the view then used as an index | Added an explicit `request_replan()` flag |
| 3 | Serious | Thermal tank at **5%** when a blizzard hit (target 80%) | The optimiser planned to pre-heat the tank with the boiler, but the twin had no boiler setpoint and ignored it | Added `Setpoint.boiler_kw`. The twin burns planned boiler heat only where useful (demand or tank) |
| 4 | Serious | With all generators tripped, AURORA dropped to diesel-first fallback, exactly when it was most needed | Three constraints became impossible: spinning reserve, the daily water quota, and the storm standby unit | Reserve and water became heavily penalised soft constraints. Standby is capped at the units available |
| 5 | Serious | Storm Mode switched on and off within an hour on ordinary windy days | Weather-forecast error was re-drawn every 15 min, so consecutive forecasts disagreed | The forecast is now issued as a 6-hourly run (as real weather centres do), and re-plans reuse it |
| 6 | Medium | Year replay ended at 274.9 / 214.7 kL; the KPI table said 275,831 / 215,567 L | The replay dropped the two partial days at the year edges (UTC to station-time shift) | The edge hours are kept inside 1 Jan and 31 Dec, so totals match exactly |
| 7 | Medium | Mixed number formats (2,75,831 L next to 275.8 kL) | Inconsistent formatting | Fuel shown in kL everywhere in the Lab |
| 8 | Medium | Lab chart empty at rest (one dot at "Jan") | Replay started at day 1 | The Lab opens on the finished year; **Replay year** animates it |
| 9 | Medium | Replay axis stretched while playing; replay slower than 60 s on slow or throttled screens | The axis grew with the data; playback advanced one day per timer tick | Full-year axis fixed; playback tied to the clock (always 60 s) |
| 10 | Medium | "Peak about 48 m/s" for a 32 m/s blizzard | One noisy forecast run 20–40 h ahead | The card says when wind passes 20 m/s and whether the turbines will need to stop, instead of quoting one uncertain number |
| 11 | Low | "Onset in 16 h" (Lab) vs "in 18 h" (storm card) | Different meanings of "onset" | Lab says "winds start rising in 16 h"; the card says "wind above 20 m/s in N h" |
| 12 | Low | Generator failure did nothing visible, and a trip appeared as "Stopped G1" (as if AURORA chose it) | It tripped an idle unit; the explainer treated trips as decisions | Trips the running unit (or says it was on standby). New "G1 tripped" warning card |
| 13 | Low | Optimiser-crash scenario had no effect while paused | An 8-second wall-clock timer | The crash now lasts 2 simulated hours |
| 14 | Low | Overview showed days-old, duplicated "Storm Mode activated" alerts | No time window on alerts | Only the last 12 h, one per title |
| 15 | Low | Forecast and Decisions screens re-downloaded every second | Refresh tied to every simulation tick | Once per simulated hour or every 3–4 s |
| 16 | Low | Server log flooded by solver tables; sensor events had no text; fuel settings showed the starting fuel, not the current level | Logging levels and data-model gaps | Solver logs moved to WARNING; messages added; live level reported |

## Checked and fine
- No console errors and no failed requests on any screen after the fixes.
- Fuel level and Fuel Survival Score agree between Overview, Fuel & resupply and the API.
- Year replay, KPI table and summary agree: 275.8 / 215.6 kL, 60.2 kL saved (21.8%), 161 t CO₂.
- Tablet (768 px): no horizontal overflow, and every control is at least 44 px tall.
- Light and dark themes both readable.

## Confusing but intended (be ready to explain)
- **More generator starts** (788 vs 332 a year): AURORA turns units off when the battery and renewables can carry the load. Every start is charged in the optimiser; savings are net of it.
- **Heat from the oil boiler with all generators off:** cheaper than running a generator half-loaded just for its waste heat. This is the power + heat co-optimisation at work.
- **Occasional "Guardrail: reserve restored" cards:** the safety layer starting a unit when real conditions differ from the forecast. This is the guardrail doing its job.
- **Forecast numbers differ from injected values:** forecasts carry realistic error, and a storm 20 h out is uncertain.

## Not tested
- `docker compose up` (Docker is not installed on the development Mac).
