import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

from joblake.data_health import QUERIES, collect_report, render_markdown, save_report


class DataHealthTests(unittest.TestCase):
    def connection(self, overrides=None):
        connection = MagicMock()
        at = datetime(2026, 9, 20, 0, tzinfo=timezone.utc)
        rows = {name: [] for name in QUERIES}
        rows.update(overrides or {})
        def execute(query, params=None):
            cursor = MagicMock()
            if query.startswith('SELECT CURRENT_TIMESTAMP'):
                cursor.fetchone.return_value = {'at': at}
            elif params is not None:
                name = next(name for name, sql in QUERIES.items() if sql == query)
                cursor.fetchall.return_value = rows[name]
            return cursor
        connection.execute.side_effect = execute
        return connection

    def test_empty_source_remains_visible_and_window_is_fixed(self):
        connection = self.connection({'inventory': [{'source': 'topcv', 'total_jobs': 2}]})
        report = collect_report(connection, ['topcv', 'itviec'])
        self.assertEqual(report['sources_without_jobs'], ['itviec'])
        self.assertEqual((report['captured_at']-report['window_start']).total_seconds(), 86400)
        self.assertIn('REPEATABLE READ READ ONLY', connection.execute.call_args_list[0].args[0])
        for call in connection.execute.call_args_list[2:]:
            self.assertEqual(call.args[1]['at'], report['captured_at'])

    def test_missing_field_percent_uses_current_parse_denominator(self):
        report = collect_report(self.connection({'completeness': [
            {'source': 'topcv', 'current_parses': 4, 'missing_title': 1}]}), ['topcv'])
        self.assertEqual(report['sections']['completeness'][0]['missing_title_pct'], 25)

    def test_historical_failures_do_not_count_as_current_errors(self):
        report = collect_report(self.connection({
            'inventory': [{'source': 'topcv', 'total_jobs': 10}],
            'current_fetch_errors': [{'source': 'topcv', 'jobs': 2}],
            'current_parse_status': [{'source': 'topcv', 'status': 'success', 'jobs': 8}],
            'fetch_attempts_in_window': [{'source': 'topcv', 'status': 'fetch_error', 'attempts': 20}],
        }), ['topcv', 'empty'])
        summary = {row['source']: row for row in report['sections']['summary']}
        self.assertEqual(summary['topcv']['current_fetch_errors'], 2)
        self.assertEqual(summary['topcv']['current_fetch_error_pct'], 20)
        self.assertEqual(summary['topcv']['latest_parse_errors'], 0)
        self.assertIsNone(summary['empty']['current_fetch_error_pct'])

    def test_query_failure_is_not_silently_reported_as_empty(self):
        connection = self.connection()
        execute = connection.execute.side_effect
        def fail(query, params=None):
            if query == QUERIES['quality']:
                raise RuntimeError('query failed')
            return execute(query, params)
        connection.execute.side_effect = fail
        with self.assertRaisesRegex(RuntimeError, 'query failed'):
            collect_report(connection, ['topcv'])

    def test_reports_are_readable_unique_and_escape_table_cells(self):
        report = collect_report(self.connection(), ['topcv'])
        report['sections']['example'] = [{'value': 'a|b\nc'}]
        self.assertIn('a\\|b c', render_markdown(report))
        with tempfile.TemporaryDirectory() as directory:
            first = save_report(report, directory)
            second = save_report(report, directory)
            self.assertNotEqual(first, second)
            payload = json.loads(first[0].read_text(encoding='utf-8'))
            self.assertEqual(payload['sources'], ['topcv'])
            self.assertTrue(first[1].read_text(encoding='utf-8').startswith('# JobLake'))
            self.assertFalse(list(Path(directory).glob('*.tmp')))


if __name__ == '__main__':
    unittest.main()
