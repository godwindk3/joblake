"""Verify a built standalone image in a disposable Compose project; never crawl/publish."""
import os
from pathlib import Path
import subprocess
import tempfile
import uuid


def main():
    root = Path(__file__).resolve().parents[1]
    (root / 'tmp').mkdir(exist_ok=True)
    project = 'joblake-smoke-' + uuid.uuid4().hex[:12]
    with tempfile.TemporaryDirectory(prefix='standalone-smoke-', dir=root / 'tmp') as temporary:
        env_file = Path(temporary) / '.env'
        values = dict(POSTGRES_USER='joblake_smoke', POSTGRES_DB='joblake_smoke',
                      POSTGRES_PASSWORD='smoke-only-postgres-password',
                      MINIO_ACCESS_KEY='joblake_smoke', MINIO_SECRET_KEY='smoke-only-minio-password',
                      JOBLAKE_ENV_FILE=env_file.as_posix())
        env_file.write_text(''.join(f'{key}={value}\n' for key, value in values.items()), encoding='utf-8')
        environment = {**os.environ, **values}
        compose = ['docker', 'compose', '--project-name', project, '--env-file', str(env_file),
                   '-f', str(root / 'compose.standalone.yaml')]

        def run(*arguments, expected=0):
            result = subprocess.run([*compose, *arguments], cwd=root, env=environment)
            if result.returncode != expected:
                raise RuntimeError(f'Smoke command failed: {arguments[0]} (exit {result.returncode})')

        def python(code):
            run('run', '--rm', '--no-deps', '--entrypoint', 'python', 'joblake-runner', '-c', code)

        try:
            run('config', '--quiet')
            run('run', '--rm', 'joblake-init')
            run('run', '--rm', '--no-deps', 'joblake-runner', 'validate')
            run('run', '--rm', '--no-deps', '--entrypoint', 'python', 'joblake-runner', '-m', 'pip', 'check')
            run('run', '--rm', '--no-deps', '--entrypoint', 'xvfb-run', 'joblake-runner',
                '-a', 'python', '-c',
                "from cloakbrowser import launch; b=launch(headless=False, geoip=False); "
                "p=b.new_page(); p.goto('data:text/html,<title>JobLake smoke</title><h1>ready</h1>', "
                "wait_until='domcontentloaded', timeout=15000); "
                "assert p.title() == 'JobLake smoke'; assert p.locator('h1').inner_text() == 'ready'; "
                "b.close(); print('Browser smoke passed')")
            python("from joblake.standalone import Runner, load_config, configure_database; "
                   "configure_database(); r=Runner(load_config('orchestration/standalone/config.yaml')); "
                   "assert not r.health(); "
                   "assert [t['exit_code'] for t in r.results] == [0, 1]; "
                   "print('Real report succeeded; empty database correctly failed quality gate')")
            # Start the real scheduler with a future timestamp: prove resume/heartbeat
            # and locking without any request to job sites or external AI/serving APIs.
            python("import time; from joblake.standalone import STATE, save_json; "
                   "STATE.mkdir(parents=True, exist_ok=True); "
                   "save_json(STATE/'latest.json', {'next_run_at': time.time()+3600})")
            run('up', '-d', '--wait', '--wait-timeout', '180', 'joblake-runner')
            run('exec', '-T', 'joblake-runner', 'python', '-m', 'joblake.standalone', 'status', '--heartbeat')
            run('run', '--rm', '--no-deps', 'joblake-runner', 'once', expected=2)
            run('stop', 'joblake-runner')
            python("import time; from joblake.standalone import STATE, read_state; "
                   "assert read_state(STATE)['next_run_at'] > time.time(); "
                   "assert not (STATE/'heartbeat').exists(); print('Schedule resume/shutdown passed')")
            print('Standalone Docker smoke passed (no live ingestion or publication).')
        finally:
            # Unique project created above owns all these disposable resources.
            run('down', '--volumes', '--remove-orphans')


if __name__ == '__main__':
    main()
