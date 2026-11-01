#!/usr/bin/env python3
"""Bundle the scorecard page into one self-contained HTML file (inline CSS, data and JS).

  python -I scripts/bus-speed-scorecard/bundle_artifact.py --out /path/to/cta-bus-speed-scorecard.bundle.html

The bundle is a complete HTML document and sets window.BUS_SCORECARD so the page
script skips its fetches. Download links use --link-base.
"""
import argparse
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=True, type=Path)
    ap.add_argument('--link-base', default='./')
    a = ap.parse_args()
    if a.link_base and not a.link_base.endswith("/"):
        a.link_base += "/"
    html = (ROOT / 'index.html').read_text()
    css = (ROOT / 'cta-bus-speed-scorecard.css').read_text()
    js = (ROOT / 'cta-bus-speed-scorecard.js').read_text()
    css += '\nbody { background: var(--bg); margin: 0; }\n'
    data_dir = ROOT / 'data/bus-speed-scorecard'
    data = dict(scorecard=json.loads((data_dir / 'scorecard.json').read_text()),
                cells=json.loads((data_dir / 'map_cells.json').read_text()),
                outline=json.loads((data_dir / 'chicago-outline.json').read_text()))
    payload = json.dumps(data, separators=(',', ':')).replace('</', '<\\/')
    body = re.search(r'<body[^>]*>(.*)</body>', html, re.S).group(1)
    body = body.replace('<!--BUNDLE:HEAD-->', '').replace('<!--BUNDLE:DATA-->', '')
    body = re.sub(r'href="(images/[^"]+|data/[^"]+)"', lambda m: f'href="{a.link_base}{m.group(1)}"', body)
    out = '\n'.join([
        '<!doctype html><html lang="en"><head><meta charset="utf-8"><title>CTA Bus Speed Scorecard</title>',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f'<style>\n{css}\n</style>',
        '</head><body><div class="bus-page">',
        body,
        '</div>',
        f'<script>window.BUS_SCORECARD={payload};window.BUS_SCORECARD_LINK_BASE={json.dumps(a.link_base)};</script>',
        f'<script>\n{js}\n</script></body></html>',
    ])
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(out)
    print(a.out, f'{len(out) / 1024:.0f} KB')


if __name__ == '__main__':
    main()
