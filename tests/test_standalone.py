"""Runner contracts without network, browser, live databases or publication."""
from copy import deepcopy
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import yaml

from joblake.standalone import Runner, load_config, runner_lock, configure_database, main, save_json


class StandaloneTests(unittest.TestCase):
    def setUp(self):
        self.config = load_config('orchestration/standalone/config.yaml')
        self.config['cleanup']['enabled'] = False
        self.config['sync']['enabled'] = True
        self.config['enrichment']['enabled'] = True
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def runner(self):
        return Runner(deepcopy(self.config), directory=self.root)

    @staticmethod
    def fake_execute(runner, failures=None):
        failures = failures or {}

        def execute(label, arguments, timeout, retries=0, browser=False):
            code = failures.get(label, 0)
            with runner.results_lock:
                runner.results.append({'task': label, 'exit_code': code})
            return code
        return execute

    def test_three_slots_and_each_source_phase_order(self):
        runner = self.runner()
        barrier = threading.Barrier(3)
        active = peak = 0
        lock = threading.Lock()
        order = {}

        def execute(label, *args, **kwargs):
            nonlocal active, peak
            source, phase = label.split('.')
            with lock:
                active += 1
                peak = max(peak, active)
                order.setdefault(source, []).append(phase)
            if phase == 'discovery':
                barrier.wait(timeout=5)
            time.sleep(0.005)
            with lock:
                active -= 1
            return 0

        with patch.object(runner, 'execute', side_effect=execute), \
                patch.object(runner, 'health', return_value=False):
            runner.cycle()
        self.assertEqual(peak, 3)
        self.assertEqual(len(order), 9)
        self.assertTrue(all(phases == ['discovery', 'detail', 'parse'] for phases in order.values()))

    def test_failed_discovery_drains_backlog_but_blocks_publication(self):
        runner = self.runner()
        with patch.object(runner, 'execute', side_effect=self.fake_execute(runner, {'topcv.discovery': 1})), \
                patch.object(runner, 'health', return_value=True) as health:
            state = runner.cycle()
        labels = [row['task'] for row in state['tasks']]
        self.assertIn('topcv.detail', labels)
        self.assertIn('topcv.parse', labels)
        self.assertIn('jobsgo.parse', labels)
        self.assertNotIn('sync.publish', labels)
        self.assertNotIn('enrichment', labels)
        self.assertEqual(state['status'], 'failed')
        health.assert_called_once()

    def test_global_tasks_follow_all_sources_and_enrichment_failure_allows_sync(self):
        runner = self.runner()
        def health():
            self.assertEqual(len(runner.results), 27)
            return True
        with patch.object(runner, 'execute', side_effect=self.fake_execute(runner, {'enrichment': 1})), \
                patch.object(runner, 'health', side_effect=health):
            state = runner.cycle()
        self.assertEqual([row['task'] for row in state['tasks']][-3:],
                         ['enrichment', 'sync.connection', 'sync.publish'])
        self.assertEqual(state['status'], 'failed')  # Never hide the AI failure.
        self.assertEqual(json.loads((self.root / 'latest.json').read_text()), state)
        self.assertGreater(state['next_run_at'], time.time())

    def test_failed_report_does_not_check_stale_report(self):
        runner = self.runner()
        runner.config['sources'] = ['topdev']
        calls = []
        def execute(label, arguments, *args):
            calls.append(label)
            directory = Path(arguments[arguments.index('--config-dir') + 1])
            self.assertEqual([p.name for p in directory.glob('*.yaml')], ['topdev.yaml'])
            return 1
        with patch.object(runner, 'execute', side_effect=execute):
            self.assertFalse(runner.health())
        self.assertEqual(calls, ['health.report'])

    def test_health_failure_blocks_sync_and_cleanup_remains_independent(self):
        runner = self.runner()
        runner.config['cleanup']['enabled'] = True
        with patch.object(runner, 'execute', side_effect=self.fake_execute(runner, {'health.gate': 1})):
            state = runner.cycle()
        labels = [row['task'] for row in state['tasks']]
        self.assertIn('health.gate', labels)
        self.assertNotIn('sync.publish', labels)
        self.assertEqual(labels[-1], 'cleanup')
        self.assertGreater(state['last_cleanup_at'], 0)
        with patch.object(runner, 'execute', side_effect=self.fake_execute(runner)), \
                patch.object(runner, 'health', return_value=True):
            second = runner.cycle(state)
        self.assertNotIn('cleanup', [row['task'] for row in second['tasks']])

    def test_sync_connection_failure_does_not_publish(self):
        runner = self.runner()
        with patch.object(runner, 'execute', side_effect=self.fake_execute(runner, {'sync.connection': 1})), \
                patch.object(runner, 'health', return_value=True):
            state = runner.cycle()
        self.assertNotIn('sync.publish', [row['task'] for row in state['tasks']])
        self.assertEqual(state['status'], 'failed')

    def test_lock_excludes_second_runner_and_releases(self):
        with runner_lock(self.root):
            with self.assertRaises(RuntimeError):
                with runner_lock(self.root):
                    self.fail('Second runner acquired the lock')
        with runner_lock(self.root):
            pass

    def test_invalid_config_and_subset_sync_rejected(self):
        for key, value in [('sources', ['topcv', 'topcv']), ('max_concurrent_sources', True),
                           ('phase_timeout_seconds', 0), ('sources', ['../topcv']),
                           ('sources', ['topcv'])]:
            with self.subTest(key=key, value=value):
                config = deepcopy(self.config)
                config[key] = value
                path = self.root / 'runner.yaml'
                path.write_text(yaml.safe_dump(config), encoding='utf-8')
                with self.assertRaises(ValueError):
                    load_config(path)

    def test_local_database_url_uses_internal_port_and_escaped_credentials(self):
        from psycopg.conninfo import conninfo_to_dict
        environment = dict(POSTGRES_HOST='postgres', POSTGRES_PORT='5432',
                           POSTGRES_DB='joblake', POSTGRES_USER='joblake',
                           POSTGRES_PASSWORD="quote' and @ password", LOCAL_DATABASE_URL='old')
        with patch.dict(os.environ, environment, clear=True):
            configure_database()
            actual = conninfo_to_dict(os.environ['LOCAL_DATABASE_URL'])
        self.assertEqual(actual['host'], 'postgres')
        self.assertEqual(actual['port'], '5432')
        self.assertEqual(actual['password'], environment['POSTGRES_PASSWORD'])

    def test_subprocess_retry_and_timeout(self):
        runner = self.runner()
        runner.config['retry_delay_seconds'] = 0
        code = runner.execute('failure', ['module_that_does_not_exist_joblake'], 5, retries=1)
        self.assertNotEqual(code, 0)
        self.assertEqual(runner.results[-1]['attempts'], 2)
        # Real sleeping process: verify timeout termination, not only mocked call order.
        sleeper = self.root / 'standalone_test_sleeper.py'
        sleeper.write_text('import time\ntime.sleep(60)\n', encoding='utf-8')
        real_popen = subprocess.Popen
        def launch(_command, **kwargs):
            return real_popen([sys.executable, str(sleeper)], **kwargs)
        with patch('joblake.standalone.subprocess.Popen', side_effect=launch):
            code = runner.execute('timeout', ['unused'], 0.1)
        self.assertEqual(code, 124)

    def test_shutdown_stops_running_process_and_remaining_phases(self):
        runner = self.runner()
        sleeper = self.root / 'sleeper.py'
        sleeper.write_text('import time\ntime.sleep(60)\n', encoding='utf-8')
        real_popen = subprocess.Popen
        launched = threading.Event()
        def launch(_command, **kwargs):
            process = real_popen([sys.executable, str(sleeper)], **kwargs)
            launched.set()
            return process
        def stop_after_launch():
            if launched.wait(5):
                runner.stop.set()
        stopper = threading.Thread(target=stop_after_launch)
        stopper.start()
        with patch('joblake.standalone.subprocess.Popen', side_effect=launch):
            self.assertFalse(runner.source('topdev'))
        stopper.join(timeout=6)
        self.assertEqual(len(runner.results), 1)
        self.assertEqual(runner.results[0]['exit_code'], 130)

    def test_restart_waits_for_persisted_schedule_without_crawling(self):
        save_json(self.root / 'latest.json', {'next_run_at': time.time() + 3600})
        handlers = {}
        def register(signum, handler):
            handlers[signum] = handler
        def stop_soon(*args):
            timer = threading.Timer(0.05, lambda: handlers[signal.SIGTERM]())
            timer.start()
            self.addCleanup(timer.join)
            return True
        with patch('joblake.standalone.STATE', self.root), \
                patch('joblake.standalone.signal.signal', side_effect=register), \
                patch('joblake.standalone.configure_database'), \
                patch('joblake.standalone.wait_services', side_effect=stop_soon), \
                patch.object(Runner, 'cycle') as cycle:
            self.assertEqual(main(['schedule']), 130)
        cycle.assert_not_called()

    def test_interrupted_cycle_is_due_on_restart(self):
        runner = self.runner()
        runner.stop.set()
        state = runner.cycle()
        self.assertEqual(state['status'], 'interrupted')
        self.assertLessEqual(state['next_run_at'], time.time())


if __name__ == '__main__':
    unittest.main()
