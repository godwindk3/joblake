"""Small Docker runner: bounded source concurrency and a persistent fixed-delay schedule."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time

import yaml

from joblake.logging import configure_logging

LOGGER = logging.getLogger(__name__)
STATE = Path('data/state/standalone')
DEFAULT_CONFIG = 'orchestration/standalone/config.yaml'


def load_config(path):
    config = yaml.safe_load(Path(path).read_text(encoding='utf-8'))
    required = {'sources', 'max_concurrent_sources', 'interval_seconds',
                'phase_timeout_seconds', 'phase_retries', 'retry_delay_seconds',
                'enrichment', 'sync', 'cleanup'}
    if not isinstance(config, dict) or set(config) != required:
        raise ValueError('Runner config must contain exactly: ' + ', '.join(sorted(required)))

    def integer(values, key, minimum=1, maximum=864000):
        value = values.get(key)
        if type(value) is not int or not minimum <= value <= maximum:
            raise ValueError(f'{key} must be an integer in {minimum}..{maximum}')

    integer(config, 'max_concurrent_sources', maximum=9)
    integer(config, 'phase_retries', minimum=0, maximum=10)
    for key in ('interval_seconds', 'phase_timeout_seconds', 'retry_delay_seconds'):
        integer(config, key)
    sections = {
        'enrichment': {'enabled', 'max_jobs', 'timeout_seconds'},
        'sync': {'enabled', 'timeout_seconds'},
        'cleanup': {'enabled', 'apply', 'interval_seconds', 'timeout_seconds', 'max_objects', 'max_mib'},
    }
    for section, keys in sections.items():
        values = config[section]
        if not isinstance(values, dict) or set(values) != keys:
            raise ValueError(f'Invalid {section} settings')
        for key in keys:
            if key in {'enabled', 'apply'}:
                if type(values[key]) is not bool:
                    raise ValueError(f'{section}.{key} must be a boolean')
            else:
                integer(values, key)
    sources = config['sources']
    if not isinstance(sources, list) or not sources or any(
            not isinstance(source, str) or not source.isidentifier() for source in sources):
        raise ValueError('sources must be a nonempty list of source codes')
    if len(set(sources)) != len(sources):
        raise ValueError('Duplicate sources are not allowed')
    for source in sources:
        source_config = yaml.safe_load(Path(f'configs/{source}.yaml').read_text(encoding='utf-8'))
        if source_config.get('source') != source or source_config.get('enabled') is not True:
            raise ValueError(f'Source {source} is missing, mismatched or disabled')
    # Sync reconciles ALL sources. A subset runner must never imply subset publication.
    if config['sync']['enabled']:
        from joblake.health_policy import configured_sources
        if set(sources) != set(configured_sources('configs')):
            raise ValueError('Sync requires all configured sources in the runner source list')
    return config


@contextmanager
def runner_lock(directory):
    """Kernel lock survives stale files, releases on exit, shared by once/schedule/init."""
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / 'runner.lock').open('a+b') as handle:
        handle.seek(0)
        if os.name == 'nt':
            import msvcrt
            if os.fstat(handle.fileno()).st_size == 0:
                handle.write(b'0')
                handle.flush()
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                raise RuntimeError('Another standalone runner/init is active') from None
        else:
            import fcntl
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                raise RuntimeError('Another standalone runner/init is active') from None
        try:
            yield
        finally:
            if os.name == 'nt':
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


def save_json(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2), encoding='utf-8')
    os.replace(temporary, path)


def read_state(directory):
    path = directory / 'latest.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}


def configure_database():
    # Ingestion, Alembic, enrichment and sync must all address the SAME local DB.
    from joblake.postgres import PostgresSettings
    from psycopg.conninfo import make_conninfo
    os.environ['LOCAL_DATABASE_URL'] = make_conninfo(
        **PostgresSettings.from_config().connection_kwargs())


def wait_services(stop, timeout=180):
    import psycopg
    from minio import Minio
    from urllib3 import PoolManager, Timeout
    from joblake.postgres import PostgresSettings
    deadline = time.monotonic() + timeout
    while not stop.is_set():
        try:
            with psycopg.connect(**PostgresSettings.from_config().connection_kwargs()) as connection:
                connection.execute('SELECT 1')
            client = Minio(os.environ['MINIO_ENDPOINT'],
                           access_key=os.environ['MINIO_ACCESS_KEY'],
                           secret_key=os.environ['MINIO_SECRET_KEY'], secure=False,
                           http_client=PoolManager(timeout=Timeout(connect=5, read=5), retries=False))
            client.list_buckets()
            return True
        except Exception as exc:
            # Credentials/URLs can be present in exception messages: log only the class.
            LOGGER.warning('Waiting for PostgreSQL/MinIO (%s)', type(exc).__name__)
            if time.monotonic() >= deadline:
                return False
            stop.wait(5)
    return False


class Runner:
    def __init__(self, config, stop=None, directory=STATE):
        self.config = config
        self.stop = stop if stop is not None else threading.Event()
        self.directory = directory
        self.results = []
        self.results_lock = threading.Lock()

    @staticmethod
    def terminate(process):
        if os.name == 'posix':
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        else:
            process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass
        # Reap descendants too, even if the wrapper already exited after SIGTERM.
        if os.name == 'posix':
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        elif process.poll() is None:
            process.kill()
        process.wait()

    def execute(self, label, arguments, timeout, retries=0, browser=False):
        command = [sys.executable, '-u', '-m', *arguments]
        if browser and os.name == 'posix':
            command = ['xvfb-run', '-a', *command]
        started = time.monotonic()
        code, attempts = 130, 0
        for attempt in range(retries + 1):
            if self.stop.is_set():
                break
            attempts += 1
            LOGGER.info('Task %s attempt=%s started', label, attempts)
            try:
                process = subprocess.Popen(command, start_new_session=os.name == 'posix')
            except OSError as exc:
                LOGGER.error('Task %s could not start (%s)', label, type(exc).__name__)
                code = 127
            else:
                deadline = time.monotonic() + timeout
                while process.poll() is None:
                    if self.stop.wait(0.2) or time.monotonic() >= deadline:
                        self.terminate(process)
                        code = 130 if self.stop.is_set() else 124
                        break
                else:
                    code = process.returncode
            LOGGER.info('Task %s exit=%s', label, code)
            if code == 0 or self.stop.is_set():
                break
            if attempt < retries:
                self.stop.wait(self.config['retry_delay_seconds'])
        with self.results_lock:
            self.results.append(dict(task=label, exit_code=code, attempts=attempts,
                                     seconds=round(time.monotonic() - started, 2)))
        return code

    def source(self, source):
        success = True
        for phase in ('discovery', 'detail', 'parse'):
            if self.stop.is_set():
                return False
            code = self.execute(f'{source}.{phase}',
                                ['joblake.main', '--config', f'configs/{source}.yaml',
                                 '--phase', phase, '--strict'],
                                self.config['phase_timeout_seconds'],
                                self.config['phase_retries'], browser=True)
            # Like Airflow all_done: drain detail/parse backlog even after upstream failure.
            success = code == 0 and success
        return success

    def health(self):
        # Existing CLIs discover sources from a directory. Give them a scoped view
        # without changing shared configs or disabling thresholds for missing sources.
        with tempfile.TemporaryDirectory(prefix='joblake-health-') as temporary:
            root = Path(temporary)
            configs = root / 'configs'
            configs.mkdir()
            for source in self.config['sources']:
                shutil.copyfile(f'configs/{source}.yaml', configs / f'{source}.yaml')
            from joblake.health_policy import configured_sources, load_policy
            policies = load_policy('configs/data_health.yaml', configured_sources('configs'))
            thresholds = root / 'thresholds.yaml'
            thresholds.write_text(yaml.safe_dump({'sources': {
                source: policies[source] for source in self.config['sources']}}), encoding='utf-8')
            common = ['--config-dir', str(configs), '--thresholds', str(thresholds),
                      '--output-dir', str(self.directory / 'health')]
            report = self.execute('health.report', ['joblake.data_health', *common], 1200)
            if report != 0:
                return False  # Never evaluate an older report after generation failed.
            return self.execute('health.gate', ['joblake.health_policy', *common,
                                               '--max-report-age-hours', '1'], 120) == 0

    def cycle(self, previous=None):
        self.results = []
        previous = previous or {}
        started = datetime.now(timezone.utc).isoformat()
        with ThreadPoolExecutor(max_workers=self.config['max_concurrent_sources']) as pool:
            futures = [pool.submit(self.source, source) for source in self.config['sources']]
            ingestion_ok = True
            for future in as_completed(futures):
                ingestion_ok = future.result() and ingestion_ok
        health_ok = self.health() if not self.stop.is_set() else False
        publish_ok = ingestion_ok and health_ok and not self.stop.is_set()
        enrichment = self.config['enrichment']
        if publish_ok and enrichment['enabled']:
            # Persistent enrichment queue owns retries. No outer retries/API replay.
            code = self.execute('enrichment', ['joblake.main', '--phase', 'enrich',
                                '--max-jobs', str(enrichment['max_jobs'])], enrichment['timeout_seconds'])
            if code:
                LOGGER.warning('Enrichment incomplete; valid base jobs may still be synced')
        sync = self.config['sync']
        if publish_ok and sync['enabled'] and not self.stop.is_set():
            if self.execute('sync.connection', ['joblake.main', '--phase', 'supabase-test'], 120,
                            self.config['phase_retries']) == 0:
                self.execute('sync.publish', ['joblake.main', '--phase', 'supabase-sync'],
                             sync['timeout_seconds'], self.config['phase_retries'])
        elif not publish_ok:
            LOGGER.warning('Publication skipped: ingestion or health failed')
        cleanup_at = previous.get('last_cleanup_at', 0)
        cleanup = self.config['cleanup']
        if (cleanup['enabled'] and not self.stop.is_set()
                and time.time() - cleanup_at >= cleanup['interval_seconds']):
            arguments = ['joblake.raw_cleanup', '--max-objects', str(cleanup['max_objects']),
                         '--max-mib', str(cleanup['max_mib'])]
            if cleanup['apply']:
                arguments.append('--apply')
            # One bounded attempt; retries would multiply the deletion budget.
            self.execute('cleanup', arguments, cleanup['timeout_seconds'])
            cleanup_at = time.time()
        failed = not ingestion_ok or not health_ok or any(task['exit_code'] for task in self.results)
        status = 'interrupted' if self.stop.is_set() else ('failed' if failed else 'completed')
        state = dict(status=status, started_at=started,
                     finished_at=datetime.now(timezone.utc).isoformat(),
                     next_run_at=time.time() + (0 if self.stop.is_set() else self.config['interval_seconds']),
                     last_cleanup_at=cleanup_at, tasks=self.results)
        self.directory.mkdir(parents=True, exist_ok=True)
        save_json(self.directory / 'latest.json', state)
        LOGGER.info('Cycle %s; next run after %ss', status, self.config['interval_seconds'])
        return state


def heartbeat(directory, stop):
    while not stop.is_set():
        (directory / 'heartbeat').touch()
        stop.wait(10)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('init', 'once', 'schedule', 'validate', 'status'))
    parser.add_argument('--config', default=DEFAULT_CONFIG)
    parser.add_argument('--heartbeat', action='store_true', help='Check runner liveness (status only)')
    args = parser.parse_args(argv)
    configure_logging()
    stop = threading.Event()
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda *_: stop.set())
    try:
        if args.mode == 'status':
            if args.heartbeat:
                return 0 if time.time() - (STATE / 'heartbeat').stat().st_mtime < 90 else 1
            print(json.dumps(read_state(STATE), indent=2))
            return 0
        config = load_config(args.config)
        if args.mode == 'validate':
            print(f"Valid: {len(config['sources'])} sources, {config['max_concurrent_sources']} slots")
            return 0
        configure_database()
        with runner_lock(STATE):
            monitor = threading.Thread(target=heartbeat, args=(STATE, stop), daemon=True)
            monitor.start()
            try:
                if not wait_services(stop):
                    return 1
                runner = Runner(config, stop)
                if args.mode == 'init':
                    return runner.execute('migration', ['alembic', 'upgrade', 'head'], 600)
                previous = read_state(STATE)
                while not stop.is_set():
                    if args.mode == 'schedule':
                        delay = max(0, previous.get('next_run_at', 0) - time.time())
                        if stop.wait(delay):
                            break
                    # Readiness is rechecked by every task through existing DB/storage clients.
                    previous = runner.cycle(previous)
                    if args.mode == 'once':
                        return 0 if previous['status'] == 'completed' else 1
                return 130
            finally:
                stop.set()
                monitor.join(timeout=11)
                (STATE / 'heartbeat').unlink(missing_ok=True)
    except (OSError, ValueError, RuntimeError, yaml.YAMLError) as exc:
        LOGGER.error('Standalone runner failed (%s): check configuration/state and task logs', type(exc).__name__)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
