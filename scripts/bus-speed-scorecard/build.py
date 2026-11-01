#!/usr/bin/env python3
"""Build the CTA bus speed scorecard from a chicago-transit-duckdb archive database.

Usage:
  python -I scripts/bus-speed-scorecard/build.py --db /path/to/transit.duckdb \
      --ridership /path/to/bus_daily.csv --out data/bus-speed-scorecard

The archive database is opened read-only. See scripts/bus-speed-scorecard/README.md.
Requires duckdb 2.x, pandas and numpy.
"""
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import subprocess

import duckdb
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
SQL = HERE / 'scorecard.sql'
RIDERSHIP_URL = ('https://data.cityofchicago.org/resource/jyb9-n7fm.csv?$where=date%20between%20'
                 "'2025-09-01T00:00:00'%20and%20'2026-08-31T00:00:00'&$limit=500000&$order=date,route")

# Weekdays removed from the scorecard (America/Chicago calendar dates).
# Oct 13-16: the collector lost every afternoon from about 13:15-14:30 to midnight, so the PM rush
# is missing entirely and midday is partial. Keeping their AM data would tilt "rush hour" toward mornings.
# Oct 12: Indigenous Peoples' Day. The feed is complete, but schools are closed, which changes traffic.
EXCLUDED_DAYS = {
    '2026-10-12': "Indigenous Peoples' Day (CPS closed); excluded as a holiday, tested as a sensitivity",
    '2026-10-13': 'Collector outage 14:31 to midnight: PM rush missing',
    '2026-10-14': 'Collector outage 13:35 to midnight: PM rush missing, midday 86% covered',
    '2026-10-15': 'Collector outage 13:14 to midnight: PM rush missing, midday 81% covered',
    '2026-10-16': 'Collector outage 13:20 to midnight: PM rush missing, midday 83% covered',
}
# Stricter alternative from the feed audit: also drop days where any window had < 95% minute coverage.
STRICT_EXTRA = ['2026-09-30', '2026-10-21', '2026-10-30']

PERIODS = {'am': [7, 8], 'mid': [10, 11, 12, 13], 'pm': [16, 17], 'peak': [7, 8, 16, 17]}
EXPRESS_PAIRS = [('X9', '9'), ('X49', '49'), ('X4', '4')]
# Express and Lake Shore Drive express routes: excluded from the "other routes" comparison (146 is in the top 20).
EXPRESS_ROUTES = {'X4', 'X9', 'X49', 'J14', '2', '6', '26', '134', '135', '136', '143', '146', '147', '148', '192'}
# Known reroutes seen in the positions (route, street the stretch runs on) -> note shown with the stretch.
STRETCH_NOTES = {('8', 'Division'): 'detour around Halsted St'}
MIN_CELL_PAIRS = 20    # a cell joins a route's fixed segment set only with >= 20 pairs in each of AM, midday and PM
MIN_ROUTE_VH = 100     # a route joins network comparisons only with >= 100 vehicle-hours in each period
# Map regions as [lat_min, lat_max, lon_min, lon_max] on the ~220 m cell grid.
REGION_LOOP = [41.8745, 41.8865, -87.6375, -87.6235]   # Lake St to Congress, Wacker to Michigan
REGION_LSD = [41.903, 41.937, -87.637, -87.60]          # route 146 on Lake Shore Drive, Division to Belmont
FT_PER_MILE = 5280.0


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def mph(feet, seconds):
    return (feet / FT_PER_MILE) / (seconds / 3600.0) if seconds else None


def archive_weekdays(con):
    days = [r[0] for r in con.execute(
        "SELECT archive_date FROM archive_ingest WHERE kind='bus' ORDER BY 1").fetchall()]
    return [d for d in days if d.isoweekday() <= 5]


OUTPUTS = ['out_route_day_hour', 'out_cells', 'out_patterns', 'out_qa', 'out_bins']


def run_pipeline(con, days, routes=None, batch_rows=4_000_000):
    """Run scorecard.sql for the given service days, in batches of routes to bound memory."""
    con.execute('CREATE OR REPLACE TEMP TABLE scope_days(service_day DATE)')
    con.executemany('INSERT INTO scope_days VALUES (?)', [[d] for d in days])
    sizes = con.execute("""SELECT route, count(*) n FROM positions_raw
        WHERE kind='bus' AND archive_date IN (SELECT service_day FROM scope_days)
        GROUP BY route ORDER BY n DESC""").fetchall()
    if routes is not None:
        sizes = [x for x in sizes if x[0] in set(routes)]
    batches, cur, n = [], [], 0
    for route, rows in sizes:
        if cur and n + rows > batch_rows:
            batches.append(cur); cur, n = [], 0
        cur.append(route); n += rows
    if cur:
        batches.append(cur)
    # Strip "--" comments (the SQL has no string literals containing "--"), then split statements.
    code = '\n'.join(line.split('--', 1)[0] for line in SQL.read_text().splitlines())
    stmts = [s.strip() for s in code.split(';') if s.strip()]
    parts = {name: [] for name in OUTPUTS}
    for batch in batches:
        con.execute('CREATE OR REPLACE TEMP TABLE scope_routes(route VARCHAR)')
        con.executemany('INSERT INTO scope_routes VALUES (?)', [[r] for r in batch])
        for stmt in stmts:
            con.execute(stmt)
        for name in OUTPUTS:
            parts[name].append(con.execute(f'SELECT * FROM {name}').df())
        for t in ['b', 'f', 'tr', 'ptn', 'win', 'pr', 'prf', 'kp0', 'standstill', 'kp', 'pdest'] + OUTPUTS:
            con.execute(f'DROP TABLE IF EXISTS {t}')
    return {name: pd.concat(v, ignore_index=True) for name, v in parts.items()}


def period_frame(rdh):
    rows = []
    for per, hours in PERIODS.items():
        sub = rdh[rdh.hr.isin(hours)]
        g = sub.groupby('route').agg(feet=('feet', 'sum'), seconds=('seconds', 'sum'),
                                     pairs=('pairs', 'sum'), days=('service_day', 'nunique'))
        g['period'] = per
        rows.append(g.reset_index())
    out = pd.concat(rows)
    out['mph'] = out.feet / FT_PER_MILE / (out.seconds / 3600)
    out['vehicle_hours'] = out.seconds / 3600
    return out


# Chicago address grid. North of Madison and south of Pershing it runs 800 address units per mile; between
# them it is irregular (Roosevelt = 1200 S is one mile south of Madison), so latitude is mapped piecewise.
GRID_LON0, MI_LAT, MI_LON = -87.6277, 0.014492, 0.01963
LAT_ANCHORS = [(41.8238, -3900), (41.8383, -3100), (41.8527, -2200), (41.8674, -1200), (41.8819, 0)]
NS_STREETS = {-11500: '115th', -11100: '111th', -10700: '107th', -10300: '103rd', -9900: '99th', -9500: '95th',
              -9100: '91st', -8700: '87th', -8300: '83rd', -7900: '79th', -7500: '75th', -7100: '71st',
              -6700: '67th', -6300: '63rd', -5900: '59th', -5500: 'Garfield', -5100: '51st', -4700: '47th',
              -4300: '43rd', -3900: 'Pershing', -3500: '35th', -3100: '31st', -2600: '26th', -2200: 'Cermak',
              -1600: '16th', -1200: 'Roosevelt', -800: 'Polk', -500: 'Congress', 0: 'Madison', 400: 'Kinzie', 800: 'Chicago',
              1200: 'Division', 1600: 'North', 2000: 'Armitage', 2400: 'Fullerton', 2800: 'Diversey',
              3200: 'Belmont', 3600: 'Addison', 4000: 'Irving Park', 4400: 'Montrose', 4800: 'Lawrence',
              5200: 'Foster', 5600: 'Bryn Mawr', 6000: 'Peterson', 6400: 'Devon', 6800: 'Pratt', 7200: 'Touhy',
              7600: 'Howard'}
EW_STREETS = {-7200: 'Harlem', -6400: 'Narragansett', -6000: 'Austin', -5600: 'Central', -5200: 'Laramie',
              -4800: 'Cicero', -4400: 'Kostner', -4000: 'Pulaski', -3600: 'Central Park', -3200: 'Kedzie',
              -2800: 'California', -2400: 'Western', -2000: 'Damen', -1600: 'Ashland', -1200: 'Racine',
              -800: 'Halsted', -400: 'Clinton', 0: 'State', 100: 'Michigan', 400: 'King Dr', 800: 'Cottage Grove',
              1600: 'Stony Island', 2000: 'Jeffery'}


def grid_address(lat, lon):
    lo, hi = LAT_ANCHORS[0], LAT_ANCHORS[-1]
    if lat >= hi[0]:
        ns = (lat - hi[0]) / MI_LAT * 800
    elif lat <= lo[0]:
        ns = lo[1] + (lat - lo[0]) / MI_LAT * 800
    else:
        for (y0, a0), (y1, a1) in zip(LAT_ANCHORS, LAT_ANCHORS[1:]):
            if y0 <= lat <= y1:
                ns = a0 + (lat - y0) / (y1 - y0) * (a1 - a0)
                break
    return ns, (lon - GRID_LON0) / MI_LON * 800


def nearest_street(addr, streets, tol=260):
    k = min(streets, key=lambda s: abs(s - addr))
    if abs(k - addr) <= tol:
        return streets[k]
    return f"{abs(addr) / 100:.0f}00 {'N' if streets is NS_STREETS and addr >= 0 else 'S' if streets is NS_STREETS else 'E' if addr >= 0 else 'W'}"


def describe_stretch(a, b, street=None, axis=None):
    """Name a stretch between two lat/lon points with Chicago grid streets: '<on street>, <cross> to <cross>'."""
    (na, ea), (nb, eb) = grid_address(*a), grid_address(*b)
    clat, clon = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
    if 41.872 <= clat <= 41.897 and -87.645 <= clon <= -87.615:
        return 'Downtown (Loop / River North)'
    moving = 'NS' if abs(na - nb) >= abs(ea - eb) else 'EW'
    if street == 'Kimball/Homan':
        street = 'Kimball' if clat > 41.91 else 'Homan'     # the 82 is Kimball north of North Ave, Homan south
    if 41.85 <= clat <= 41.91 and clon >= -87.66:
        street = None    # near downtown, routes leave their namesake street (e.g. 151 and 146 on Michigan Ave)
    if moving == 'NS':     # cross streets run east-west
        c1, c2 = nearest_street(min(na, nb), NS_STREETS), nearest_street(max(na, nb), NS_STREETS)
        on = street if axis == 'NS' and street else nearest_street((ea + eb) / 2, EW_STREETS)
    else:
        c1, c2 = nearest_street(min(ea, eb), EW_STREETS), nearest_street(max(ea, eb), EW_STREETS)
        on = street if axis == 'EW' and street else nearest_street((na + nb) / 2, NS_STREETS)
    cross = f'at {c1}' if c1 == c2 else f'{c1} to {c2}'
    return f'{on}, {cross}'


def slowest_stretches(bins, pats, route, street=None, axis=None, period_hours=('am', 'pm'), window=2, min_pairs=60):
    """Slowest half-mile (two quarter-mile bins) on each of the route's two busiest included patterns."""
    main = pats[(pats.route == route) & pats.included].sort_values('trips', ascending=False).head(2)
    out = []
    for _, p in main.iterrows():
        b = bins[(bins.pid == p.pid) & bins.period.isin(period_hours)]
        b = (b.assign(lf=b.lat * b.pairs, nf=b.lon * b.pairs).groupby('bin')
             .agg(feet=('feet', 'sum'), seconds=('seconds', 'sum'), pairs=('pairs', 'sum'), lf=('lf', 'sum'), nf=('nf', 'sum')))
        b['lat'], b['lon'] = b.lf / b.pairs, b.nf / b.pairs
        maxbin = int(p.length_ft // 1320)
        b = b[(b.index >= 4) & (b.index <= maxbin - 4) & (b.pairs >= min_pairs)]   # skip the mile at each end
        best = None
        for i in b.index:
            w = [j for j in range(i, i + window) if j in b.index]
            if len(w) < window:
                continue
            ww = b.loc[w]
            v = (ww.feet.sum() / 5280) / (ww.seconds.sum() / 3600)
            if best is None or v < best[0]:
                best = (v, ww.iloc[0][['lat', 'lon']].tolist(), ww.iloc[-1][['lat', 'lon']].tolist(), int(ww.pairs.sum()))
        if best:
            where = describe_stretch(best[1], best[2], street, axis)
            note = STRETCH_NOTES.get((route, where.split(',')[0]))
            out.append(dict(pid=p.pid, toward=p.destination, mph=round(best[0], 3), note=note,
                            where=where, start=[round(x, 5) for x in best[1]],
                            end=[round(x, 5) for x in best[2]], pairs=best[3]))
    return sorted(out, key=lambda x: x['mph'])


class FixedSegments:
    """Route speeds on a fixed set of ~220 m cells, weighted identically in every period.

    Pooling all pairs per period mixes slower travel with changes in where buses run (rush-only
    extensions, outer ends served more at midday). Here each route keeps only cells observed in all of
    AM, midday and PM; each cell gets one distance weight (its total feet), and a period's speed is
    total weighted distance / total time to cover those cells at that period's cell speeds.
    """

    def __init__(self, cells_day, routes, days):
        self.days = list(days)
        self.day_index = pd.to_datetime(self.days)
        self.routes = {}
        cd = cells_day[cells_day.route.isin(routes) & cells_day.period.notna()]
        for rt, c in cd.groupby('route'):
            tot = c.groupby(['cell_lat', 'cell_lon', 'period']).pairs.sum().unstack('period', fill_value=0)
            if not {'am', 'mid', 'pm'} <= set(tot.columns):
                continue
            keep = tot[(tot.am >= MIN_CELL_PAIRS) & (tot.mid >= MIN_CELL_PAIRS) & (tot.pm >= MIN_CELL_PAIRS)].index
            # Drop cells averaging under 1 mph in any period: holding spots, not travel (2 cells in the top 20).
            sp = c.groupby(['cell_lat', 'cell_lon', 'period'])[['feet', 'seconds']].sum()
            sp = (sp.feet / sp.seconds * 3600 / FT_PER_MILE).unstack('period')
            keep = [k for k in keep if sp.loc[k, ['am', 'mid', 'pm']].min() >= 1.0]
            if len(keep) == 0:
                continue
            c = c.set_index(['cell_lat', 'cell_lon'])
            arrays = {}
            for p in ['am', 'mid', 'pm']:
                g = c[c.period == p].reset_index().pivot_table(index=['cell_lat', 'cell_lon'], columns='service_day',
                                                              values=['feet', 'seconds'], aggfunc='sum', fill_value=0)
                g = g.reindex(keep, fill_value=0)
                fe, se = g['feet'], g['seconds']
                fe.columns, se.columns = pd.to_datetime(fe.columns), pd.to_datetime(se.columns)
                arrays[p] = (fe.reindex(columns=self.day_index, fill_value=0).to_numpy(float),
                             se.reindex(columns=self.day_index, fill_value=0).to_numpy(float))
            arrays['peak'] = (arrays['am'][0] + arrays['pm'][0], arrays['am'][1] + arrays['pm'][1])
            w = sum(arrays[p][0].sum(1) for p in ['am', 'mid', 'pm'])
            all_feet = c.feet.sum()
            self.routes[rt] = dict(arrays=arrays, w=w, coverage=float(w.sum() / all_feet), cells=len(keep))

    @staticmethod
    def _speed(F, S, w, counts=None):
        """counts: (reps x days) multiplicities, or None for the full sample. Returns mph (scalar or reps)."""
        full_v = F.sum(1) / np.where(S.sum(1) > 0, S.sum(1), np.nan)
        if counts is None:
            return float(w.sum() / np.nansum(w / full_v)) * 3600 / FT_PER_MILE
        Fs, Ss = counts @ F.T, counts @ S.T
        ok = (Ss > 0) & (Fs > 0)       # a resampled cell with no time or no distance keeps its full-sample speed
        v = np.where(ok, Fs / np.where(ok, Ss, 1), full_v[None, :])
        return (w.sum() / np.nansum(w[None, :] / v, axis=1)) * 3600 / FT_PER_MILE

    def speed(self, routes, period, counts=None):
        rs = [self.routes[r] for r in routes if r in self.routes]
        F = np.vstack([r['arrays'][period][0] for r in rs])
        S = np.vstack([r['arrays'][period][1] for r in rs])
        w = np.concatenate([r['w'] for r in rs])
        return self._speed(F, S, w, counts)

    def bootstrap(self, route, reps=4000, seed=20261031):
        rng = np.random.default_rng(seed)
        idx = rng.integers(0, len(self.days), size=(reps, len(self.days)))
        counts = np.zeros((reps, len(self.days)))
        np.add.at(counts, (np.arange(reps)[:, None], idx), 1)
        sp = {p: self.speed([route], p, counts) for p in PERIODS}
        q = lambda v: [float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))]
        res = {p: q(v) for p, v in sp.items()}
        res['penalty'] = q(1 - sp['peak'] / sp['mid'])
        res['pm_penalty'] = q(1 - sp['pm'] / sp['mid'])
        res['am_penalty'] = q(1 - sp['am'] / sp['mid'])
        return res


def shared_cell_comparison(cells, a, b, period, min_pairs=40):
    """Speeds of routes a and b on the cells both serve in `period` (same cells, same distance weights)."""
    c = cells[(cells.period == period) & cells.route.isin([a, b])]
    g = c.groupby(['route', 'cell_lat', 'cell_lon'])[['feet', 'seconds', 'pairs']].sum()
    ga, gb = g.loc[a], g.loc[b]
    both = ga.index.intersection(gb.index)
    both = [i for i in both if ga.loc[i, 'pairs'] >= min_pairs and gb.loc[i, 'pairs'] >= min_pairs]
    if not both:
        return None
    w = ga.loc[both, 'feet'].to_numpy() + gb.loc[both, 'feet'].to_numpy()
    va = ga.loc[both, 'feet'].to_numpy() / ga.loc[both, 'seconds'].to_numpy()
    vb = gb.loc[both, 'feet'].to_numpy() / gb.loc[both, 'seconds'].to_numpy()
    sp = lambda v: float(w.sum() / (w / v).sum()) * 3600 / FT_PER_MILE
    return dict(cells=len(both), miles=round(float(w.sum() / 2 / FT_PER_MILE / 20), 2), a_mph=sp(va), b_mph=sp(vb))


def load_ridership(path):
    con = duckdb.connect()
    df = con.execute("""
        SELECT route, count(*) FILTER (daytype='W') weekdays,
               avg(rides) FILTER (daytype='W') avg_weekday_rides, sum(rides) total_rides
        FROM read_csv(?, columns={'route':'VARCHAR','date':'TIMESTAMP','daytype':'VARCHAR','rides':'BIGINT'}, header=true)
        GROUP BY route""", [str(path)]).df()
    span = con.execute("SELECT min(date)::DATE, max(date)::DATE FROM read_csv(?, header=true)", [str(path)]).fetchone()
    return df.sort_values('avg_weekday_rides', ascending=False).reset_index(drop=True), span


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--db', required=True, type=Path)
    ap.add_argument('--ridership', required=True, type=Path,
                    help='CTA daily bus ridership CSV (downloaded with --fetch-ridership if missing)')
    ap.add_argument('--fetch-ridership', action='store_true')
    ap.add_argument('--names', type=Path, default=HERE / 'route_names.csv')
    ap.add_argument('--out', required=True, type=Path)
    ap.add_argument('--no-sensitivity', action='store_true')
    args = ap.parse_args()

    if args.fetch_ridership and not args.ridership.exists():
        args.ridership.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(['curl', '-fsS', '--max-time', '120', RIDERSHIP_URL, '-o', str(args.ridership)], check=True)
    ridership, rspan = load_ridership(args.ridership)
    top20 = ridership.head(20).copy()
    top20['rank'] = range(1, 21)
    names = pd.read_csv(args.names, dtype={'route': str})

    con = duckdb.connect(str(args.db), read_only=True)
    con.execute("SET TimeZone='America/Chicago'; SET memory_limit='12GB'; SET max_temp_directory_size='2GB';"
                "SET preserve_insertion_order=false")
    version = con.execute('SELECT version()').fetchone()[0]
    manifest = con.execute("SELECT kind, archive_date, sha256, rows, bytes FROM archive_ingest ORDER BY archive_date").df()
    weekdays = archive_weekdays(con)
    main_days = [d for d in weekdays if d.isoformat() not in EXCLUDED_DAYS]

    out = run_pipeline(con, main_days)
    rdh = out['out_route_day_hour']
    per = period_frame(rdh)
    wide = per.pivot(index='route', columns='period', values='mph')          # all-service pooled speeds
    vh = per.pivot(index='route', columns='period', values='vehicle_hours')
    cells_day = out['out_cells']
    cells_day = cells_day[cells_day.period.notna()].copy()
    cells = cells_day.groupby(['route', 'cell_lat', 'cell_lon', 'period'], as_index=False)[['feet', 'seconds', 'pairs']].sum()

    # Pattern lengths: the most-travelled included patterns per route, for approximate end-to-end ride times.
    pats = out['out_patterns']
    main_pat = (pats[pats.included].sort_values(['route', 'trips'], ascending=[True, False])
                .groupby('route').head(2).groupby('route').length_ft.mean())

    top_routes = top20.route.tolist()
    eligible = [r for r in vh.index if all(vh.loc[r, p] >= MIN_ROUTE_VH for p in ['am', 'mid', 'pm'])]
    other_routes = [r for r in eligible if r not in top_routes and r not in EXPRESS_ROUTES]
    fs = FixedSegments(cells_day, sorted(set(top_routes) | set(eligible)), main_days)
    fixed = {r: {p: fs.speed([r], p) for p in PERIODS} for r in fs.routes}
    ci = {r: fs.bootstrap(r) for r in top_routes}

    # Hourly weekday profile, 05:00-22:59 local (all service in each hour).
    hourly = (rdh[rdh.hr.between(5, 22)].groupby(['route', 'hr'])[['feet', 'seconds']].sum().reset_index())
    hourly['mph'] = hourly.feet / FT_PER_MILE / (hourly.seconds / 3600)

    # Daily all-service peak and midday speeds (published for inspection).
    daily = []
    for p in ['peak', 'mid']:
        d = rdh[rdh.hr.isin(PERIODS[p])].groupby(['route', 'service_day'])[['feet', 'seconds']].sum().reset_index()
        d['period'] = p
        daily.append(d)
    daily = pd.concat(daily)
    daily['mph'] = daily.feet / FT_PER_MILE / (daily.seconds / 3600)

    def pooled(routes, p):
        s = per[(per.period == p) & per.route.isin(routes)]
        return mph(s.feet.sum(), s.seconds.sum())

    route_rows = []
    for _, r in top20.iterrows():
        rt = r.route
        nm = names.loc[names.route == rt, 'name']
        plen = float(main_pat.get(rt, np.nan))
        rec = dict(rank=int(r['rank']), route=rt, name=nm.iloc[0] if len(nm) else rt,
                   avg_weekday_rides=round(float(r.avg_weekday_rides)), total_rides_12mo=int(r.total_rides),
                   pattern_miles=round(plen / FT_PER_MILE, 2),
                   fixed_segment_cells=fs.routes[rt]['cells'], fixed_segment_coverage=round(fs.routes[rt]['coverage'], 4))
        for p in PERIODS:
            rec[f'{p}_mph'] = round(fixed[rt][p], 4)
            rec[f'{p}_mph_all_service'] = round(float(wide.loc[rt, p]), 4)
            rec[f'{p}_vehicle_hours'] = round(float(vh.loc[rt, p]))
            rec[f'{p}_ci'] = [round(x, 3) for x in ci[rt][p]]
        rec['penalty'] = round(1 - rec['peak_mph'] / rec['mid_mph'], 4)
        rec['penalty_ci'] = [round(x, 4) for x in ci[rt]['penalty']]
        rec['pm_penalty'] = round(1 - rec['pm_mph'] / rec['mid_mph'], 4)
        rec['pm_penalty_ci'] = [round(x, 4) for x in ci[rt]['pm_penalty']]
        rec['am_penalty'] = round(1 - rec['am_mph'] / rec['mid_mph'], 4)
        rec['am_penalty_ci'] = [round(x, 4) for x in ci[rt]['am_penalty']]
        rec['peak_minutes_end_to_end'] = round(plen / FT_PER_MILE / rec['peak_mph'] * 60, 1)
        rec['mid_minutes_end_to_end'] = round(plen / FT_PER_MILE / rec['mid_mph'] * 60, 1)
        rec['hourly'] = [round(float(v), 2) for v in hourly[hourly.route == rt].set_index('hr').reindex(range(5, 23)).mph]
        nrow = names[names.route == rt]
        rec['street'] = nrow.street.iloc[0] if len(nrow) else None
        rec['slowest_stretch_rush'] = slowest_stretches(out['out_bins'], pats, rt, rec['street'],
                                                        nrow.axis.iloc[0] if len(nrow) else None)
        q = out['out_qa'].set_index('route').loc[rt]
        rec['qa'] = dict(raw_rows=int(q.raw_rows), dedup_fixes=int(q.dedup_fixes), trips=int(q.trips),
                         pairs=int(q.pairs), pairs_kept=int(q.pairs_kept),
                         share_time_layover=round(float(q.seconds_layover / q.pair_seconds), 4),
                         share_time_long_gap=round(float(q.seconds_long_gap / q.pair_seconds), 4),
                         pairs_backward=int(q.pairs_backward), pairs_geometry=int(q.pairs_geometry),
                         pairs_short_pattern=int(q.pairs_short_pattern))
        route_rows.append(rec)

    others_fs = [r for r in other_routes if r in fs.routes]
    ranked = sorted([r for r in eligible if r in fixed and r not in EXPRESS_ROUTES - {'146'}], key=lambda r: fixed[r]['peak'])
    system = {
        'method': 'fixed-segment',
        'top20_pooled': {p: round(fs.speed(top_routes, p), 4) for p in PERIODS},
        'other_routes_pooled': {p: round(fs.speed(others_fs, p), 4) for p in PERIODS},
        'other_routes': others_fs,
        'other_routes_rule': f'Non-express routes outside the top 20 with at least {MIN_ROUTE_VH} vehicle-hours in each of AM, midday and PM',
        'top20_all_service': {p: round(pooled(top_routes, p), 4) for p in PERIODS},
        'other_routes_all_service': {p: round(pooled(others_fs, p), 4) for p in PERIODS},
        'route_median': {p: round(float(np.median([fixed[r][p] for r in ranked])), 4) for p in PERIODS},
        'route_count': len(ranked),
        'top20_peak_ranks': {r: ranked.index(r) + 1 for r in top_routes if r in ranked},
        'top20_hourly': [round(mph(*hourly[(hourly.route.isin(top_routes)) & (hourly.hr == h)][['feet', 'seconds']].sum()), 3)
                         for h in range(5, 23)],
        'other_routes_hourly': [round(mph(*hourly[hourly.route.isin(others_fs) & (hourly.hr == h)][['feet', 'seconds']].sum()), 3)
                                for h in range(5, 23)],
    }
    qa_top = out['out_qa'][out['out_qa'].route.isin(top_routes)]
    system['counts_top20'] = dict(raw_rows=int(qa_top.raw_rows.sum()), dedup_fixes=int(qa_top.dedup_fixes.sum()),
                                  trips=int(qa_top.trips.sum()), pairs=int(qa_top.pairs.sum()),
                                  pairs_kept=int(qa_top.pairs_kept.sum()),
                                  vehicle_hours_kept=round(float(qa_top.seconds_kept.sum() / 3600)),
                                  miles_kept=round(float(qa_top.feet_kept.sum() / 5280)),
                                  share_time_layover=round(float(qa_top.seconds_layover.sum() / qa_top.pair_seconds.sum()), 4),
                                  share_time_long_gap=round(float(qa_top.seconds_long_gap.sum() / qa_top.pair_seconds.sum()), 4),
                                  fixed_segment_coverage=round(float(np.average([fs.routes[r]['coverage'] for r in top_routes])), 4))
    all_route_table = [dict(route=rt, express=rt in EXPRESS_ROUTES, top20=rt in top_routes,
                            **{f'{p}_mph': round(fixed[rt][p], 4) for p in PERIODS},
                            **{f'{p}_vehicle_hours': round(float(vh.loc[rt, p])) for p in ['am', 'mid', 'pm']})
                       for rt in sorted(fixed, key=lambda r: fixed[r]['peak'])]

    # Express vs local on the cells both serve. Expresses barely run midday, so only the rushes are compared.
    express = []
    for x, local in EXPRESS_PAIRS:
        rec = dict(express=x, local=local,
                   express_vehicle_hours={p: round(float(vh.loc[x, p])) if x in vh.index else 0 for p in ['am', 'mid', 'pm']})
        for p in ['am', 'pm']:
            cmp = shared_cell_comparison(cells, x, local, p)
            if cmp:
                rec[p] = dict(cells=cmp['cells'], express_mph=round(cmp['a_mph'], 3), local_mph=round(cmp['b_mph'], 3),
                              advantage=round(cmp['a_mph'] / cmp['b_mph'] - 1, 4))
        express.append(rec)

    # Named areas on the map: all top-20 cells inside a lat/lon box (both directions, all routes).
    top_cells = cells[cells.route.isin(top_routes)]
    def region(box, route=None):
        res = {}
        for p_ in ['am', 'mid', 'pm']:
            q_ = top_cells[(top_cells.period == p_) & top_cells.cell_lat.between(box[0], box[1])
                           & top_cells.cell_lon.between(box[2], box[3])]
            if route:
                q_ = q_[q_.route == route]
            res[p_] = round(mph(q_.feet.sum(), q_.seconds.sum()), 3)
        return res
    system['regions'] = {
        'loop': dict(label='The Loop (Lake St to Congress, Wacker to Michigan)', box=REGION_LOOP, **region(REGION_LOOP)),
        'lsd_146': dict(label='Route 146 on Lake Shore Drive (Division to Belmont)', box=REGION_LSD, **region(REGION_LSD, '146')),
    }

    sensitivity = []
    if not args.no_sensitivity:
        variants = {
            'main (20 weekdays)': main_days,
            'strict coverage (17 weekdays)': [d for d in main_days if d.isoformat() not in STRICT_EXTRA],
            "include Oct 12 holiday (21 weekdays)": sorted(main_days + [dt.date(2026, 10, 12)]),
        }
        for label, days in variants.items():
            if days is main_days:
                fsv = fs
            else:
                o = run_pipeline(con, days, routes=top_routes)
                fsv = FixedSegments(o['out_cells'][o['out_cells'].period.notna()], top_routes, days)
            for rt in top_routes:
                sensitivity.append(dict(variant=label, days=len(days), route=rt,
                                        peak_mph=round(fsv.speed([rt], 'peak'), 4), mid_mph=round(fsv.speed([rt], 'mid'), 4)))
            sensitivity.append(dict(variant=label, days=len(days), route='TOP20',
                                    peak_mph=round(fsv.speed(top_routes, 'peak'), 4), mid_mph=round(fsv.speed(top_routes, 'mid'), 4)))

    args.out.mkdir(parents=True, exist_ok=True)
    meta = dict(
        generated_at=dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds'),
        duckdb_version=version,
        archive_first=str(manifest.archive_date.min())[:10], archive_last=str(manifest.archive_date.max())[:10],
        archive_files=len(manifest), archive_rows=int(manifest.rows.sum()),
        service_days=[d.isoformat() for d in main_days],
        excluded_weekdays=EXCLUDED_DAYS,
        periods={'am': '07:00-09:00', 'mid': '10:00-14:00', 'pm': '16:00-18:00', 'peak': 'am + pm'},
        ridership_source='https://data.cityofchicago.org/d/jyb9-n7fm',
        ridership_span=[str(rspan[0]), str(rspan[1])], ridership_sha256=sha256(args.ridership),
        position_source='https://data.chicagotransitalerts.app/positions/index.json',
        manifest=[dict(archive_date=str(r.archive_date)[:10], rows=int(r.rows), bytes=int(r.bytes), sha256=r.sha256)
                  for r in manifest.itertuples()],
    )
    meta['sql'] = SQL.read_text()
    payload = dict(meta=meta, system=system, routes=route_rows, all_routes=all_route_table,
                   express=express, sensitivity=sensitivity)
    (args.out / 'scorecard.json').write_text(json.dumps(payload, indent=1, default=str))
    # Outputs are sorted so a rebuild from the same archive is byte-identical (DuckDB row order is not fixed).
    top_cells.sort_values(['route', 'period', 'cell_lat', 'cell_lon']).to_csv(args.out / 'corridor_cells.csv', index=False, float_format='%.6g')
    hourly.sort_values(['route', 'hr']).to_csv(args.out / 'route_hourly.csv', index=False, float_format='%.6g')
    daily.sort_values(['route', 'period', 'service_day']).to_csv(args.out / 'route_daily.csv', index=False, float_format='%.6g')
    rdh.sort_values(['route', 'service_day', 'hr']).to_csv(args.out / 'route_day_hour.csv', index=False, float_format='%.6g')
    pats.sort_values(['route', 'pid']).to_csv(args.out / 'patterns.csv', index=False, float_format='%.8g')
    out['out_bins'][out['out_bins'].route.isin(top_routes)].sort_values(['route', 'pid', 'period', 'bin']).to_csv(args.out / 'pattern_bins.csv', index=False, float_format='%.7g')
    # Compact cell file for the interactive map: pooled across the 20 routes, per period.
    mc = {}
    for p_ in ['am', 'mid', 'pm']:
        cp = top_cells[top_cells.period == p_]
        gg = cp.groupby(['cell_lat', 'cell_lon']).agg(feet=('feet', 'sum'), seconds=('seconds', 'sum'), pairs=('pairs', 'sum'),
                                                       routes=('route', lambda r: ' '.join(sorted(set(r), key=lambda x: (len(x), x)))))
        gg = gg[gg.pairs >= 40].reset_index().sort_values(['cell_lat', 'cell_lon'])
        mc[p_] = [[round(a, 4), round(b, 4), round(f / 5280 / (s / 3600), 2), int(n), rr]
                  for a, b, f, s, n, rr in gg[['cell_lat', 'cell_lon', 'feet', 'seconds', 'pairs', 'routes']].itertuples(index=False)]
    (args.out / 'map_cells.json').write_text(json.dumps(dict(min_pairs=40, cell_deg=[0.002, 0.0027], periods=mc), separators=(',', ':')))
    out['out_qa'].sort_values('route').to_csv(args.out / 'qa_funnel.csv', index=False, float_format='%.6g')
    manifest.to_csv(args.out / 'source_manifest.csv', index=False)
    print(json.dumps(dict(system=system, express=express), indent=1))
    print(pd.DataFrame(route_rows)[['rank', 'route', 'name', 'am_mph', 'mid_mph', 'pm_mph', 'peak_mph', 'peak_mph_all_service',
                                    'penalty', 'penalty_ci', 'pm_penalty_ci', 'fixed_segment_coverage']].to_string(index=False))


if __name__ == '__main__':
    main()
