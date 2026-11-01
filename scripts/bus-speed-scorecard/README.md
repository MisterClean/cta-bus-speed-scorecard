# Bus speed scorecard pipeline

Builds `data/bus-speed-scorecard/` and the `images/cta-bus-speed-*.png` graphics from a DuckDB archive created by `scripts/transit_archive.py`. See `docs/bus-speed-scorecard.md` for the method, decisions and refresh steps.

| File | Role |
|---|---|
| `scorecard.sql` | The whole speed computation, as TEMP tables (the archive database is opened read-only) |
| `build.py` | Chooses service days, runs the SQL in route batches, derives period/hourly/daily figures, bootstrap intervals, sensitivity runs, slowest stretches and the web data files |
| `route_names.csv` | Route names, the street each route mostly runs on, and its axis (used to name slowest stretches) |
| `render_social.py` | 4:5 Bluesky graphic (`--variant dumbbell` is published; `three` shows AM/midday/PM) |
| `render_map.py` | 4:5 corridor speed map |
| `render_card.py` | 1200×630 link-preview card |
| `bundle_artifact.py` | Inlines the page, CSS, data and JS into one HTML file |

Requirements and full setup: see the root README.
