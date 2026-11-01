#!/usr/bin/env python3
"""Render the 1200x630 link-preview card (og:image) from scorecard.json.

  python -I scripts/bus-speed-scorecard/render_card.py --data data/bus-speed-scorecard/scorecard.json \
      --out images/cta-bus-speed-scorecard-card.png [--headline-font path.ttf]
"""
import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager as fm

BG, INK, INK2, MUTED, BLUE, ORANGE, LINE = '#fbfaf7', '#0b0b0b', '#52514e', '#898781', '#2a78d6', '#eb6834', '#e4e2da'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--data', required=True, type=Path)
    ap.add_argument('--out', required=True, type=Path)
    ap.add_argument('--headline-font', type=Path)
    a = ap.parse_args()
    d = json.loads(a.data.read_text())
    s, o = d['system']['top20_pooled'], d['system']['other_routes_pooled']
    have = {f.name for f in fm.fontManager.ttflist}
    sans = next((n for n in ['Helvetica Neue', 'Helvetica', 'Arial'] if n in have), 'DejaVu Sans')
    plt.rcParams.update({'font.family': sans})
    head = fm.FontProperties(fname=str(a.headline_font), size=44) if a.headline_font and a.headline_font.exists() \
        else fm.FontProperties(family=sans, weight='bold', size=34)
    fig = plt.figure(figsize=(6, 3.15), dpi=200, facecolor=BG)
    fig.text(0.06, 0.88, "CTA BUS SPEED SCORECARD", fontsize=8, color=ORANGE, weight='bold', va='top')
    fig.text(0.055, 0.82, 'HOW FAST IS\nYOUR BUS?', va='top', color=INK, fontproperties=head, linespacing=0.9)
    fig.text(0.06, 0.22, "Chicago's 20 busiest bus routes, average speed\nwith stops included, 20 weekdays in fall 2026", fontsize=8.4, color=INK2,
             va='bottom', linespacing=1.4)
    items = [(f"{s['peak']:.1f}", 'mph at rush hour', ORANGE), (f"{s['mid']:.1f}", 'mph at midday', BLUE),
             (f"{o['peak']:.1f}", f"mph: {len(d['system']['other_routes'])} other frequent\nall-day routes at rush hour", INK)]
    y = 0.86
    for big, small, color in items:
        fig.text(0.6, y, big, fontsize=26, color=color, weight='bold', va='top')
        fig.text(0.6, y - 0.15, small, fontsize=7.6, color=INK2, va='top', linespacing=1.3)
        y -= 0.255
    fig.lines.append(matplotlib.lines.Line2D([0.56, 0.56], [0.12, 0.86], transform=fig.transFigure, color=LINE, lw=0.8))
    fig.text(0.06, 0.07, 'github.com/MisterClean/cta-bus-speed-scorecard', fontsize=7.4, color=MUTED, va='bottom')
    a.out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(a.out, dpi=200, facecolor=BG, metadata={'Software': None})
    print(a.out)


if __name__ == '__main__':
    main()
