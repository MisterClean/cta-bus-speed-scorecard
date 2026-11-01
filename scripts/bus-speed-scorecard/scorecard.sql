-- CTA bus speed scorecard: operating (commercial) speed from Bus Tracker positions.
-- DuckDB 2.x. Run through build.py, which opens the archive database READ-ONLY and first creates
--   scope_days(service_day DATE)   the weekdays included in the scorecard (see build.py / README)
--   scope_routes(route VARCHAR)    the routes processed in this batch (routes are independent)
-- Every table below is TEMP, so nothing is written to the archive database.
--
-- Speed definition (operating or "commercial" speed, stops included): distance along the route pattern
-- (pdist, feet) / GPS-fix elapsed time (vehicle_ts), including time at bus stops and traffic signals,
-- excluding terminal layovers, long gaps and mid-route stand-stills of 10+ minutes. Pairs are summed as
-- sum(feet) / sum(seconds) (space-mean speed); build.py then weights ~220 m cells identically across periods.
-- Thresholds are tagged [T1]..[T8] and documented in docs/bus-speed-scorecard.md.

-- 0. Scope: weekday service days chosen in build.py. Every route is kept for system context.
CREATE OR REPLACE TEMP TABLE b AS
SELECT route, vehicle_id vid, pid, sched_start_date ssd, sched_start_sec sss,
       vehicle_ts vts, ts, pdist, lat, lon, destination
FROM positions_raw
WHERE kind = 'bus' AND archive_date IN (SELECT service_day FROM scope_days)
  AND route IN (SELECT route FROM scope_routes);

-- 1. Fix dedup. A bus whose GPS fix is frozen repeats the same vehicle_ts on later polls with
--    identical position (190,605 such rows across the archive). Keep one row per trip key and fix time.
CREATE OR REPLACE TEMP TABLE f AS
SELECT route, vid, pid, ssd, sss, vts, min(pdist) pdist, any_value(lat) lat, any_value(lon) lon
FROM b GROUP BY route, vid, pid, ssd, sss, vts;

-- 2. Trip key = (vehicle, pattern, scheduled service date, scheduled start second) [T0].
--    pdist is measured along one pattern, so pairs are never formed across a key change.
CREATE OR REPLACE TEMP TABLE tr AS
SELECT route, vid, pid, ssd, sss, arg_min(pdist, vts) pfirst, max(pdist) pmax,
       min(vts) tmin, max(vts) tmax, count(*) fixes
FROM f GROUP BY route, vid, pid, ssd, sss;

-- 3. Pattern inclusion [T7]. Pattern length = p90 of per-trip max pdist. Drop short connector or
--    pull-in patterns (< 50% of the route's longest well-populated pattern) and rare patterns (< 30 trips).
CREATE OR REPLACE TEMP TABLE ptn AS
WITH p AS (SELECT route, pid, count(*) ntr, quantile_cont(pmax, 0.9) plen FROM tr GROUP BY route, pid),
     r AS (SELECT route, coalesce(max(plen) FILTER (WHERE ntr >= 200), max(plen)) rmax FROM p GROUP BY route)
SELECT p.*, r.rmax, (p.plen >= 0.5 * r.rmax AND p.ntr >= 30) incl FROM p JOIN r USING (route);

-- 4. Terminal layover trim [T1]: measure each trip from the first fix more than 500 ft past its
--    starting point to the first fix within 500 ft of its furthest point.
CREATE OR REPLACE TEMP TABLE win AS
SELECT t.route, t.vid, t.pid, t.ssd, t.sss,
       coalesce(min(f.vts) FILTER (WHERE f.pdist > t.pfirst + 500), min(f.vts)) dep,
       coalesce(min(f.vts) FILTER (WHERE f.pdist >= t.pmax - 500), max(f.vts)) arr
FROM tr t JOIN f USING (route, vid, pid, ssd, sss)
GROUP BY ALL;

-- 5. Consecutive-fix pairs within a trip, with the straight-line distance between the two GPS points.
CREATE OR REPLACE TEMP TABLE pr AS
SELECT route, vid, pid, ssd, sss,
       lag(vts) OVER w t0, vts t1, lag(pdist) OVER w p0, pdist p1,
       lag(lat) OVER w lat0, lat lat1, lag(lon) OVER w lon0, lon lon1,
       (vts - lag(vts) OVER w) / 1000.0 dt,
       pdist - lag(pdist) OVER w dd,
       3.28084 * 111320 * sqrt(power(lat - lag(lat) OVER w, 2)
            + power(cos(radians(lat)) * (lon - lag(lon) OVER w), 2)) crow
FROM f WINDOW w AS (PARTITION BY route, vid, pid, ssd, sss ORDER BY vts);

-- 6. Flag every pair with the reason it would be excluded (flags overlap; used for the QA funnel).
CREATE OR REPLACE TEMP TABLE prf AS
SELECT p.*, n.incl pattern_ok,
       (p.t0 >= w.dep AND p.t1 <= w.arr) in_window,          -- [T1] layover trim
       p.dt <= 180 gap_ok,                                    -- [T3] do not bridge gaps > 180 s
       p.dd >= 0 forward_ok,                                  -- [T4] drop the 0.16% backward snaps
       p.dd <= 2 * p.crow + 1500 geometry_ok,                 -- [T5] pdist jump must be supported by GPS
       (p.dd / p.dt) * 3600 / 5280 <= 80 speed_ok             -- [T6] absolute backstop, mph
FROM pr p
JOIN win w USING (route, vid, pid, ssd, sss)
JOIN ptn n USING (route, pid)
WHERE p.t0 IS NOT NULL;

CREATE OR REPLACE TEMP TABLE kp0 AS
SELECT *, sum(CASE WHEN abs(dd) <= 100 THEN 0 ELSE 1 END)
            OVER (PARTITION BY route, vid, pid, ssd, sss ORDER BY t1 ROWS UNBOUNDED PRECEDING) grp
FROM prf
WHERE pattern_ok AND in_window AND gap_ok AND forward_ok AND geometry_ok AND speed_ok;

-- 7. Mid-route stand-stills [T2]: drop runs of pairs moving <= 100 ft that total >= 600 s
--    (breakdowns, holds, buses parked while still logged in). Ordinary stop and signal dwell stays.
CREATE OR REPLACE TEMP TABLE standstill AS
SELECT route, vid, pid, ssd, sss, grp FROM kp0 WHERE abs(dd) <= 100
GROUP BY ALL HAVING sum(dt) >= 600;

CREATE OR REPLACE TEMP TABLE kp AS
SELECT k.*,
       timezone('America/Chicago', to_timestamp((k.t0 + k.t1) / 2000.0)) lm   -- local midpoint [T8]
FROM kp0 k
ANTI JOIN standstill s
  ON s.route = k.route AND s.vid = k.vid AND s.pid = k.pid AND s.ssd = k.ssd AND s.sss = k.sss
 AND s.grp = k.grp AND abs(k.dd) <= 100;

-- 8. Outputs ----------------------------------------------------------------------------------------
-- 8a. Route x service day x local hour sums. Every period, hourly, daily and bootstrap figure is
--     derived from this table in build.py, so all charts share one computation.
CREATE OR REPLACE TEMP TABLE out_route_day_hour AS
SELECT route, CAST(lm AS DATE) service_day, hour(lm) hr,
       sum(dd) feet, sum(dt) AS seconds, count(*) pairs,
       count(DISTINCT (vid, pid, ssd, sss)) trips
FROM kp
WHERE CAST(lm AS DATE) IN (SELECT service_day FROM scope_days)
GROUP BY ALL;

-- 8b. ~220 m GPS-midpoint cells by route, service day and period. Used for the map and for
--     fixed-segment route speeds (the same cells, with the same distance weights, in every period).
CREATE OR REPLACE TEMP TABLE out_cells AS
SELECT route, CAST(lm AS DATE) service_day,
       round((lat0 + lat1) / 2 / 0.002) * 0.002 cell_lat,
       round((lon0 + lon1) / 2 / 0.0027) * 0.0027 cell_lon,
       CASE WHEN hour(lm) IN (7, 8) THEN 'am' WHEN hour(lm) IN (16, 17) THEN 'pm'
            WHEN hour(lm) BETWEEN 10 AND 13 THEN 'mid' END period,
       sum(dd) feet, sum(dt) AS seconds, count(*) pairs
FROM kp
WHERE CAST(lm AS DATE) IN (SELECT service_day FROM scope_days)
  AND (hour(lm) IN (7, 8, 16, 17) OR hour(lm) BETWEEN 10 AND 13)
GROUP BY ALL;

-- 8c. Patterns: inclusion decisions and lengths (used for end-to-end ride times).
CREATE OR REPLACE TEMP TABLE pdest AS SELECT pid, arg_max(destination, n) destination FROM (SELECT pid, destination, count(*) n FROM b GROUP BY ALL) GROUP BY pid;
CREATE OR REPLACE TEMP TABLE out_patterns AS
SELECT p.route, p.pid, any_value(d.destination) destination, p.ntr trips, round(p.plen) length_ft,
       round(p.rmax) route_max_ft, p.incl included,
       any_value(f.lat ORDER BY f.pdist, f.vts, f.vid) start_lat, any_value(f.lon ORDER BY f.pdist, f.vts, f.vid) start_lon,
       any_value(f.lat ORDER BY f.pdist DESC, f.vts, f.vid) end_lat, any_value(f.lon ORDER BY f.pdist DESC, f.vts, f.vid) end_lon
FROM ptn p JOIN f USING (route, pid) LEFT JOIN pdest d USING (pid)
GROUP BY p.route, p.pid, p.ntr, p.plen, p.rmax, p.incl;

-- 8e. Quarter-mile bins along each pattern (by pair midpoint pdist), for "slowest stretch" by route.
CREATE OR REPLACE TEMP TABLE out_bins AS
SELECT route, pid, CAST(floor((p0 + p1) / 2 / 1320) AS INTEGER) bin,
       CASE WHEN hour(lm) IN (7, 8) THEN 'am' WHEN hour(lm) IN (16, 17) THEN 'pm'
            WHEN hour(lm) BETWEEN 10 AND 13 THEN 'mid' END period,
       sum(dd) feet, sum(dt) AS seconds, count(*) pairs,
       avg((lat0 + lat1) / 2) lat, avg((lon0 + lon1) / 2) lon
FROM kp
WHERE CAST(lm AS DATE) IN (SELECT service_day FROM scope_days)
  AND (hour(lm) IN (7, 8, 16, 17) OR hour(lm) BETWEEN 10 AND 13)
GROUP BY ALL;

-- 8d. QA funnel: how much each rule removes, per route (flags overlap, so they are not additive).
CREATE OR REPLACE TEMP TABLE out_qa AS
WITH raw AS (SELECT route, count(*) raw_rows FROM b GROUP BY route),
     dd AS (SELECT route, count(*) dedup_fixes FROM f GROUP BY route),
     trips AS (SELECT route, count(*) trips FROM tr GROUP BY route),
     pf AS (
       SELECT route, count(*) pairs, sum(dt) pair_seconds,
              count(*) FILTER (WHERE NOT pattern_ok) pairs_short_pattern,
              count(*) FILTER (WHERE NOT in_window) pairs_layover,
              sum(dt) FILTER (WHERE NOT in_window) seconds_layover,
              count(*) FILTER (WHERE NOT gap_ok) pairs_long_gap,
              sum(dt) FILTER (WHERE NOT gap_ok) seconds_long_gap,
              count(*) FILTER (WHERE NOT forward_ok) pairs_backward,
              count(*) FILTER (WHERE NOT geometry_ok) pairs_geometry,
              count(*) FILTER (WHERE NOT speed_ok) pairs_over_80mph
       FROM prf GROUP BY route),
     k0 AS (SELECT route, count(*) pairs_after_filters FROM kp0 GROUP BY route),
     k AS (SELECT route, count(*) pairs_kept, sum(dt) seconds_kept, sum(dd) feet_kept FROM kp GROUP BY route)
SELECT * FROM raw JOIN dd USING (route) JOIN trips USING (route) JOIN pf USING (route)
JOIN k0 USING (route) JOIN k USING (route);
