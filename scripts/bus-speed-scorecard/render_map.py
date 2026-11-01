#!/usr/bin/env python3
"""Render the 4:5 corridor speed map (1600x2000 px): where the 20 busiest CTA routes crawl.

  python -I scripts/bus-speed-scorecard/render_map.py --cells data/bus-speed-scorecard/corridor_cells.csv \
      --data data/bus-speed-scorecard/scorecard.json --wards data/chicago-wards.geojson \
      --out images/cta-bus-speed-map.png [--period pm] [--headline-font path.ttf]

Cells are ~220 m GPS-midpoint bins of kept speed pairs; all 20 routes and both directions are pooled
per cell as sum(feet) / sum(seconds). Cells with fewer than --min-pairs pairs are not drawn.
"""
import argparse
import json
from pathlib import Path
import textwrap

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager as fm
from matplotlib.patches import FancyBboxPatch, Polygon
import numpy as np
import pandas as pd

BG = '#fbfaf7'
LAND = '#ecebe5'
INK = '#0b0b0b'
INK2 = '#52514e'
MUTED = '#898781'
# Diverging classes: warm = slower than the network's typical speed, gray = typical, cool = faster.
BINS = [0, 5, 6.5, 8, 10, 12, 15, 99]
COLORS = ['#9f2a22', '#df4a3f', '#f19c82', '#bcb9b0', '#8db8ee', '#3a86e0', '#164f98']
LABELS = ['under 5', '5–6.5', '6.5–8', '8–10', '10–12', '12–15', '15+']
PERIOD_TEXT = {'pm': 'evening rush, 4–6 PM', 'am': 'morning rush, 7–9 AM', 'mid': 'midday, 10 AM–2 PM'}
LOOP = (41.8819, -87.6278)


def pick_sans():
    have = {f.name for f in fm.fontManager.ttflist}
    return next((n for n in ['Helvetica Neue', 'Helvetica', 'Arial'] if n in have), 'DejaVu Sans')


def ward_polygons(path):
    gj = json.loads(Path(path).read_text())
    for feat in gj['features']:
        g = feat['geometry']
        polys = g['coordinates'] if g['type'] == 'MultiPolygon' else [g['coordinates']]
        for poly in polys:
            yield np.asarray(poly[0])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--cells', required=True, type=Path)
    ap.add_argument('--data', required=True, type=Path)
    ap.add_argument('--wards', required=True, type=Path)
    ap.add_argument('--out', required=True, type=Path)
    ap.add_argument('--period', default='pm', choices=['pm', 'am', 'mid'])
    ap.add_argument('--min-pairs', type=int, default=40)
    ap.add_argument('--headline-font', type=Path)
    ap.add_argument('--handle', default='CTA Bus Speed Scorecard')
    args = ap.parse_args()

    sans = pick_sans()
    plt.rcParams.update({'font.family': sans, 'text.color': INK})
    head = fm.FontProperties(family=sans, weight='bold', size=40)
    if args.headline_font and args.headline_font.exists():
        head = fm.FontProperties(fname=str(args.headline_font), size=50)

    d = json.loads(args.data.read_text())
    cells = pd.read_csv(args.cells, dtype={'route': str})
    per = cells[cells.period == args.period]
    g = per.groupby(['cell_lat', 'cell_lon'], as_index=False)[['feet', 'seconds', 'pairs']].sum()
    g = g[g.pairs >= args.min_pairs].copy()
    g['mph'] = g.feet / 5280 / (g.seconds / 3600)
    g['cls'] = np.digitize(g.mph, BINS[1:-1])
    g = g.sort_values('mph', ascending=False)          # slow cells drawn last, on top

    fig = plt.figure(figsize=(8, 10), dpi=200, facecolor=BG)
    bg = fig.add_axes([0, 0, 1, 1], zorder=-10)
    bg.set_xlim(0, 1); bg.set_ylim(0, 1); bg.axis('off')
    sysm = d['system']['top20_pooled']
    key = {'pm': 'pm_mph', 'am': 'am_mph', 'mid': 'mid_mph'}[args.period]

    # ---- Header (full width) ---------------------------------------------------------------------
    fig.text(0.055, 0.966, "CTA BUS SPEED SCORECARD  ·  CHICAGO'S 20 HIGHEST-RIDERSHIP BUS ROUTES",
             fontsize=8.6, color='#eb6834', weight='bold', va='top')
    heading = fig.text(0.052, 0.95, 'WHERE THE BUS CRAWLS', va='top', color=INK, fontproperties=head)
    # Fit installed fallback fonts as well as the optional condensed headline font.
    fig.canvas.draw()
    width = heading.get_window_extent(fig.canvas.get_renderer()).width
    available = fig.bbox.width * 0.90
    if width > available:
        heading.set_fontsize(heading.get_fontsize() * available / width)
    fig.text(0.055, 0.877, f"Average bus speed during the {PERIOD_TEXT[args.period]}, every ~220 m along Chicago's 20 busiest\n"
             "CTA bus routes. Both directions combined; time at stops and red lights included.",
             fontsize=10, color=INK2, va='top', linespacing=1.45)

    # ---- Map --------------------------------------------------------------------------------------
    lat0, lat1 = g.cell_lat.min() - 0.008, g.cell_lat.max() + 0.006
    lon0, lon1 = g.cell_lon.min() - 0.012, -87.515
    k = 1 / np.cos(np.radians((lat0 + lat1) / 2))
    map_h = 0.745
    map_w = map_h * (10 / 8) * (lon1 - lon0) / ((lat1 - lat0) * k)
    ax = fig.add_axes([0.03, 0.085, map_w, map_h], facecolor='none')
    ax.set_xlim(lon0, lon1); ax.set_ylim(lat0, lat1); ax.set_aspect(k); ax.axis('off')
    for poly in ward_polygons(args.wards):
        ax.add_patch(Polygon(poly, closed=True, facecolor=LAND, edgecolor=LAND, lw=0.6, zorder=0))
    ax.scatter(g.cell_lon, g.cell_lat, s=10, c=[COLORS[c] for c in g.cls], marker='s', linewidths=0, zorder=3)
    ax.text(-87.585, 41.985, 'Lake Michigan', fontsize=9, color='#97a6b5', style='italic', ha='left', zorder=1)

    # Route badges at each route's outer end (cell farthest from the Loop), nudged apart.
    rc = per.groupby(['route', 'cell_lat', 'cell_lon'], as_index=False).pairs.sum()
    rc = rc[rc.pairs >= args.min_pairs]
    rc['dist'] = np.hypot(rc.cell_lat - LOOP[0], (rc.cell_lon - LOOP[1]) / k)
    ends = rc.sort_values('dist').groupby('route').tail(1)
    placed = []
    for _, e in ends.sort_values('dist', ascending=False).iterrows():
        x, y = e.cell_lon, e.cell_lat
        # Small nudges only, so every badge stays touching its route end.
        for dx, dy in [(0, 0), (-0.018, 0), (0, -0.013), (0.018, 0), (0, 0.013)]:
            if not any(abs(x + dx - px) < 0.017 and abs(y + dy - py) < 0.011 for px, py in placed):
                x, y = x + dx, y + dy
                break
        placed.append((x, y))
        ax.text(x, y, e.route, fontsize=6.8, color='white', weight='bold', ha='center', va='center', zorder=6,
                bbox=dict(boxstyle='round,pad=0.28,rounding_size=0.35', fc=INK, ec='none'))

    # Callouts placed over the lake.
    def region(lat_a, lat_b, lon_a, lon_b, route=None):
        q = per if route is None else per[per.route == route]
        q = q[q.cell_lat.between(lat_a, lat_b) & q.cell_lon.between(lon_a, lon_b)]
        return q.feet.sum() / 5280 / (q.seconds.sum() / 3600)
    loop = d['system']['regions']['loop'][args.period]
    lsd = d['system']['regions']['lsd_146'][args.period]
    callout = dict(fontsize=8.4, color=INK, ha='left', va='center', zorder=7, linespacing=1.3)
    arrow = dict(arrowstyle='-', color=INK2, lw=0.8, shrinkA=2, shrinkB=4)
    ax.annotate(f"The Loop\n{loop:.1f} mph", xy=(-87.622, 41.882), xytext=(-87.585, 41.872), arrowprops=arrow, **callout)
    ax.annotate(f"Lake Shore Dr (146)\n{lsd:.0f} mph", xy=(-87.628, 41.922), xytext=(-87.596, 41.935), arrowprops=arrow, **callout)

    # ---- Right panel: vertical legend + facts --------------------------------------------------------
    tx = 0.03 + map_w + 0.035
    width_chars = int((0.96 - tx) * 1600 / 12.5)
    fig.text(tx, 0.815, 'Miles per hour', fontsize=8.6, color=INK2, weight='bold', va='top')
    sy, sh = 0.79, 0.031
    for i, (c, lab) in enumerate(zip(COLORS, LABELS)):
        y = sy - i * sh
        bg.add_patch(FancyBboxPatch((tx, y - 0.019), 0.032, 0.019, boxstyle='round,pad=0,rounding_size=0.003',
                     facecolor=c, edgecolor='none'))
        fig.text(tx + 0.042, y - 0.0095, lab, fontsize=8.6, color=INK, va='center')
    fig.text(tx + 0.13, sy - 0.0095, 'slower', fontsize=7.6, color=MUTED, va='center')
    fig.text(tx + 0.13, sy - 6 * sh - 0.0095, 'faster', fontsize=7.6, color=MUTED, va='center')

    share_slow = float((g.cls <= 2).mean())
    slowest = sorted(d['routes'], key=lambda r: r[key])[:3]
    facts = [
        (f"{share_slow * 100:.0f}%", f"of mapped stretches average under 8 mph"),
        (f"{loop:.1f} mph", "average bus speed in the Loop"),
        (f"{sysm[args.period]:.1f} mph", "all 20 routes combined"),
    ]
    y = 0.535
    for big, small in facts:
        fig.text(tx, y, big, fontsize=19, color=INK, weight='bold', va='top')
        fig.text(tx, y - 0.035, textwrap.fill(small, width_chars), fontsize=8.6, color=INK2, va='top', linespacing=1.35)
        y -= 0.095
    fig.text(tx, y + 0.005, 'Slowest routes', fontsize=8.6, color=INK2, weight='bold', va='top')
    for j, r in enumerate(slowest):
        fig.text(tx, y - 0.025 - j * 0.024, f"{r['route']} {r['name']}", fontsize=8.6, color=INK, va='top')
        fig.text(0.96, y - 0.025 - j * 0.024, f"{r[key]:.1f}", fontsize=8.6, color=INK, va='top', ha='right', weight='bold')

    m = d['meta']
    fig.text(0.055, 0.066, f"{len(m['service_days'])} weekdays, Sep 28–Oct 30, 2026. Speed = distance along the route ÷ time between GPS fixes, stops included; "
             "terminal layovers excluded.\n"
             f"Cells near stops include dwell; cells with < {args.min_pairs} measurements not drawn. Data: CTA Bus Tracker via "
             "chicagotransitalerts.app. Silhouette: Chicago wards.",
             fontsize=6.9, color=MUTED, va='top', linespacing=1.5)
    bg.plot([0.055, 0.945], [0.036, 0.036], color='#e4e2da', lw=0.8)
    fig.text(0.055, 0.013, args.handle, fontsize=9.8, color=INK, weight='bold', va='bottom')
    fig.text(0.945, 0.013, 'Open data · Reproducible SQL', fontsize=8.4,
             color=INK2, ha='right', va='bottom')

    args.out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.out, dpi=200, facecolor=BG, metadata={'Software': None})
    print(args.out, len(g), 'cells', f'{share_slow:.3f} slow share', f'loop {loop:.2f}', f'lsd {lsd:.2f}')


if __name__ == '__main__':
    main()
