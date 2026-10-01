import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from joblake.health_policy import DEFAULTS, check_latest, evaluate, load_policy, main


NOW = datetime(2026, 10, 1, tzinfo=timezone.utc)


def healthy():
    return {
        'captured_at': NOW.isoformat(), 'sources': ['topcv'],
        'sections': {
            'inventory': [{'source': 'topcv', 'total_jobs': 100, 'pending_fetch': 100, 'stuck_fetch': 0}],
            'raw_and_backlog': [{'source': 'topcv', 'awaiting_usable_parse': 100}],
            'current_parse_status': [{'source': 'topcv', 'status': 'success', 'stuck_parse': 0}],
            'freshness': [{'source': 'topcv', 'phase': phase, 'hours_since_success': 48}
                          for phase in ('discovery', 'detail', 'parse')],
            'parse_outcomes_in_window': [
                {'source': 'topcv', 'status': 'success', 'jobs': 8},
                {'source': 'topcv', 'status': 'validation_error', 'jobs': 2}],
        },
    }


class HealthPolicyTests(unittest.TestCase):
    def setUp(self):
        self.policy = {'topcv': dict(DEFAULTS)}

    def test_equal_limits_are_healthy(self):
        self.assertEqual(evaluate(healthy(), self.policy)['status'], 'ok')

    def test_missing_success_is_not_healthy_and_full_does_not_replace_parse(self):
        report = healthy()
        report['sections']['freshness'] = [
            {'source': 'topcv', 'phase': 'full', 'hours_since_success': 1}]
        result = evaluate(report, self.policy)
        self.assertEqual([a['metric'] for a in result['alerts']], ['parse_hours_since_success'])

    def test_backlog_stuck_and_parse_failures_are_independent(self):
        report = healthy()
        report['sections']['inventory'][0].update(pending_fetch=101, stuck_fetch=1)
        report['sections']['raw_and_backlog'][0]['awaiting_usable_parse'] = 101
        report['sections']['parse_outcomes_in_window'][1]['jobs'] = 3
        result = evaluate(report, self.policy)
        self.assertEqual({a['metric'] for a in result['alerts']},
                         {'pending_fetch', 'stuck_jobs', 'parse_backlog', 'parse_error_pct'})

    def test_low_volume_and_optional_fields_do_not_create_rate_alerts(self):
        report = healthy()
        report['sections']['parse_outcomes_in_window'] = [
            {'source': 'topcv', 'status': 'validation_error', 'jobs': 3}]
        report['sections']['completeness'] = [{'source': 'topcv', 'missing_salary_raw_pct': 100}]
        self.assertEqual(evaluate(report, self.policy)['status'], 'ok')

    def test_disabled_thresholds_and_source_overrides(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'policy.yaml'
            path.write_text('defaults: {freshness_hours: null}\nsources: {topcv: {max_parse_backlog: 5}}')
            policy = load_policy(path, ['topcv', 'jobsgo'])
        self.assertIsNone(policy['jobsgo']['freshness_hours'])
        self.assertEqual(policy['jobsgo']['max_parse_backlog'], 100)
        self.assertEqual(policy['topcv']['max_parse_backlog'], 5)

    def test_invalid_policy_fails_closed(self):
        for contents in ('[]', 'defaults: {typo: 1}', 'sources: {typo: {}}',
                         'defaults: {freshness_hours: .nan}', 'defaults: {max_stuck_jobs: true}',
                         'defaults: {min_parse_jobs: 0}', 'defaults: {min_parse_jobs: null}',
                         'defaults: {max_parse_error_pct: 101}'):
            with self.subTest(contents=contents), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'policy.yaml'
                path.write_text(contents)
                with self.assertRaises(ValueError):
                    load_policy(path, ['topcv'])

    def test_report_freshness_and_missing_source(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, 'No health'):
                check_latest(directory, self.policy, now=NOW)
            path = Path(directory) / '20261001.json'
            path.write_text(json.dumps(healthy()))
            self.assertEqual(check_latest(directory, self.policy, now=NOW)[1]['status'], 'ok')
            for at in (NOW + timedelta(hours=31), NOW - timedelta(hours=1)):
                with self.assertRaisesRegex(ValueError, 'stale or dated'):
                    check_latest(directory, self.policy, now=at)
            with self.assertRaisesRegex(ValueError, 'missing configured sources'):
                check_latest(directory, {'jobsgo': DEFAULTS}, now=NOW)

    def test_broken_newest_report_never_falls_back_to_older_green_report(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / '20260930.json').write_text(json.dumps(healthy()))
            (Path(directory) / '20261001.json').write_text('{')
            with self.assertRaises(ValueError):
                check_latest(directory, self.policy, now=NOW)

    def test_old_report_without_metrics_requires_regeneration(self):
        report = healthy()
        del report['sections']['parse_outcomes_in_window']
        with self.assertRaisesRegex(ValueError, 'generate a new snapshot'):
            evaluate(report, self.policy)

    def test_gate_exit_codes(self):
        for alerts, expected in (([], 0), ([dict(source='topcv', metric='stuck', observed=1, limit=0)], 1)):
            with patch('joblake.health_policy.configured_sources', return_value=['topcv']), \
                 patch('joblake.health_policy.load_policy', return_value=self.policy), \
                 patch('joblake.health_policy.check_latest', return_value=(Path('report.json'),
                       {'status': 'alert' if alerts else 'ok', 'alerts': alerts})), patch('builtins.print'):
                self.assertEqual(main([]), expected)
        with patch('joblake.health_policy.configured_sources', side_effect=ValueError('no report')), \
             patch('builtins.print'):
            self.assertEqual(main([]), 2)


if __name__ == '__main__':
    unittest.main()
