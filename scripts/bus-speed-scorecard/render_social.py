#!/usr/bin/env python3
"""Render the 4:5 social graphic (1600x2000 px) from scorecard.json.

  python -I scripts/bus-speed-scorecard/render_social.py --data data/bus-speed-scorecard/scorecard.json \
      --out images/cta-bus-speed-scorecard.png [--variant three|dumbbell] [--headline-font path.ttf]

The headline uses Big Shoulders Display (SIL OFL, the typeface of Chicago's city identity) when a static
bold instance is supplied; everything else uses Helvetica Neue / Helvetica / DejaVu Sans.
"""
import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager as fm
from matplotlib.patches import FancyBboxPatch

BG = '#fbfaf7'
INK = '#0b0b0b'
INK2 = '#52514e'
MUTED = '#898781'
GRID = '#e4e2da'
BAND = '#f2f0ea'
BLUE = '#2a78d6'     # midday (off-peak)
ORANGE = '#eb6834'   # rush hour / PM rush
AMC = '#898781'      # AM rush (de-emphasised: it barely differs from midday)


def pick_sans():
    have = {f.name for f in fm.fontManager.ttflist}
    for name in ['Helvetica Neue', 'Helvetica', 'Arial', 'DejaVu Sans']:
        if name in have:
            return name
    return 'DejaVu Sans'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--data', required=True, type=Path)
    ap.add_argument('--out', required=True, type=Path)
    ap.add_argument('--variant', choices=['three', 'dumbbell'], default='three')
    ap.add_argument('--headline-font', type=Path)
    ap.add_argument('--handle', default='CTA Bus Speed Scorecard')
    args = ap.parse_args()

    d = json.loads(args.data.read_text())
    routes = d['routes']
    sysm = d['system']['top20_pooled']
    sans = pick_sans()
    plt.rcParams.update({'font.family': sans, 'text.color': INK, 'axes.edgecolor': GRID})
    head = dict(fontproperties=fm.FontProperties(family=sans, weight='bold', size=40))
    if args.headline_font and args.headline_font.exists():
        # Use the file directly: a variable-font install can share the family name at a thin weight.
        head = dict(fontproperties=fm.FontProperties(fname=str(args.headline_font), size=50))

    key = 'pm_mph' if args.variant == 'three' else 'peak_mph'
    rows = sorted(routes, key=lambda r: r[key])   # slowest first (top)
    n = len(rows)

    W, H = 8.0, 10.0
    fig = plt.figure(figsize=(W, H), dpi=200, facecolor=BG)
    # Background layer (figure coordinates) for row bands and badges, drawn beneath the chart axes.
    bg = fig.add_axes([0, 0, 1, 1], zorder=-10)
    bg.set_xlim(0, 1); bg.set_ylim(0, 1); bg.axis('off')

    # ---- Header -------------------------------------------------------------------------------
    fig.text(0.055, 0.962, "CTA BUS SPEED SCORECARD  ·  CHICAGO'S 20 HIGHEST-RIDERSHIP BUS ROUTES",
             fontsize=8.6, color=ORANGE, weight='bold', va='top')
    if args.variant == 'three':
        title = 'THE 5 PM CRAWL'
        sub = (f"Chicago's busiest buses average {sysm['mid']:.1f} mph at midday. In the evening rush they "
               f"slow to {sysm['pm']:.1f} mph.\nThe morning rush is barely slower than midday ({sysm['am']:.1f} mph).")
    else:
        title = 'HOW FAST IS YOUR BUS?'
        other = d['system']['other_routes_pooled']
        slowest = min(routes, key=lambda r: r['peak_mph'])
        sub = (f"Chicago's 20 busiest bus routes average {sysm['peak']:.1f} mph at rush hour and {sysm['mid']:.1f} mph at "
               f"midday, stops included.\n{len(d['system']['other_routes'])} other frequent all-day routes average {other['peak']:.1f} mph at rush. "
               f"Slowest of the 20: the {slowest['route']} {slowest['name']}, {slowest['peak_mph']:.1f}.")
    heading = fig.text(0.052, 0.945, title, va='top', color=INK, **head)
    # Fit installed fallback fonts as well as the optional condensed headline font.
    fig.canvas.draw()
    width = heading.get_window_extent(fig.canvas.get_renderer()).width
    available = fig.bbox.width * 0.90
    if width > available:
        heading.set_fontsize(heading.get_fontsize() * available / width)
    fig.text(0.055, 0.868, sub, fontsize=10.2, color=INK2, va='top', linespacing=1.45)

    # ---- Legend row -----------------------------------------------------------------------------
    ly = 0.808
    def legend_item(x, color, label, hollow=False):
        bg.scatter([x], [ly], s=70, facecolor=BG if hollow else color, edgecolor=color if hollow else BG,
                   lw=1.8 if hollow else 1.2, zorder=5)
        fig.text(x + 0.016, ly, label, fontsize=9.4, va='center', color=INK)
    if args.variant == 'three':
        legend_item(0.062, AMC, 'Morning rush 7–9 AM', hollow=True)
        legend_item(0.372, BLUE, 'Midday 10 AM–2 PM')
        legend_item(0.664, ORANGE, 'Evening rush 4–6 PM')
    else:
        legend_item(0.062, BLUE, 'Midday 10 AM–2 PM')
        legend_item(0.372, ORANGE, 'Rush hour 7–9 AM & 4–6 PM')

    # ---- Chart ----------------------------------------------------------------------------------
    left, right = 0.295, 0.80
    top, bottom = 0.752, 0.142
    ax = fig.add_axes([left, bottom, right - left, top - bottom], facecolor='none', zorder=1)
    xmin, xmax = 5.5, 11.0
    ax.set_xlim(xmin, xmax)
    ax.set_ylim(n - 0.5, -0.5)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.set_yticks([])
    ticks = [6, 7, 8, 9, 10, 11]
    ax.set_xticks(ticks)
    ax.set_xticklabels([f'{t} mph' for t in ticks], fontsize=8.6, color=MUTED)
    ax.tick_params(axis='x', length=0, pad=6)
    ax.xaxis.set_ticks_position('bottom')
    for t in ticks:
        ax.axvline(t, color=GRID, lw=0.8, zorder=0)

    # Row bands span the full figure width for readability.
    row_h = (top - bottom) / n
    for i, r in enumerate(rows):
        yc = top - (i + 0.5) * row_h
        if i % 2 == 0:
            bg.add_patch(matplotlib.patches.Rectangle((0.04, yc - row_h / 2), 0.92, row_h,
                         facecolor=BAND, edgecolor='none', zorder=0))
        # Route badge + name
        bx, bw, bh = 0.055, 0.052, row_h * 0.66
        bg.add_patch(FancyBboxPatch((bx, yc - bh / 2), bw, bh, boxstyle='round,pad=0,rounding_size=0.006',
                     facecolor=INK, edgecolor='none', zorder=3))
        fig.text(bx + bw / 2, yc, r['route'], fontsize=10, color='white', weight='bold', ha='center',
                 va='center', zorder=4)
        name = r['name'].replace('Inner Lake Shore/Michigan Express', 'Inner Lake Shore Exp.')
        fig.text(bx + bw + 0.012, yc, name, fontsize=9.6, color=INK, va='center')
        # Right columns
        fig.text(0.858, yc, f"{r['avg_weekday_rides'] / 1000:.1f}k", fontsize=9.4, color=INK2,
                 ha='right', va='center')
        slow = 1 - r[key] / r['mid_mph']
        pct_txt = '0%' if round(slow * 100) == 0 else f"{'−' if slow > 0 else '+'}{abs(slow) * 100:.0f}%"
        fig.text(0.945, yc, pct_txt, fontsize=9.6, ha='right', va='center',
                 color=INK, weight='bold' if slow >= 0.15 else 'normal')

        # Marks
        if args.variant == 'three':
            vals = [r['am_mph'], r['mid_mph'], r['pm_mph']]
            ax.plot([min(vals), max(vals)], [i, i], color='#cfccc2', lw=1.6, zorder=1, solid_capstyle='round')
            ax.scatter([r['am_mph']], [i], s=46, facecolor=BG, edgecolor=AMC, lw=1.6, zorder=3)
            ax.scatter([r['mid_mph']], [i], s=52, color=BLUE, edgecolor=BG, lw=1.2, zorder=4)
            ax.scatter([r['pm_mph']], [i], s=60, color=ORANGE, edgecolor=BG, lw=1.2, zorder=5)
        else:
            ax.annotate('', xy=(r['peak_mph'] + 0.07, i), xytext=(r['mid_mph'] - 0.06, i),
                        arrowprops=dict(arrowstyle='-', color='#f3b49b', lw=2.2), zorder=1)
            ax.scatter([r['mid_mph']], [i], s=52, color=BLUE, edgecolor=BG, lw=1.2, zorder=4)
            ax.scatter([r['peak_mph']], [i], s=60, color=ORANGE, edgecolor=BG, lw=1.2, zorder=5)
        ax.text(r[key] - 0.16, i, f"{r[key]:.1f}", fontsize=8.4, color=INK, ha='right', va='center',
                weight='bold', zorder=6)

    # Column headers
    hy = top + 0.006
    fig.text(0.858, hy, 'Weekday\nriders', fontsize=7.6, color=MUTED, ha='right', va='bottom', linespacing=1.15)
    fig.text(0.945, hy, 'Rush vs\nmidday' if args.variant == 'dumbbell' else 'PM vs\nmidday',
             fontsize=7.6, color=MUTED, ha='right', va='bottom', linespacing=1.15)
    fig.text(0.055, hy, 'Route  (slowest at top)', fontsize=7.6, color=MUTED, va='bottom')

    # ---- Footer ---------------------------------------------------------------------------------
    m = d['meta']
    foot = ("Average speed with stops included: distance along the route ÷ time, counting stops and red lights, not layovers at the ends of the line.\n"
            f"Rush and midday compare the same street segments. {len(m['service_days'])} weekdays, Sep 28–Oct 30, 2026 (outage days and the Oct 12 holiday removed).\n"
            "Rush is clearly slower than midday on 19 of 20 routes (not the 4); the evening rush alone is slower on all 20. Data: CTA Bus Tracker via\n"
            "chicagotransitalerts.app; CTA ridership, average weekday Sep 2025–Aug 2026 (Chicago Data Portal). Other routes: frequent all-day, non-express routes.")
    fig.text(0.055, 0.112, foot, fontsize=6.6, color=MUTED, va='top', linespacing=1.5)
    bg.plot([0.055, 0.945], [0.046, 0.046], color=GRID, lw=0.8)
    fig.text(0.055, 0.02, args.handle, fontsize=9.8, color=INK, weight='bold', va='bottom')
    fig.text(0.945, 0.02, 'Open data · Reproducible SQL', fontsize=8.4,
             color=INK2, ha='right', va='bottom')

    args.out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.out, dpi=200, facecolor=BG, metadata={'Software': None})
    print(args.out)


if __name__ == '__main__':
    main()
