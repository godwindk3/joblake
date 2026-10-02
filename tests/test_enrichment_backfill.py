"""Backfill parameter/CLI contracts; no model calls or production database writes."""
import json
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from joblake import main as cli
from joblake.enrichment.backfill import VIETNAM, normalize, selection_query


class BackfillOptionsTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 2, 10, tzinfo=VIETNAM)

    def test_default_window_is_relative_and_replayable(self):
        options = normalize({}, now=self.now)
        self.assertTrue(options['dry_run'])
        self.assertEqual(options['date_field'], 'first_seen_at')
        self.assertEqual(options['date_to'], self.now.isoformat())
        self.assertEqual(options['date_from'], (self.now - timedelta(days=30)).isoformat())
        self.assertEqual(normalize(options, now=self.now + timedelta(days=10)), options)

    def test_dates_override_lookback_and_use_vietnam_midnight(self):
        options = normalize(dict(date_from='2026-08-01', date_to='2026-09-01', lookback_days=1), now=self.now)
        self.assertEqual(options['date_from'], '2026-08-01T00:00:00+07:00')
        self.assertEqual(options['date_to'], '2026-09-01T00:00:00+07:00')

    def test_invalid_filters_fail_closed(self):
        cases = [dict(max_jobs=0), dict(max_api_attempts=True), dict(dry_run='false'),
                 dict(posting_ids=[True]), dict(posting_ids=[0]), dict(sources='topcv'),
                 dict(date_field='r.title; DROP TABLE x'), dict(sort_order='random'),
                 dict(date_from='2026-11-01'), dict(date_to='2026-11-01'),
                 dict(date_from='2026-09-01', date_to='2026-09-01'),
                 dict(lookback_days=-1), dict(unknown=True)]
        for value in cases:
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize(value, now=self.now)

    def test_source_values_are_bound_not_sql(self):
        malicious = "x'); DROP TABLE core.job_enrichments; --"
        query, params = selection_query(normalize(dict(sources=[malicious]), now=self.now))
        self.assertNotIn(malicious, query.as_string())
        self.assertIn([malicious], params)

    def invoke(self, args):
        with patch('sys.argv', ['joblake', '--phase', 'enrich-backfill', *args]), patch.object(
                cli, 'load_dotenv'), patch('joblake.enrichment.backfill.run', return_value=0) as run:
            with self.assertRaises(SystemExit) as result:
                cli.main()
            self.assertEqual(result.exception.code, 0)
            return run.call_args.kwargs['options']

    def test_cli_preview_default_and_explicit_execution(self):
        self.assertTrue(normalize(self.invoke([]))['dry_run'])
        options = self.invoke(['--execute', '--max-jobs', '20', '--max-api-attempts', '10',
                               '--sources', 'topcv', 'itviec', '--posting-ids', '1', '2'])
        self.assertFalse(options['dry_run'])
        self.assertEqual(options['max_jobs'], 20)
        self.assertEqual(options['max_api_attempts'], 10)
        self.assertEqual(options['posting_ids'], [1, 2])

    def test_dry_run_flag_overrides_airflow_json(self):
        options = self.invoke(['--backfill-options', json.dumps(dict(dry_run=False)), '--dry-run'])
        self.assertTrue(options['dry_run'])


if __name__ == '__main__':
    unittest.main()
