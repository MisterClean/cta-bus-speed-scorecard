<!-- Profiling report written before the scorecard SQL. Paths like $WORKDIR refer to the analyst's local workspace; the SQL files it cites were exploratory and are not part of the published pipeline. -->

# CTA bus speed signal: data-quality profile

Scope: top-20 routes, 2026-09-28 to 2026-10-30, `positions_raw` (11,853,731 rows, 164,381 trips, 11.62M consecutive-fix pairs after dedup).
All numbers below were measured by me in DuckDB (read-only). The SQL lives in `p0.py`..`p17.py` in this folder (helpers in `h.py`); the production-style query is `recommended_speed.sql`, which I ran end-to-end (about 8 s) and which reproduces the prototype numbers exactly.
"Weekday daytime" benchmarks below exclude Oct 12-17 (feed-outage week, handled elsewhere) and use fixes with local midpoint hour 06-19.

## Executive summary (ranked by bias on route speeds)

| # | Issue | Bias if ignored (top-20 weekday daytime, 8.83 mph reference) | Fix |
|---|---|---|---|
| 1 | **Terminal layovers** at start and end of each trip. 12-15% of observed trip time is spent within 250-1000 ft of the first/last pdist. | **-10.5%** (7.90 vs 8.83 mph); per route -10% to -11.4% (66: 7.15 vs 7.99; 9: 8.96 vs 10.00; 3: 8.29 vs 9.36) | Trim each trip to [first fix with pdist > pfirst+500, first fix with pdist >= pmax-500] |
| 2 | **Speed cap that is wrong for Lake Shore Drive** (146, partly 151). A blanket "drop >50 mph" rule removes real fast driving. | Route 146: **-2.1%** at cap 50 (8.42 vs 8.59), -12.5% at cap 40 (7.51). Top-20 total only -0.5%. | Replace the mph cap with a GPS-geometry test (dd <= 2*crow+1500 ft) plus an 80 mph backstop |
| 3 | **Gap bridging policy** (pairs with dt > 180 s). | Bridging everything: -0.8% (8.76); dropping >180 s: about +1.0% vs bridging. Long gaps are slow (4.5-5.5 mph). | Drop pairs with dt > 180 s (0.31% of pairs, about 2% of time) |
| 4 | **Short / connector patterns** (route 9 pids 3637/3634, route 66 pids 4601/6982, ...). Run at 13-14 mph vs 8-10 for the full pattern. | Route 9 reads 9.99 with all patterns vs 9.87 with connectors out (+1.2% bias if left in); route 66 reads 7.99 vs 7.92 (+0.9%). Top-20 pooled effect about 0.4%. | Exclude patterns shorter than 50% of the route's longest pattern, or fewer than 30 trips |
| 5 | **Partial trip coverage.** 84% of trips are observed end-to-end. Partial trips are slower (8.53 vs 8.86 mph). | Not removable by filtering; no positional bias visible by pattern decile (within 0.1 mph). | Report coverage; do not require complete trips |
| 6 | **Mid-route stand-still runs >= 10 min** (relief / breakdown / incidents). 0.45% of mid-route time, 1.4% of trips. | -0.2% (8.81 vs 8.83) | Drop runs of |dd| <= 100 ft totalling >= 600 s |
| 7 | pdist jumps (spurious forward snaps), backward steps, stale fixes. | Each under 0.5% of speed. Net-vs-pairs method difference is zero. | Dedup on (trip, vehicle_ts); drop backward pairs and geometry-inconsistent jumps |

Things that do **not** matter: net trip progress (last pdist - first pdist) / (last ts - first ts) vs sum of positive pair deltas vs sum of all pair deltas (identical to 3 decimals), pair period assignment by midpoint vs start (<= 0.006 mph), clamping vs dropping vs keeping negative pairs (<= 0.01 mph).

Sanity check on levels: the recommended pipeline gives 6.5-10.7 mph by route and period (system-in-scope 8.25 peak, 9.17 off-peak). That is below the "10-12 mph" figure you quoted. I could not verify that figure; my numbers include dwell at every stop and signal and exclude only terminal and long-gap time, and an independent end-to-end check agrees within 1-3% (section 8). So I do not think the pipeline is under-counting speed because of leftover layover, but the definition difference vs. the cited figure is worth confirming before publication.

## 1. Trip identity

Key tested: `(vehicle_id, pid, sched_start_date, sched_start_sec)`. No nulls in any of those columns or in pdist/vehicle_ts (top-20 rows). `trip_id` is entirely null.

```sql
select count(distinct (vid,pid,ssd,sss)) trips,
       count(distinct (vid,ssd,sss))     trips_without_pid,     -- 164,165
       count(distinct (vid,pid,ssd))     trips_without_sss      -- 78,959
from b;
```

| Check | Result |
|---|---|
| Trips under full key | 164,381 |
| Dropping `pid` from key | 164,165 (216 keys carry 2 pids; 215 are same-route pid flips mid-trip, 1 crosses routes) |
| Dropping `sched_start_sec` | 78,959, so `sched_start_sec` is required (vehicles run multiple trips of the same pid per day) |
| Dropping `vehicle_id` | 2,348 of 161,945 (pid,ssd,sss) keys have 2-8 vehicles, so vehicle must stay in the key (bus swaps / reused schedule slots) |
| Trip duration (first to last fix) | p50 1.23 h, p99 2.30 h, max 7.26 h (2 trips >6 h) |
| Within-key time gaps | 1,678 gaps >30 min, 364 >1 h, 2 >4 h (0.014% of pairs; the pair-gap filter handles them) |
| pdist reset inside a key | Only 42 pairs with dd < -20,000 ft, and about 6 look like a reset to near 0 |
| pdist at trip boundaries | A trip's first pdist: p10 0, median 5, p90 1,215 ft. The next trip of the same vehicle also starts at median 5 ft. pdist "resets" by the key changing, not inside a key. |
| Vehicle with 2 keys overlapping in time | 999 consecutive-key overlaps (0.6% of trips); 889 involve a pid change, overlap median 58 min |

Pid changes mid-trip: 216 keys (0.13%). Partitioning on pid splits these into two partial trips, which is the right behavior because pdist is only meaningful within a pid.

**Recommendation:** trip key = `(vehicle_id, pid, sched_start_date, sched_start_sec)`, ordered by `vehicle_ts`. Never form a pair across keys. No explicit pdist-reset detection is required.

## 2. Fix dedup (stale vehicle_ts)

```sql
select k, count(*) groups, sum(np>1) pdist_differs, sum(nll>1) latlon_differs
from (select vid,vts,count(*) k,count(distinct pdist) np,count(distinct (lat,lon)) nll from b group by all) group by 1;
```

| Finding | Number |
|---|---|
| Rows that repeat an earlier `(vehicle_id, vehicle_ts)` | 66,647 of 11,853,731 (0.56%) |
| Groups of repeated fixes with differing pdist, lat/lon, pid or key | **0 of 29,877** |
| Large repeat groups (10-11 consecutive polls) | 2,563 groups, so some buses stay stale for ~10 minutes |
| `vehicle_ts` going backwards between consecutive polls | 118 (max -45 s) |
| Poll interval | p1 57.9 s, median 60.0 s, p99 76.3 s |

A repeated vehicle_ts carries identical position, so it adds no information and, if kept, produces dt=0 (undefined speed) pairs or inflates dwell. **Dedup on (trip key, vehicle_ts)** (`min(pdist)`; all identical). Form pairs on distinct fixes ordered by vehicle_ts, using vehicle_ts (not poll ts) for dt.

Distinct-fix gap distribution (dt between consecutive distinct fixes, 11.62M pairs): p1 30 s, p5 39, p25 54, median 60, p75 67, p90 76, p95 81, p99 91, p99.9 463 s.

## 3. pdist monotonicity and implied speed

```sql
-- pairs: lag() over (partition by vid,pid,ssd,sss order by vts) on deduped fixes
select sum(dd<0) neg, sum(dd=0) zero, sum(dd>0) pos, sum(mph>50), sum(mph>70) from pr2;
```

| Class | Pairs | Share |
|---|---|---|
| dd < 0 | 19,132 | 0.165% |
| dd = 0 | 1,332,834 | 11.47% (stopped, plus stale position) |
| dd > 0 | 10,270,737 | 88.37% |
| implied > 50 mph | 4,177 | 0.036% |
| > 70 mph | 1,882 | 0.016% |
| > 100 / > 200 mph | 1,301 / 562 | |

dd quantiles (ft): p0.1 -41, p1 0, p25 288, median 696, p75 1,123, p95 1,798, p99 2,439, p99.9 4,402.

**Negative steps** by size: (-50,0) 7,945; [-200,-50] 3,971; [-1000,-200] 5,570; [-5000,-1000] 1,443; < -5000 203.
Do they reverse? (share where pdist is back within 100 ft of its pre-dip level by the next fix)

| Dip size | n | recovered by next fix | within 2 | within 3 |
|---|---|---|---|---|
| < 200 ft | 8,592 | 89.2% | 90.5% | 91.1% |
| 200-1000 ft | 3,320 | 24.4% | 34.0% | 38.6% |
| > 1000 ft | 1,058 | 5.3% | 12.0% | 17.2% |

Small dips are snapping noise. Large backward moves are level shifts (pattern re-snap / pid-adjacent geometry) and do not reverse. Total negative distance is 116 miles against 1.64M positive miles (0.007%).

**Forward jumps.** The >50 mph pairs are concentrated, not random: route 146 has 0.45% of pairs >50 mph vs 0.01-0.05% elsewhere. For non-146 routes the jumps look spurious:
- 98% stay at the new level (not spikes that snap back); 78.5% of >70 mph jumps are preceded by at least one dd=0 pair.
- Using lat/lon, great-circle distance (crow) between the two fixes has median 5% of dd for >70 mph pairs. Normal moving pairs have dd/crow median 1.02, p90 1.43 (n=3.55M). So the position did not move as far as pdist claims: pdist re-snapped.
- Geometry test `dd > 2*crow + 1500 ft` flags 0.02% of pairs at <=50 mph, 57.7% of pairs >50 mph (2,411 of 4,177), and 4,331 pairs overall.
- For route 146, 1,534 of its 1,681 pairs above 50 mph pass the geometry test; their speed is p10 50.4, median 51.9, p90 53.9 mph. These are real Lake Shore Drive driving. A mph cap of 50 deletes them (Section 8 sensitivity: 146 goes from 8.59 to 8.42). A cap of 40 would be a disaster for 146 (7.51).
- Route 47 shows 809 geometry-inconsistent pairs at <=50 mph (985 total); I did not investigate why (possible pattern geometry problem).

**Trip-level vs pair-sum.** For trips in the trimmed window (160,981 trips):

| Method | mph (all top-20) |
|---|---|
| (pdist(arr) - pdist(dep)) / (arr - dep), Σ-over-trips | 9.526 |
| Σ all pair dd / Σ dt | 9.526 |
| Σ positive-only dd / Σ dt | 9.526 (ratio to net at trip level: p1 1.0, median 1.0, p99 1.0003) |
| Kept pairs after filters | 9.594 (different window: gap and jump filters remove time too) |

The first two are identical by telescoping; positives-only differs by 116 miles out of 1.64M. **The choice between them is irrelevant.** What matters is the pair filters: for route 146, kept pairs under a cap-50 rule give 8.73 vs 8.89 for the unfiltered net method, which is exactly the LSD artifact above. Use Σ pairs (needed anyway to assign pairs to time periods).

## 4. Time gaps

Body pairs (not within 1000 ft of either terminal, dd >= 0, mph <= 50; 9.78M pairs):

| dt bucket | % pairs | % time | space-mean mph | % with dd=0 |
|---|---|---|---|---|
| <= 45 s | 11.78 | 7.54 | 10.90 | 2.3 |
| 46-75 | 77.64 | 76.49 | 9.64 | 2.4 |
| 76-90 | 9.59 | 12.62 | 8.64 | 0.5 |
| 91-120 | 0.43 | 0.70 | 7.98 | 3.1 |
| 121-180 | 0.25 | 0.60 | 7.76 | 1.0 |
| 181-300 | 0.17 | 0.62 | 5.55 | 14.5 |
| 301-600 | 0.09 | 0.59 | 4.49 | 14.3 |
| > 600 | 0.05 | 0.85 | 5.48 | 20.8 |

| Max-gap rule | Body-pair speed (mph) | Pairs kept |
|---|---|---|
| none | 9.499 | 9,783,131 |
| <= 600 s | 9.533 | 9,778,701 |
| <= 300 s | 9.563 | 9,770,108 |
| <= 180 s | 9.589 | 9,753,353 |
| <= 120 s | 9.600 | 9,729,004 |
| <= 90 s | 9.611 | 9,686,684 |

Longer gaps correlate with **low** speed (dd=0 pairs are 14-21% of gaps >180 s vs 2-3% normally), so dropping them biases speed **up**, by about +1.0% at 180 s. Not dropping them bridges likely stand-stills and incident dwell and biases it down by the same order. Both are small. Recommended 180 s (3 polls): it removes 0.34% of all pairs, 2% of time. Interesting but unexplained: short-dt pairs look faster (10.9 mph at <=45 s) and 76-90 s look slower (8.6); this smells like jitter in vehicle_ts vs actual position time. The effect washes out in sums but is a reason not to use per-pair mean speed. The 0.34% of pairs with dt > 180 s are spread across days (max 0.62% on Oct 21); I did not break out time of day.

## 5. Terminal layovers

Trips with start observed (pfirst < 2,000 ft, n >= 5 fixes): 151,376. Time from the first fix until pdist exceeds pfirst+X, and from the first fix with pdist >= pmax-X until the last fix:

| X (ft) | Lead minutes p25/50/75/90/99 | mean | Trail minutes p25/50/75/90/99 | mean | Lead / trail / both share of observed trip time |
|---|---|---|---|---|---|
| 250 | 1.0/2.1/5.9/11.9/24.2 | 4.57 | 0.0/1.0/7.5/13.0/30.4 | 4.59 | 6.1% / 6.1% / 12.1% |
| 500 | 1.1/2.7/6.2/12.2/25.0 | 4.92 | 0.0/1.9/8.2/13.8/31.1 | 5.14 | 6.5% / 6.9% / 13.3% |
| 1000 | 1.9/3.2/7.0/13.0/25.9 | 5.49 | 0.9/2.9/9.1/14.7/32.1 | 5.93 | 7.3% / 7.9% / 15.1% |

Increasing X from 250 to 1000 only adds about 0.9 min lead time per trip, the time to cover 750 ft at ~9 mph, so the trim is not very threshold-sensitive: after X=250 we are already past most true dwell.

**Effect on speed** (weekday daytime, "G" pipeline: geometry filter, dt<=180, drop negatives):

| Rule | All top-20 | 9 | 66 | 146 | 3 |
|---|---|---|---|---|---|
| No trim, no relief rule | 7.90 | 8.96 | 7.15 | 7.81 | 8.29 |
| Trim 250 ft | 8.79 | 9.96 | 7.97 | 8.56 | 9.29 |
| **Trim 500 ft (recommended)** | 8.83 | 9.99 | 7.99 | 8.59 | 9.36 |
| Trim 1000 ft | 8.86 | 10.04 | 7.97 | 8.64 | 9.42 |
| Trim 2000 ft | 8.86 | 10.01 | 7.92 | 8.70 | 9.46 |

Trim vs no-trim: +11.8% overall. Between 250 and 2000 ft the spread is 0.8%: pick 500.

**Mid-route relief / stand-still runs** (consecutive pairs with |dd| <= 100 ft, inside the mid-route zone p0 >= 1000 and p1 <= pmax-1000; 9.79M pairs, 167,065 vehicle-hours):

| Run length ≥ | Runs | Vehicle-hours | % of mid-route time | Trips affected (% of all trips) |
|---|---|---|---|---|
| 120 s | 52,228 | 3,431 | 2.05% | 39,284 (23.9%) |
| 300 s | 9,615 | 1,519 | 0.91% | 8,670 (5.3%) |
| 600 s | 2,489 | 748 | 0.45% | 2,278 (1.4%) |
| 900 s | 1,153 | 478 | 0.29% | 1,108 (0.7%) |
| 1800 s | 261 | 187 | 0.11% | 259 (0.2%) |

Runs >= 10 min average 18 min; they are spread over the whole pattern (not clustered at specific pdist) and all hours (peak count in afternoon), which looks more like incidents / holds / breakdowns than scheduled relief. Highest: route 79 (297 runs), 9 (188), 146 (180), 82 (160). Runs of 60-300 s (the 120 s row is mostly ordinary traffic-signal and stop dwell, which door-to-door speed should keep) are not trimmed. Effect: the 600 s rule changes top-20 speed 8.81 → 8.83; a 300 s rule 8.86 (this one starts to cut real stop-and-go). Recommend 600 s; it is a small, defensible cleanup.

## 6. Pattern variants

Pattern length = p90 of per-trip max pdist within a pid. "Short" = < 80% of the longest pattern (>= 200 trips) on the route.

| Route | pids | trips | % trips on short patterns | longest pattern (ft) |
|---|---|---|---|---|
| 79 | 21 | 12,664 | 31.0 | 61,817 |
| 9 | 20 | 9,737 | 25.4 | 103,856 |
| 53 | 16 | 9,727 | 24.6 | 90,849 |
| 66 | 10 | 12,359 | 18.0 | 53,136 |
| 77 / 146 / 72 / 8 | | | 17.6 / 17.2 / 17.2 / 15.1 | |
| 4, 36, 49 | | | 0.2-0.4 | |

Weekday-daytime speed by pattern class (recommended pipeline):

| Route | full (>=80%) | mid (50-80%) | short (<50%) |
|---|---|---|---|
| 9 | 9.87 (54,986 mi) | none | **14.40** (2,282 mi, 5 pids) |
| 66 | 7.94 | 7.25 | **13.20** (1,050 mi, 2 pids) |
| 53 | 9.43 | 10.78 | 8.85 |
| 79 | 9.40 | 8.90 | 9.62 |
| 3 | 9.32 | 11.24 | 9.97 |
| 8 | 8.91 | 8.38 | 7.89 |
| all top-20 | 8.84 (94.3% of miles) | 8.36 (4.2%) | 9.43 (1.6%) |

Route 9's pids 3637/3634 are 14.2k/13.7k ft, in the far south (lat 41.72-41.80, almost constant lon -87.664), 989 and 973 trips; the typical vehicle sequence is full-pattern → 3637 → 3634 → full-pattern (modal previous/next pid). Route 66's 4601/6982 (10.6k/13.2k ft) sit around Austin-Pulaski. This sequencing and the 13-14 mph speeds suggest garage pull-in/pull-out or terminal-loop connectors, not revenue short-turns, but I **inferred this from sequencing, I did not check GTFS or destination text** (their destination fields say "74th", "95th", "Austin", "Pulaski"). Mid-length patterns behave like their parents (no consistent offset).

Inclusion effect (weekday daytime): route 9 9.99 (all) vs 9.87 (>=50% only); route 66 7.99 vs 7.92; route 79 9.35 vs 9.34; 146 unchanged; all-top-20 total 8.83 → about 8.8. Small overall, up to ~1% on routes with connectors.

**Recommendation:** include only patterns with `plen >= 0.5 * longest well-populated pattern on the route` and `>= 30 trips`; this excludes 105 of 275 pids but only 10,362 of 164,381 trips (6.3%). If GTFS shape/pattern type is available later, prefer excluding deadhead/connector patterns by that, and keep genuine short-turns (mid class).

## 7. Partial trips / coverage

Start observed = pfirst <= 1,500 ft; end observed = pmax >= p90-pattern-length − 1,500.

| | Share of trips |
|---|---|
| Start observed | 91.5% |
| End observed | 91.1% |
| Both (complete) | 84.1% (87.1% excluding Oct 12-17 and trips <10 min) |
| Neither observed | 1.5% |
| Worst days | Sep 27 55% (partial day), Oct 17 72.9%, Oct 14 73.0%, Oct 16 74.6% (outage week); Sep 30 76.3% (the worst non-outage day) |

Tail: pfirst p90 1,215, p95 6,603, p99 43,276 ft; pattern-end gap p90 1,237, p95 12,990, p99 55,928 ft.

Does incomplete coverage bias pair-based speed? Weekday daytime, recommended pipeline:

| | Trips | Miles | mph |
|---|---|---|---|
| complete | 74,378 | 739,679 | 8.86 |
| partial | 10,205 | 74,698 | 8.53 |

Per route (complete / partial): 9 10.06 / 9.37; 66 8.01 / 7.67; 146 8.64 / 8.30; 3 9.40 / 9.21. Partial trips are consistently 2-7% slower. I cannot say why (partial trips disproportionately come from outage/stale spells, and missing the faster end segments may also play a role), but positional coverage is balanced: share of miles per pattern decile is within 0.2 points for complete vs all, and speeds per decile differ by <= 0.1 mph. **Net effect of including partial trips: 8.83 vs 8.86, about 0.3% low; not worth filtering.** Report the complete-trip share as a quality indicator, per route/day.

## 8. Sanity benchmarks

Recommended pipeline (weekday, local midpoint in 07-09 or 16-18 for peak and 10-14 for off-peak; 20 service days after dropping Oct 12-17; Oct 12 is also Indigenous Peoples' Day):

| Route | Peak mph | Off-peak mph | Peak/Off |
|---|---|---|---|
| 9 | 9.30 | 10.19 | 0.91 |
| 66 | 7.45 | 8.23 | 0.91 |
| 146 | 8.04 | 8.91 | 0.90 |
| 3 | 8.93 | 9.44 | 0.95 |
| 53 | 8.79 | 9.82 | 0.90 |
| 79 | 9.03 | 9.55 | 0.95 |
| All 20 routes pooled (space-mean) | 8.25 | 9.17 | 0.90 |

Across all 20 routes: peak 6.45 (36) to 9.58 (4); off-peak 6.67 (36) to 10.67 (49). Routes 77 and 82 have the largest peak penalty (0.81). Full table: `prototype_top20.csv`. Route 4 shows essentially no peak/off-peak difference (0.99).

Level check: these are 1-3 mph below the "10-12 mph" the brief cited. My figures count all stop and signal dwell on the whole pattern, only trimming terminals and long gaps, and the independent check below agrees, so I read 8-10 mph as what the data supports for these top routes. I cannot verify the 10-12 figure's definition (it may be mixed all-hours/all-routes or exclude dwell). Slow downtown/crowded routes (36 at 6.5-6.7, 151 at 7.0-7.4, 22 at 7.1-7.8) read well under 10 as expected.

**Independent cross-check** (complete trips only, start pdist <= 1,000 and end >= pattern − 1,500, patterns >= 20k ft and included): speed = (pdist at first fix >= pattern−250 minus pdist at last fix <= 250) ÷ elapsed time between them, per trip midpoint period, vs the pair pipeline restricted to the same trips:

| Route | Period | Trips | End-to-end (Σdist/Σtime) | Per-trip median | Pair pipeline, same trips |
|---|---|---|---|---|---|
| 9 | peak | 507 | 9.37 | 9.43 | 9.38 |
| 9 | off | 637 | 9.98 | 10.04 | 10.21 |
| 66 | peak | 1,085 | 7.55 | 7.62 | 7.54 |
| 66 | off | 927 | 8.14 | 8.14 | 8.23 |
| 146 | peak | 474 | 7.98 | 8.03 | 8.12 |
| 146 | off | 372 | 8.86 | 8.87 | 8.93 |
| 3 | peak | 520 | 8.89 | 8.95 | 8.97 |
| 3 | off | 431 | 9.07 | 9.09 | 9.30 |

Agreement is within 0.1-0.25 mph (0-2.5%), the pipeline being slightly higher where it also trims 250 more feet of terminal slow-roll and drops long gaps. No sign of a systematic error.

## Recommended speed computation

Implemented in `recommended_speed.sql`. Steps and thresholds:

1. **Scope:** top-20 routes; weekday service days only; exclude Oct 12-17 (edit to the outage agent's final list).
2. **Dedup:** `GROUP BY route, vehicle_id, pid, sched_start_date, sched_start_sec, vehicle_ts` taking `min(pdist)` (and any lat/lon; identical within group). Use `vehicle_ts`, not poll `ts`.
3. **Trip key** [T0]: `(vehicle_id, pid, sched_start_date, sched_start_sec)`. Never pair across keys.
4. **Trip summary:** `pfirst` = pdist at earliest fix, `pmax` = max pdist.
5. **Pattern inclusion [T7]:** `plen` = p90 over trips of `pmax`, per (route,pid); `rmax` = max `plen` over pids with >= 200 trips; keep pid iff `plen >= 0.5*rmax` and `trips >= 30`.
6. **Layover trim [T1]:** `dep` = first vehicle_ts with pdist > pfirst + 500 (else first fix); `arr` = first vehicle_ts with pdist >= pmax − 500 (else last fix). Keep pairs with `t0 >= dep` and `t1 <= arr`.
7. **Pairs:** consecutive distinct fixes, `dt = (t1−t0)/1000`, `dd = p1−p0`, `crow` = straight-line feet between the two lat/lon points.
8. **Pair filters:** `dt <= 180` [T3]; `dd >= 0` [T4, drop rather than clamp; 0.165% of pairs]; `dd <= 2*crow + 1500` [T5, GPS-geometry check against pdist jumps]; `dd/dt*3600/5280 <= 80` [T6 backstop]. Do **not** use a 50 mph cap on 146/151.
9. **Relief runs [T2]:** within a trip, drop consecutive pairs with |dd| <= 100 ft whose run totals >= 600 s.
10. **Period [T8]:** assign each pair by the **local midpoint** `(t0+t1)/2` in `America/Chicago`. Peak = weekday hours 7, 8, 16, 17; off-peak = weekday hours 10-13. Start-time assignment gives the same numbers to 0.006 mph, so this is a convention rather than a bias issue.
11. **Aggregate:** `Σdd/5280 ÷ (Σdt/3600)` per route and period (space-mean). Also output vehicle-hours, miles, trips, days so the author can set minimum-sample rules.
12. Report side metrics per route: complete-trip share, share of time dropped by gaps, share of pairs removed by geometry filter.

## Sensitivity (weekday daytime 06-19, reference = row 1)

| Variant | All-20 | 9 | 66 | 146 | 3 | 53 | 79 |
|---|---|---|---|---|---|---|---|
| **Recommended (trim 500, dt<=180, geometry, drop neg, relief 600)** | 8.83 | 9.99 | 7.99 | 8.59 | 9.36 | 9.45 | 9.35 |
| No trim, no relief rule | **7.90** | 8.96 | 7.15 | 7.81 | 8.29 | 8.30* | 8.24* |
| Trim 250 | 8.79 | 9.96 | 7.97 | 8.56 | 9.29 | 9.45 | 9.29 |
| Trim 1000 | 8.86 | 10.04 | 7.97 | 8.64 | 9.42 | 9.44 | 9.36 |
| Trim 2000 | 8.86 | 10.01 | 7.92 | 8.70 | 9.46 | 9.36 | 9.35 |
| Cap 50 mph instead of geometry | 8.83 | 10.00 | 7.99 | **8.42** | 9.36 | 9.46 | 9.35 |
| Cap 40 mph | 8.79 | 9.99 | 7.99 | **7.51** | 9.36 | 9.45 | 9.35 |
| Cap 65 mph | 8.84 | 10.00 | 7.99 | 8.60 | 9.36 | 9.46 | 9.35 |
| No speed filter | 8.86 | 10.04 | 8.00 | 8.64 | 9.38 | 9.47 | 9.38 |
| Geometry tight (1.5×crow+1000) | 8.83 | 9.99 | 7.99 | 8.59 | 9.36 | 9.45 | 9.34 |
| Max gap 120 s | 8.84 | 10.01 | 8.00 | 8.58 | 9.37 | 9.48 | 9.36 |
| Max gap 300 s | 8.80 | 9.96 | 7.97 | 8.58 | 9.33 | 9.42 | 9.32 |
| Max gap 600 s | 8.77 | 9.93 | 7.96 | 8.57 | 9.32 | 9.39 | 9.30 |
| No gap rule | 8.76 | 9.92 | 7.95 | 8.56 | 9.31 | 9.37 | 9.28 |
| Negatives clamped to 0 / kept | 8.83 / 8.83 | 9.99 | 7.99 / 7.98 | 8.59 / 8.58 | 9.36 | 9.45 | 9.34 |
| No relief rule | 8.81 | 9.98 | 7.98 | 8.57 | 9.34 | 9.44 | 9.30 |
| Relief rule 300 s | 8.86 | 10.03 | 8.01 | 8.63 | 9.37 | 9.48 | 9.41 |

(*"No trim" for 53 and 79 are taken from the `sens_all.csv` run of the same variant; see that file for all 20 routes.)
Variant rows above (except cap rows, which use the cap-50/40/65 + same trim/gap/relief) all share the other recommended settings.

**Which choices matter:** (1) whether to trim layovers at all (about 12%; far larger than everything else combined); (2) for 146 and 151 only, the form of the speed filter (2-12%); (3) max-gap and relief thresholds (about 1% each); (4) trim distance, negative handling, jump geometry tightness, and period assignment rule (<= 0.5%).

## Caveats

- Everything is inferred from the feed itself; I did not validate against GTFS stop times, scheduled layover, or ground truth.
- The 2 mph level gap to "10-12 mph" is unresolved; I attribute it to definition (see section 8) but did not prove it.
- pdist re-snap artifacts: I showed they are geometry-inconsistent, but the mechanism is unexplained (pattern overlap/loops vs map-matching).
- Route 47 has an unusually large count of geometry-inconsistent pairs (985); not investigated.
- Short-pattern interpretation (connectors) is inferred from vehicle sequencing, not verified.
- 20 service days only; per-route peak/off-peak numbers for thin routes have limited sample (about 900-2,700 trips per cell).
- The weekday-hour breakdown I printed at one point was in UTC and discarded; all reported period numbers use `America/Chicago` local midpoint.

## Files (all under `$S/profiling/speed/`)

`REPORT.md`, `recommended_speed.sql`, `prototype_top20.csv`, `sens_all.csv`, `h.py` (helpers), `p0.py`..`p17.py` (investigation SQL, run with `$S/venv/bin/python -I`; p12 builds the sensitivity table).
