<!-- Profiling report written before the scorecard SQL. Paths like $WORKDIR refer to the analyst's local workspace; the SQL files it cites were exploratory and are not part of the published pipeline. -->

# CTA bus feed integrity report (2026-09-28 to 2026-10-30)

Scope: `positions_raw`, 29,530,887 rows, 1,863 vehicle ids, 125 routes. Top-20 routes = 11,853,731 rows (9,384,845 on weekdays).
Everything below was measured with read-only DuckDB. SQL is in this directory (`00_setup.sql` defines the temp tables `p` and `t20` used by all others; `run.py` runs a file). Local time = `epoch_ms(ts) AT TIME ZONE 'UTC' AT TIME ZONE 'America/Chicago'`.

Schema facts that differ from the brief:
- `archive_date` equals the America/Chicago calendar date of `ts` for all rows (0 mismatches), so it is safe as the local service date.
- `sched_start_date` is formatted `YYYY-MM-DD`, not `YYYYMMDD`. Columns `trip_id`, `direction`, `next_station` are 100% NULL; `approx` is all false; `kind` is all `bus`.
- Exact-duplicate full rows: 0. No NULLs in pid/pdist/vehicle_ts/sched fields.

## Executive summary (ranked by potential to bias peak vs off-peak route speed)

1. **PM peak is entirely missing on Tue Oct 13 to Fri Oct 16** (outages 14:31 / 13:35 / 13:14 / 13:20 local to midnight). AM and part of MID exist, so an unfiltered "peak" for those days is AM-only. MID is also partial (Oct 14 86%, Oct 15 81%, Oct 16 83%). Exclude these four days (and Sat Oct 17, out of scope anyway).
2. **Other partial windows**: Sep 30 MID 91.3%, Oct 21 MID 91.7%, Oct 30 PM 84.2% (gap 17:41-18:07). Smaller AM losses (Oct 27 AM 95.0%). Under a >=95% minute-coverage rule, 8 of 25 weekdays fail or are policy-excluded; 17 remain.
3. **Terminal layovers dominate stationary time.** After dedup, 333,799 stationary runs (>=2 fixes with identical pdist) on top-20 routes; 5-15 min runs at the first/last 500 ft hold ~9,745 h of stationary time (start 3,764 h, end 5,982 h). 11.4% of consecutive-fix pairs have zero movement. Any speed definition that includes them without a layover filter will be biased low, more so off-peak when layovers are longer.
4. **Stuck/repeated fixes**: 80,902 (vehicle_id, vehicle_ts) keys appear in >1 poll, 190,605 redundant rows (0.65% of all rows; 0.86% of in-scope weekday rows), all byte-identical in position/route/pid/trip. Concentrated in a few vehicles (8099, 8643, 4328, 4398, 1452 account for about 35.7k redundant rows). Runs of 10-12 polls (about 10 min frozen) are common (7,871 keys at k=10 or 11). Dedup on (vehicle_id, vehicle_ts) removes them.
5. **Pattern changes mid-month on route 47 (weekday) and route 49**; many weekend-only temporary pids on Oct 10-11 (out of scope). pdist is not comparable across pids; speed must be computed within one trip/pid.
6. **Backward pdist** within one trip: 18,638 pairs (0.16%), 1,429 of them > 1,000 ft; plus 2,105 pairs implying > 60 mph and 17,049 negative-speed pairs. These are outliers needing a plausibility filter, not a systematic bias.
7. **Source staleness is small**: median age 14.7 s, 0.38% of rows > 120 s, 0.175% > 300 s, no negative ages; concentrated in specific vehicles.
8. Oct 12 (Indigenous Peoples' Day) is **not** a feed anomaly (fleet within ~1-4% of other Mondays); only route 9 AM is down (77%). Exclusion is a policy choice.
9. One bus appearing on two routes at the same poll happens only 17 times (terminal turnaround, old trip + new trip). Dedup on (vehicle_id, ts) keeping the later vehicle_ts.

## 1. Coverage by weekday x period x route (`02_coverage.sql`, `03_coverage_route.sql`, `04_route_window.sql`, `18_misc.sql`)

Windows: AM 07:00-09:00 (120 min), MID 10:00-14:00 (240 min), PM 16:00-18:00 (120 min). "Observed" = minutes with at least one record anywhere in the system.

- Polls: 43,950 distinct poll timestamps in 33 days (47,520 minutes), 43,921 distinct minutes. Whole-system polls, not per route (one `ts` holds all routes; 43 to 1,361 rows per poll).
- `coverage_gaps` listing confirmed (local): 09-30 12:44-13:01 (17), 09-30 18:26-19:01 (35), 10-01 01:02-02:36 (94), 10-01 14:41-15:00 (19), 10-12 18:04 to 10-13 00:01 (357), 10-13 14:31 (570), 10-14 13:35 (626), 10-15 13:14 (647), 10-16 13:20 (641), 10-17 15:52 (489), 10-22 15:38-15:48 (10), 10-30 17:41-18:07 (26).
- **Gaps that `coverage_gaps` shows but that I additionally attribute to windows**: Oct 14 12:30-12:38 (8 min, in MID), Oct 21 13:01-13:04 and 13:47-13:50 (3 + 3 min, in MID), and many 1-3 minute holes on Oct 13 (MID 237/240), Oct 26-28 mornings (AM 118/120, 114/120, 115/120).
- **Partial collapse without hitting zero**: for every weekday minute 05:00-22:00 I compared vehicles reporting vs the median for that minute-of-day on 8 clean weekdays. No weekday minute fell below 90% (sum of minutes with ratio <0.9 was <=5 on every weekday, so none printed). The only sub-90% days are weekends, which is a schedule effect. So there are no hidden partial degradations beyond the listed gaps.
- **Individual routes vanishing while others report**: for the 20 routes x 3 windows x 25 weekdays, no route-window had a vehicle-minute count below 60% or above 150% of its median outside the outage windows. All 20 routes have at least one record in every non-outage window. Day-level absent routes among 121 routes with a weekday AM median >= 60 rows: none.
- Route-level AM row counts: Oct 12 route 9 = 77% of other Mondays (route 9 MID and PM rows are also about 15-20% below typical Mondays: 4,855 vs 5,802-5,951 and 2,698 vs 3,280-3,465), route 47 = 111%. Max |deviation| among other top-20 routes on Oct 12 is 8%.

Window coverage failures (weekdays only; everything not listed is 100%):

| date | AM | MID | PM |
|---|---|---|---|
| Wed 09-30 | 97.5 | **91.3** | 100 |
| Thu 10-01 | 98.3 | 100 | 100 |
| Tue 10-13 | 100 | 98.8 | **0** |
| Wed 10-14 | 100 | **86.3** | **0** |
| Thu 10-15 | 100 | **80.8** | **0** |
| Fri 10-16 | 100 | **83.3** | **0** |
| Wed 10-21 | 100 | **91.7** | 100 |
| Mon 10-26 / Tue 10-27 / Wed 10-28 | 98.3 / 95.0 / 95.8 | 100 | 100 |
| Fri 10-30 | 100 | 100 | **84.2** |

Recommended list (rule: all three windows >= 95% minute coverage, plus Oct 12 holiday excluded). Full per-day detail in `day_inclusion.csv`; per-window in `window_inclusion.csv`.
- **Include (17)**: 09-28, 09-29, 10-01, 10-02, 10-05, 10-06, 10-07, 10-08, 10-09, 10-19, 10-20, 10-22, 10-23, 10-26, 10-27, 10-28, 10-29.
- **Exclude (8 weekdays)**: 09-30 (MID 91.3%), 10-12 (holiday, judgment), 10-13, 10-14, 10-15, 10-16 (PM missing), 10-21 (MID 91.7%), 10-30 (PM 84.2%).
- The 95% threshold is a judgment call. Alternative with more data: use `window_inclusion.csv` and compute AM and PM speeds separately, then average them for "peak" (never pool a day that has only AM). That salvages AM/PM on 09-30 and 10-21, AM/MID on 10-30 and AM/MID on 10-13.
- Gaps matter for trips as well: pairs spanning an outage have dt > 180 s and must be dropped by the pair filter (see section 7 rules).

## 2. Poll cadence and staleness (`03_coverage_route.sql`, `04_route_window.sql`, `05_staleness.sql`, `06_repeat.sql`, `07_stuck.sql`)

Poll interval (distinct `ts`, system-wide): median 60.0 s, p1 58.1, p99 61.8; 63 intervals > 90 s, 40 > 120 s, 41 < 30 s. Odd clusters of about 44-45 s (about 120 intervals) and 75-76 s (about 100) plus a few multi-hour holes (the outages). 27 minutes contain two distinct poll timestamps.

Per-vehicle fix spacing (consecutive polls, `vehicle_ts` differences, top-20, ts gap < 120 s, vts increasing): p1 30 s, p5 39, median 60, p95 80, p99 90. So a pair at nominal 60 s often spans 40 to 90 s; speed must divide by actual Δvehicle_ts, not by poll interval.

Source age (`ts - vehicle_ts`), all 29.5M rows:

| stat | value |
|---|---|
| median / p95 / p99 | 14.7 s / 32.1 s / 38.2 s |
| > 60 s / > 120 s / > 300 s | 0.63% / 0.38% / 0.175% |
| negative or zero | 0 / 0 |
| max | 0.2 h |

Age buckets: 0-15 s 50.97%, 15-30 s 39.73%, 30-60 s 8.67%, 60-120 s 0.25%, 120-300 s 0.20%, 300-1800 s 0.18%. In top-20 weekday rows the medians are the same (15.0 s); > 120 s is 0.32%. Stale rows (> 120 s) are concentrated: top vehicle 8099 has 8,348 stale rows of 18,780; 1,747 vehicles have at least one. No single day exceeds 0.51% (Oct 27).

**Repeated vehicle_ts (stuck fixes)**: of 29,340,282 distinct (vehicle_id, vehicle_ts) keys, 80,902 appear in more than one poll; 190,605 redundant rows (0.65%). In all 80,902 groups the rows are identical on lat, lon, pdist, route, pid, sched_start (0 exceptions). Repeat count: k=2 52,698 groups; k=3 11,087; k=10 4,007; k=11 3,864; max 12 (about 11 minutes). A spike at k=10-11 indicates a frozen unit for about 10 minutes rather than random double-polling. By day the worst are Sep 30 (14,300 redundant rows) and Oct 1 (9,483), which are also days with outages; by hour they follow fleet size (peak at 08:00). Reasoning (not measured): without dedup, a stuck bus yields pairs with dt (from `ts`) of 60 s but Δpdist = 0, inflating dwell; if elapsed time is taken from `vehicle_ts` those pairs have dt=0 and drop out, so the risk is mainly when poll `ts` is used for elapsed time. Recommended dedup key: **(vehicle_id, vehicle_ts)**, keep the earliest `ts`.

## 3. Duplicates and conflicts (`08_dups.sql`, `09_conf.sql`)

- Exact duplicate rows: 0.
- Same (vehicle_id, ts) with different content: **17 keys**, every one a bus reporting two different routes/patterns in the same poll (two rows, route and pid and pdist differ, vts differ by 3 to 32 s). Pattern: one row is the trip just finished (pdist near end, older vts), the other is the next trip (pdist 0 or small, newer vts). Examples: vehicle 8922 on 49 (pdist 83,417) and X49 (pdist 0) at 2026-09-28 15:41:04; vehicle 8102 on X9/9 on Oct 6; vehicle 1333 on 3 and X4 on Oct 19. Positions in the listed examples differ by well under 100 m.
- Vehicle in more than one row within the same minute: 20,531 vehicle-minutes have 2 rows and 1,814 have 3 (poll jitter; distinct vts, benign).
- Route switches for the same vehicle between consecutive polls: 79,266 (6,428 within 2 min), mostly legitimate interlining or express/local pairs (9 and X9, 49 and X49, 63W and 165). A vehicle id serves up to 21 different routes in 33 days (e.g. 8488), so the route must come from the row, not the vehicle.
- 7 three-digit vehicle ids (608, 609, 610, 612, 615, 621, 622; 36,486 rows) report on routes 55, 63, 65 at fixed latitudes (41.78-41.92); not distinguishable as non-revenue from this table. 622 is on route 63 for 1,902 rows (Sep 28 to Oct 5).

## 4. Day-of-week, holiday and event effects (`10_dow.sql`, `11_r9.sql`)

Average concurrent vehicles per minute:

| date | AM | MID (10-13) | PM |
|---|---|---|---|
| typical Mon (09-28, 10-05, 10-19, 10-26) | 1,207 / 1,222 / 1,193 / 1,220 | 861 / 873 / 875 / 877 | 1,286 / 1,311 / 1,291 / 1,313 |
| **Mon 10-12** | 1,203 | 842 | 1,272 |
| Sat (typical) | about 530-545 | about 790 | about 845 |
| Sun (typical) | about 410-430 | about 625-663 | about 660-708 |

- Oct 12: fleet is 0.6% below the mean of the four other Mondays in AM, 3.4% in MID and 2.2% in PM. System-wide AM vehicle-minutes: 144,304 vs 143,189-146,686 for other Mondays, i.e. inside normal Monday variation. Route-level AM on Oct 12: route 9 -23%, routes 72 and 49 -8%, all else within 5% (route 47 +11%). Among all 121 routes with a weekday AM median >= 60 rows, only two route-days fall below 50% of normal: route 206 on Oct 12 (47%) and route 124 on Oct 20 (45%). Neither is top-20.
- Route 9 on Oct 12 (AM 2,193 rows vs 2,600-2,977 typical) is the only top-20 route clearly different. The feed does not say why.
- Daily route count is 124-125 on every weekday, 87-95 on weekends. Fleet size per weekday is 1,491-1,631 distinct vehicles/day, except the outage days.
- Weekend notes (out of scope): Sat 1,148-1,223 vehicles, Sun 1,011-1,046; Sat Oct 17 truncated at 15:52; the weekend of Oct 10-11 has many temporary 502xxx pids (below).
- I cannot determine from this feed whether the Oct 12 holiday changed traffic or speeds; including or excluding it is a policy call. I recommend excluding it as the conservative choice and running it as a sensitivity.

## 5. Route and pattern identity (`12_pids.sql`, `13_r47.sql`, `19_scale.sql`, `20_rules.sql`)

Top-20 routes have 275 distinct pids in total (201 on weekdays). A pid belongs to exactly one route (0 pids shared). `destination` is constant within every pid (0 of 275 pids have more than one destination), so destination can serve as direction label.

- Weekday pid shares (within route): 75 of 201 pids hold < 1% of their route's rows (1.42% of rows), 115 < 2% (4.51%), 144 < 5% (8.51%).
- Short patterns are real service, not noise: e.g. route 79 pid 1628 (7.2% of rows, max pdist 38,816 ft vs modal 60,304), route 77 pid 7560 (7.0%), route 53 pid 28354 (2.9%). 5.17% of weekday rows are in pids shorter than 70% of the route's modal pattern. Dropping them on share would remove legitimate short-turn trips.
- **Route 47 pattern id change**: pids 6126/6128 (about 25% and 28% of rows each, max pdist 53,592 / 54,091 ft) carry all traffic through Fri Oct 16; pids 502453/502450 (58,878 / 59,359 ft) replace them starting at the very end of Oct 16 (70 rows on 10-16, 6,965 on Sat 10-17) and carry 22% and 21% of rows. Terminals are unchanged (Lake Park 41.809,-87.592; Midway 41.786,-87.739). Pattern length +5,300 to +5,800 ft (+10%). I checked that haversine distance over pdist distance per pid is 0.968 (old) vs 0.963 (new), so pdist scale is consistent and speeds within a pid are comparable; the cause of the longer pattern is not in the data. The 502xxx short and branch variants (2402/2404/6125/6127 to 502451/502452/502454/502455) change at the same time.
- **Route 49 new pids from Oct 19**: 502438/502439 (Oct 19 to 20) then 502456/502457 (Oct 20 to 30) at 89,258-89,315 ft vs 83,478 (1180) / 83,922 (1178, 9379). These are 79th-bound only; 1180/1178 continue through Oct 30. Combined new-pid share is 5.6% of route 49 weekday rows. Geometry ratio 0.981-0.990 (consistent with old pids at 0.991-0.994).
- **Weekend-only pids**: temp 5020xx to 5024xx pids appear for most top-20 routes only on Sat Oct 10 and Sun Oct 11 (for example route 146 has 13 new pids). Apart from routes 47 and 49, no top-20 pid with 500+ weekday rows starts or stops mid-month (route 82 pid 5364, 930 rows on 5 weekdays, last seen Oct 26, is the only one that stops). The coincidence with Oct 10-11 is noted but I did not verify the cause.
- Pids seen on exactly 7 days between Oct 3 and Oct 25 are weekend patterns (pids 1054, 96, 1514, 1523, 9370, 29290, 5901, 10940, 28325, 30405) and have no weekday impact.
- pdist is referenced to each pid, so the same physical point has different pdist in different pids; never difference pdist across a pid change (this occurs for 216 of 164,165 trips, below).
- Note: pids 502456/502458 also appear in the 17 same-poll conflicts above, i.e. the new patterns are used at terminal changeover.

## 6. Time-field sanity and trip identity (`14_time.sql`, `15_trips.sql`)

- `vehicle_ts` after `ts`: 0 rows. Negative or zero source age: 0.
- Consecutive same-vehicle fixes (top-20, 11.85M pairs): 66,641 have equal vts (stuck fixes); **118 go backward** (down to -45 s; examples include double polls 1 s apart on Oct 1 and Oct 13 and a 173 s poll gap on Oct 27); 19,962 move ahead by more than the poll interval + 60 s.
- Within a trip (same vehicle, pid, sched_start), **pdist decreases between successive fixes in 18,638 of 11.62M pairs (0.16%)**: 8,936 by > 100 ft and 1,429 by > 1,000 ft.
- Naive pair speeds (pairs with 20 s <= dvts <= 180 s, same trip, top-20, n = 11,577,677): median 8.1 mph, p95 20.4, p99 26.8, p99.9 42.0; zero movement 11.4% (1,325,370); negative 17,049; > 60 mph 2,105; > 80 mph 1,568. For dvts 20-40 s the mean is 9.72 mph and 12.8% are exactly zero, vs 8.64 mph at 40-70 s, so very short intervals are noisier (pdist is integer feet and vts is integer seconds). I did not compute the scorecard; these are plausibility numbers only.
- `sched_start_sec` range 10,710 to 97,440; 353,797 top-20 rows (3.0%) have > 86,400 (post-midnight trips of the previous service day) and 499,550 rows (4.2%) have `sched_start_date` different from the poll date. So the service date must come from `sched_start_date`, not `archive_date`, for after-midnight trips. `sched_start_date` has 34 values (2026-09-27 to 2026-10-30).
- **Trip key**: (vehicle_id, pid, sched_start_date, sched_start_sec) yields 164,381 trips on top-20 routes (all days). Median span 73.8 min, p99 138 min. 9 trips exceed 4 h (the longest 7.26 h: vehicle 8540, route 3, 4 fixes across a garage period on Oct 6), 45 exceed 3 h. 1,484 trips have fewer than 3 fixes, 2,184 fewer than 5. 1,660 keys (1.0%) contain a gap > 30 min between consecutive fixes, 7,403 > 10 min, 17,434 > 5 min. Dropping `pid` from the key gives 164,165 trips; only 216 span more than one pid and 1 spans two routes, so `pid` in the key is correct and costs little.
- (pid, sched_start_date, sched_start_sec) without `vehicle_id` is shared by more than one vehicle in 2,348 of 161,945 cases (1.4%); vehicle_id must stay in the key.
- Trips per route per clean weekday (mean; min-max): 79: 438 (328-453), 66: 427, 53: 330, 20: 329, 9: 327, 77: 321, 72: 289, 63: 281, 82: 270, 49: 259, 8: 260, 4: 245, 12: 244, 60: 244, 3: 239, 47: 235, 22: 232, 146: 216, 151: 207, 36: 163. The minimum column reflects partial days (Oct 13-16 are excluded from this table; the cause of the remaining low days was not checked), so use the mean over included days.

## 7. Other bias sources (`16_geo.sql`, `17_dwell.sql`, `19_scale.sql`)

- Coordinates: all rows are in lat 41.644-42.066, lon -87.887 to -87.525; 0 rows at (0,0), 0 outside a 41.60-42.10 / -88.00 to -87.50 box. pdist: no negatives or NULLs; 1,282,783 rows (4.3%) at exactly pdist 0 (trip starts and layover). Max pdist 103,980 ft.
- pdist scale check: sum of haversine step lengths / sum of positive Δpdist is 0.979 overall (p1 0.68, median 1.00, p99 1.04) and 0.954-0.995 per pid for all pids with > 20,000 pairs, so pdist is consistent with road geometry (pdist is slightly longer than the straight chord, as expected).
- **Stationary runs** (fixes with identical pdist, within one trip, after dedup on vehicle_ts; top-20; counts of runs / hours):

| location | 2-5 min | 5-15 min | 15-60 min | > 60 min |
|---|---|---|---|---|
| first 500 ft of pid | 37,188 / 1,701 h | 26,520 / 3,764 h | 4,439 / 1,491 h | 39 / 55 h |
| last 500 ft of pid | 24,548 / 1,290 h | 42,609 / 5,982 h | 5,722 / 1,961 h | 55 / 77 h |
| mid-route | 29,719 / 1,378 h | 11,326 / 1,509 h | 3,029 / 1,219 h | 158 / 212 h |

  30,623 of 36,545 runs of at least 10 min are at a terminal (84%); 5,922 are mid-route. Mid-route long stops (> 60 min, 158 runs) are probably breakdowns or buses parked while still logged on a trip; for example vehicle 8540 on route 3 sat at pdist 577 for 7.3 h on Oct 6 (a garage pull-in, 4 fixes only). Terminal runs are layovers (scheduled recovery time), so `Δpdist/Δt` over them is not travel speed.
- Pair speed bias risk: plain mean of per-pair mph weights short intervals equally; use sum(Δpdist)/sum(Δvts) per route-period.

## Recommended handling rules (testable)

Window definitions: AM 07:00 <= t < 09:00, MID 10:00 <= t < 14:00, PM 16:00 <= t < 18:00, `lts` local, weekdays Mon-Fri only.

1. **Day inclusion**: use `day_inclusion.csv` (`include_in_scorecard = true` gives 17 days). Equivalent rule: window minute coverage >= 95% for AM, MID and PM, minus 2026-10-12. Test: `SELECT count(*) FROM day_inclusion WHERE include_in_scorecard` = 17.
2. **Do not compute peak from a day lacking PM or AM.** If the day-level rule is relaxed, compute AM and PM speeds separately and average them equally. Never pool AM-only days into peak. For 2026-10-13 to 10-16 PM is 0%.
3. **Dedup**: keep one row per (vehicle_id, vehicle_ts), earliest `ts`. Expect to drop 190,605 of 29,530,887 rows (0.645%).
4. **Same-poll conflicts**: keep one row per (vehicle_id, ts), the one with the larger `vehicle_ts` (17 keys in total; these are old-trip/new-trip changeover rows).
5. **Trip key**: (vehicle_id, pid, sched_start_date, sched_start_sec). Compute pair speeds only between consecutive fixes inside one trip key. Use `sched_start_date` (format `YYYY-MM-DD`), not `archive_date`, for service date. Do not difference pdist across pids.
6. **Pair filter**: consecutive deduped fixes with 20 s <= Δvehicle_ts <= 180 s (drops outage-spanning pairs and the noisiest short intervals); Δpdist >= 0 (drop the 0.16% backward pairs); implied speed <= 60 mph (drops 2,105 pairs). Elapsed time must be Δvehicle_ts, never Δts. Aggregate as sum(Δpdist)/sum(Δvehicle_ts).
7. **Layover exclusion**: exclude any pair that lies in a run of identical pdist (after dedup) that starts at pdist <= 500 ft or ends within 500 ft of the pid's max pdist, and exclude all fixes with pdist <= 500 ft or >= maxpd - 500 ft. Evidence: 84% of runs of 10 minutes or more are at a terminal.
8. **Trip sanity**: drop trips with span > 4 h (9 trips), fewer than 3 fixes (1,484), or any internal gap > 30 min (1,660 keys; or split at the gap).
9. **Staleness**: optionally drop rows with `ts - vehicle_ts` > 120 s (0.38%) -- they are concentrated in about a dozen vehicles; this matters less once rule 3 and the 20-180 s pair filter are applied.
10. **Patterns**: keep all pids with weekday rows; do not drop short-turn pids on share (they are real service). If a route-level filter is wanted, drop only pids with < 1% of the route's weekday rows (1.42% of rows). Do not mix pids when comparing pdist; for route 47 (pid change 10-16 to 10-17) and route 49 (new pids from 10-19) run a before/after sensitivity.
11. **Geography**: no coordinate filter is needed (0 out-of-bounds, 0 zero-coordinate rows).
12. **Route identity**: take route from the row, not from vehicle_id (one vehicle id served up to 21 routes).

## Caveats and what I did not do
- I did not compute scorecard speeds; the speed percentiles above are plausibility numbers from naive pair differencing.
- Causes (detours, events, pick changes) are not in the data; where I mention a date coincidence it is flagged as unverified.
- The 95% coverage threshold, 500 ft terminal band, 20-180 s pair window and 60 mph cap are my choices, not derived from a ground truth.
- Coverage is measured as "any record in that minute"; per-route per-minute coverage is only checked through vehicle-minute totals.
- Disk was nearly full during the session (about 0.8 GB free at the end); one early query failed on a temp-file write and was rerun with a leaner form. My own temp directory was empty.
