import datetime as dt
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest
from html.parser import HTMLParser

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import transit_archive as archive
spec = importlib.util.spec_from_file_location('scorecard', ROOT / 'scripts/bus-speed-scorecard/build.py')
scorecard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scorecard)


class AnalysisTests(unittest.TestCase):
    def test_weighted_speed_and_zero_distance_bootstrap(self):
        # Equal-distance cells at 10 and 20 mph must produce 13 1/3, not 15 mph.
        F = np.array([[5280., 0.], [0., 5280.]])
        S = np.array([[360., 0.], [0., 180.]])
        w = np.array([5280., 5280.])
        self.assertAlmostEqual(scorecard.FixedSegments._speed(F, S, w), 40 / 3)
        resampled = scorecard.FixedSegments._speed(F, S, w, np.array([[2., 0.], [0., 2.]]))
        np.testing.assert_allclose(resampled, [40 / 3, 40 / 3])

    def test_ingest_checksums_idempotency_and_sql_read_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            day = '2026-10-30'
            start = archive.calendar_bounds(day)[0] + 8 * 3600000
            # >=30 trips qualifies the pattern. Each interval is 880 ft / 60 s = 10 mph.
            rows = [dict(ts=start + i * 60000, vehicle_ts=start + i * 60000,
                         route='66', vehicle_id=str(trip), pid='p1',
                         sched_start_date=day, sched_start_sec=28800,
                         destination='Test', pdist=i * 880., lat=41.9 + i * .0024,
                         lon=-87.7, heading=0) for trip in range(35) for i in range(20)]
            path = root / 'bus-2026-10-30.ndjson.gz'
            with gzip.open(path, 'wt') as f:
                for row in rows:
                    f.write(json.dumps(row) + '\n')
            meta = dict(kind='bus', date=day, path='positions/bus/2026/10/2026-10-30.ndjson.gz',
                        rows=len(rows), bytes=path.stat().st_size, sha256=archive.file_hash(path))
            db = root / 'test.duckdb'
            con = archive.connect(db, threads=2)
            archive.initialize(con)
            with self.assertRaisesRegex(ValueError, 'manifest verification'):
                archive.ingest_file(con, dict(meta, sha256='0' * 64), path)
            self.assertEqual(archive.ingest_file(con, meta, path)['status'], 'ingested')
            self.assertEqual(archive.ingest_file(con, meta, path)['status'], 'skipped')
            self.assertEqual(con.execute('SELECT count(*) FROM positions_raw').fetchone()[0], len(rows))
            con.close()
            before = archive.file_hash(db)
            con = archive.connect(db, read_only=True, threads=2)
            out = scorecard.run_pipeline(con, [dt.date.fromisoformat(day)])
            result = out['out_route_day_hour']
            self.assertFalse(result.empty)
            self.assertAlmostEqual(scorecard.mph(result.feet.sum(), result.seconds.sum()), 10)
            # First/last fixes are trimmed, preserving ordinary in-service intervals.
            self.assertEqual(result.pairs.sum(), 35 * 18)
            con.close()
            self.assertEqual(before, archive.file_hash(db))

    def test_dst_and_incomplete_archive_rejection(self):
        a, b = archive.calendar_bounds('2026-11-01')
        self.assertEqual((b-a) / 3600000, 25)
        with self.assertRaisesRegex(ValueError, 'not complete'):
            archive.select_files({'days': []}, end='2026-10-30', as_of='2026-10-30')
        with self.assertRaisesRegex(ValueError, 'not published'):
            archive.select_files({'days': []}, end='2026-10-30', days=1, as_of='2026-10-31')


class DistributionTests(unittest.TestCase):
    def test_snapshot_and_sql_agree(self):
        d = json.loads((ROOT / 'data/bus-speed-scorecard/scorecard.json').read_text())
        self.assertEqual(d['meta']['sql'], scorecard.SQL.read_text())
        self.assertEqual(len(d['routes']), 20)
        self.assertEqual(len(d['meta']['service_days']), 20)
        for row in d['routes']:
            for period in ['am', 'pm', 'mid', 'peak']:
                self.assertGreater(row[period + '_mph'], 0)
                lo, hi = row[period + '_ci']
                self.assertLessEqual(lo, hi)

    def test_local_html_assets_resolve(self):
        class Links(HTMLParser):
            def handle_starttag(self, tag, attrs):
                for key, value in attrs:
                    if key in ('href', 'src') and value and not re.match(r'(?:https?:|#|mailto:)', value):
                        target = value.split('?')[0].split('#')[0]
                        self_check.assertTrue((ROOT / target).exists(), target)
        self_check = self
        Links().feed((ROOT / 'index.html').read_text())

    def test_no_personal_paths_or_common_credentials(self):
        # Scan distributable source/data/docs; not a substitute for a release review.
        patterns = [r'/(?:Users|home|Volumes|private/var)/[A-Za-z0-9_.-]+',
                    r'[A-Z]:\\Users\\[^\\\s]+', r'gh[pousr]_[A-Za-z0-9]{30,}',
                    r'github_pat_[A-Za-z0-9_]{40,}', r'AKIA[0-9A-Z]{16}',
                    r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----']
        for folder in ['scripts', 'docs', 'data']:
            for path in (ROOT / folder).rglob('*'):
                if path.is_file() and '__pycache__' not in path.parts:
                    text = path.read_text()
                    for pattern in patterns:
                        self.assertIsNone(re.search(pattern, text), str(path.relative_to(ROOT)))
