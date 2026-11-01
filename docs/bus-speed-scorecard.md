# CTA bus speed scorecard

Page: `index.html` with `cta-bus-speed-scorecard.css` and `.js`
Pipeline: `scripts/bus-speed-scorecard/` · Data: `data/bus-speed-scorecard/` · Graphics: `images/cta-bus-speed-*.png`

Operating ("commercial", stops included) speeds for the CTA's 20 highest-ridership bus routes, weekday rush hour vs midday, built from the Chicago Transit Alerts Bus Tracker position archive with DuckDB 2.0.

## Headline results (20 weekdays, Sep 28 – Oct 30, 2026)

Fixed-segment speeds (the same ~220 m segments, with the same distance weights, in every period):

| | Top 20 routes | 62 other all-day, non-express routes |
|---|---|---|
| Rush hour (7–9 AM + 4–6 PM) | 8.3 mph | 9.1 mph |
| Midday (10 AM–2 PM) | 9.0 mph | 10.2 mph |
| Morning rush (7–9 AM) | 8.9 mph | 9.7 mph |
| Evening rush (4–6 PM) | 7.8 mph | 8.6 mph |

- Rush is slower than midday on 19 of 20 routes; the 95% interval for route 4 spans zero. The evening rush is slower than midday on all 20.
- 14 of the top 20 rank in the slower half of the 82 comparable routes.
- The Loop (Lake to Congress, Wacker to Michigan) averages 4.6 mph in the evening rush. Route 146 on Lake Shore Drive (Division to Belmont) averages 29 mph.
- Express vs local on shared segments: +7% to +14% in both rushes. Express buses barely run midday, so midday is not compared.

Exact values live in `data/bus-speed-scorecard/scorecard.json` (`system`, `routes`). All-service pooled speeds are kept as `*_all_service` for transparency. Prose numbers on the page are bound to that file by `cta-bus-speed-scorecard.js`, so the page cannot drift from the data.

## Sources

| Source | Use | Notes |
|---|---|---|
| `https://data.chicagotransitalerts.app/positions/index.json` and the daily `bus/YYYY/MM/YYYY-MM-DD.ndjson.gz` files | Vehicle positions, ~60 s polling | 33 daily files, 29.5M rows, SHA-256 verified on ingest. Checksums: `data/bus-speed-scorecard/source_manifest.csv` |
| Chicago Data Portal `jyb9-n7fm` (CTA Ridership, Bus Routes, Daily Totals by Route) | Top-20 ranking | Average weekday boardings, Sep 1 2025 – Aug 31 2026, the latest 12 months published as of Oct 31 2026 |
| `data/chicago-wards.geojson` | Map silhouette | Dissolved to `data/bus-speed-scorecard/chicago-outline.json` |

## Refresh

```bash
# From the repository root; install requirements first (see README)
python scripts/transit_archive.py ingest --db local/transit.duckdb --raw-dir local/raw \
    --kinds bus --days 33 --end 2026-10-30 --as-of 2026-10-31

# From the repo root
.venv/bin/python -I scripts/bus-speed-scorecard/build.py --db local/transit.duckdb \
    --ridership data/sources/cta-bus-daily.csv --fetch-ridership --out data/bus-speed-scorecard
.venv/bin/python -I scripts/bus-speed-scorecard/render_social.py --variant dumbbell \
    --data data/bus-speed-scorecard/scorecard.json --out images/cta-bus-speed-scorecard.png
.venv/bin/python -I scripts/bus-speed-scorecard/render_map.py --cells data/bus-speed-scorecard/corridor_cells.csv \
    --data data/bus-speed-scorecard/scorecard.json --wards data/chicago-wards.geojson --out images/cta-bus-speed-map.png
.venv/bin/python -I scripts/bus-speed-scorecard/render_card.py --data data/bus-speed-scorecard/scorecard.json \
    --out images/cta-bus-speed-scorecard-card.png
```

A full build takes about a minute on an M-series laptop. `build.py` processes routes in batches of about 4M rows, because one pass over all 125 routes exceeded a 12 GB memory limit. Day exclusions are the `EXCLUDED_DAYS` dict in `build.py`. When a new window is analyzed, re-run the feed audit first: query `coverage_gaps` and per-window minute coverage, as in `docs/bus-speed-scorecard/profiling-feed.md`.

The web page uses system fonts. Renderers accept an optional `--headline-font` TTF path.

## Method decisions

The data was profiled before any scorecard SQL was written. The two reports are in `docs/bus-speed-scorecard/profiling-feed.md` and `profiling-speed.md`. Thresholds are tagged `[T0]`–`[T8]` in `scorecard.sql`.

| Decision | Choice | Why | Effect if changed |
|---|---|---|---|
| Speed definition | Σ Δpdist ÷ Σ Δvehicle_ts (space-mean), stops and signals included ("operating" or commercial speed, not a rider's door-to-door trip time) | Time riders spend on board; per-pair means overweight short fast intervals | Net-trip vs pair-sum methods agree to 3 decimals |
| Same segments | Route speed = Σw ÷ Σ(w / v_cell) over ~220 m cells with ≥ 20 pairs in each of AM, midday and PM; w = cell's total feet | Pooling by period mixes slower travel with where buses run (rush-only extensions, outer ends served more at midday) | Route 20's rush penalty is 8.6% pooled vs 2.6% on fixed segments; top-20 penalty 10.0% vs 8.2%. Coverage 99% of distance |
| Holding spots | Drop fixed-segment cells averaging < 1 mph in any period | Two cells (routes 77 and 79) are waiting spots, not travel; a zero-distance resample also broke the bootstrap | Route 77 rush 7.83 → 7.89 mph |
| Comparison set | Frequent non-express routes outside the top 20 with ≥ 100 vehicle-hours in each period (62 routes) | Rush-only, express and lightly served routes have no comparable midday | Pooled all-service: 9.1 mph at rush; fixed segments: 9.1 |
| Express comparison | Shared ~220 m cells, both routes ≥ 40 pairs, AM and PM only | X49 has 24 midday vehicle-hours, all from AM trip tails | |
| Time basis | `vehicle_ts` (GPS fix), not poll `ts` | Fix spacing ranges from 30 to 90 s around the 60 s poll | |
| Dedup [T0] | One row per (trip, vehicle_ts) | 190,605 repeated frozen fixes across the archive, all identical | |
| Trip key [T0] | vehicle_id, pid, sched_start_date, sched_start_sec | All four are needed; pdist is per pattern | |
| Layover trim [T1] | From first fix > start + 500 ft to first fix ≥ max − 500 ft | 13% of observed time is terminal dwell | Without the trim, speeds read ~11% low. 250–2,000 ft moves results < 1% |
| Gap rule [T3] | Drop pairs > 180 s | Long gaps hide stand-stills and outages | Bridging all gaps lowers speeds ~0.8% |
| Snaps [T4–T6] | Drop Δpdist < 0; drop Δpdist > 2 × straight-line + 1,500 ft; 80 mph backstop | pdist re-snaps; a 50 mph cap deletes real Lake Shore Drive driving (146) | A 40 mph cap would cut route 146 by 12.5% |
| Stand-stills [T2] | Drop runs of ≤ 100 ft movement totalling ≥ 600 s | Breakdowns and holds, 0.45% of mid-route time | ~0.2% |
| Patterns [T7] | Keep pids ≥ 50% of the route's longest well-populated pattern and ≥ 30 trips | Garage and connector patterns run 13–14 mph | Route 9 +1.2%, route 66 +0.9% if kept |
| Periods [T8] | Weekday 7–9, 10–14, 16–18 local; pair assigned by local midpoint | User-chosen windows; midpoint vs start differ < 0.01 mph | |
| Days | 20 weekdays: exclude Oct 13–16 (PM rush missing after collector outages) and Oct 12 (holiday) | Prevents an AM-heavy "rush hour" | Strict 17-day list or adding Oct 12 changes the top-20 rush speed by +0.02 / +0.03 mph (all print 8.3); no route moves > 0.06 mph |
| Uncertainty | Bootstrap over service days (4,000 draws, paired across periods) on the fixed segments | Days are the independent unit | Rush < midday on 19 of 20 routes (the 4's interval includes 0); PM < midday on all 20 |
| Slowest stretch | Slowest pair of quarter-mile pdist bins at rush, on each route's two busiest patterns, ≥ 1 mile from either end | Terminal holds and turnarounds otherwise dominate | Named from the address grid (piecewise south of Madison) |

## Known data issues

- Collector outages: Oct 12 18:04 to midnight; Oct 13–16 from about 13:15–14:31 to midnight; Oct 17 from 15:52. Short gaps on Sep 30, Oct 1, Oct 22 and Oct 30 (17:41–18:07) are kept, because pairs never bridge gaps longer than 180 s.
- Route 47 switched to new, ~10% longer patterns from Oct 17, with the same terminals. Route 49 added 79th-bound patterns from Oct 19.
- Route 8 southbound shows a Division St jog between Halsted and Racine (3.8 mph). It is reported as the route's slowest stretch.
- `sched_start_date` is `YYYY-MM-DD`. `trip_id`, `direction` and `next_station` are null for buses.

## Outputs

| File | Contents |
|---|---|
| `scorecard.json` | Every page figure: routes (period speeds, CIs, hourly profile, slowest half-miles, QA), system aggregates, regions, express pairs, sensitivity, metadata, SQL text and source manifest |
| `route_day_hour.csv` | Base table: feet, seconds, pairs and trips by route × service day × local hour, for all routes. All-service pooled period figures can be recomputed from it; fixed-segment figures and confidence intervals require cell-by-day inputs from the archive |
| `route_daily.csv`, `route_hourly.csv` | Daily rush and midday speeds (top 20), and weekday hourly speeds (all routes) |
| `corridor_cells.csv`, `map_cells.json` | ~220 m GPS-midpoint cells by route and period. The map JSON pools the 20 routes, cells ≥ 40 pairs |
| `pattern_bins.csv`, `patterns.csv` | Quarter-mile pdist bins (slowest stretches) and pattern inclusion decisions |
| `qa_funnel.csv` | Per-route counts removed by each rule (flags overlap, so counts are not additive) |

## Graphics

- `images/cta-bus-speed-scorecard.png`: 1600×2000 Bluesky graphic (dumbbell, rush vs midday)
- `images/cta-bus-speed-map.png`: 1600×2000 evening-rush corridor map
- `images/cta-bus-speed-scorecard-card.png`: 1200×630 `og:image` link card

## Review

An independent review re-ran the SQL route by route and reproduced every speed to 4 decimals. It also cross-checked five routes with an interpolated end-to-end method (−1.3% to +3.5% against the published fixed-segment speeds). It flagged the express midday comparison, a mislabeled Lake Shore Drive callout, composition effects in pooled period speeds, the comparison set, and terminal-adjacent "slowest stretches". A verification pass then reproduced every published number with independent code. It caught remaining wording problems and a bootstrap edge case (zero-distance resampled cells), and both were fixed.

## Limitations

Fall weekdays only; hourly charts use all service in each hour; no schedule data (no on-time or planned-speed comparison); bus-weighted, not rider-weighted; map cells pool directions and routes; slowest-stretch street names are approximated from Chicago's address grid.
