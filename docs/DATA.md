# Data contract and provenance

## Sources and rights

Positions: [Chicago Transit Alerts archive](https://data.chicagotransitalerts.app/positions/index.json), collected from CTA Bus Tracker by [chicago-transit-insights](https://github.com/cailinpitt/chicago-transit-insights). Source checksums, sizes, row counts and dates are in `data/bus-speed-scorecard/source_manifest.csv`.

Ridership: [CTA daily bus route totals, Chicago Data Portal](https://data.cityofchicago.org/d/jyb9-n7fm). Fields used: `date`, `route`, `daytype`, `rides`; weekday ranking uses `daytype = 'W'` and September 2025–August 2026. The exact input SHA-256 and date span are recorded in `scorecard.json` metadata. A fresh portal download may reflect later revisions; matching dates alone does not guarantee the same bytes.

Geometry: Chicago Data Portal ward boundaries, included as `data/chicago-wards.geojson`, used only for the city silhouette. Inspect the original metadata and [Chicago Data Portal terms](https://www.chicago.gov/city/en/narr/foia/data_disclaimer.html) before downstream redistribution.

The MIT license covers project code and authored documentation/graphics. It does **not** relicense CTA, archive-provider or Chicago source data, boundaries, or rights in them. Derived data remains subject to applicable source terms. No affiliation or endorsement is implied.

The scorecard pipeline and report were extracted from their author's website with a new history. The included archive helper was adapted from the same author's `ai-plugins` transit helper, revision `5423cab36dbfd47777b8b96659975ac5a4921bd9`. Historical profiling notes describe exploratory code that is not distributed here; the production SQL and tests are the maintained entrypoints.

## Database inputs

Use `scripts/transit_archive.py` to produce a compatible DuckDB database. The scorecard needs:

| Table | Required columns |
| --- | --- |
| `positions_raw` | `kind VARCHAR`, `archive_date DATE`, `route VARCHAR`, `vehicle_id VARCHAR`, `pid VARCHAR`, `sched_start_date VARCHAR`, `sched_start_sec INTEGER`, `vehicle_ts BIGINT`, `ts BIGINT`, `pdist DOUBLE`, `lat DOUBLE`, `lon DOUBLE`, `destination VARCHAR` |
| `archive_ingest` | `kind VARCHAR`, `archive_date DATE`, `sha256 VARCHAR`, `rows BIGINT`, `bytes BIGINT` |

Bus timestamps are Unix **milliseconds**. `pdist` is feet along a single pattern, not a straight-line distance. `archive_date` is the America/Chicago date; `sched_start_date` is ISO YYYY-MM-DD. Route and vehicle identifiers must remain strings. The importer also builds normalized views and coverage tables for audits. Its `archive_ingest.local_path` is local provenance only and is excluded from published manifests.

## Published outputs

The files in `data/bus-speed-scorecard/` are aggregate study outputs. `scorecard.json` has `meta`, `system`, `routes`, `all_routes`, `express` and `sensitivity`. Metadata includes SQL, source manifest, service-day exclusions and ridership checksum. Speeds are mph, distances feet unless the field names say otherwise, and time sums seconds. `corridor_cells.csv` aggregates route × period × ~220 m cell; `route_day_hour.csv` aggregates route × local date × hour. No passenger data or local database is included.

Rebuilds preserve sorted numeric tables; `meta.generated_at` changes on every build. The dated prose and graphics are not a generic automatically refreshed reporting template.

`docs/bus-speed-scorecard/day_inclusion_audit.csv` is the historical **strict 17-day** coverage audit, not the main 20-day sample; `scorecard.json.meta.service_days` is authoritative for the published results.
