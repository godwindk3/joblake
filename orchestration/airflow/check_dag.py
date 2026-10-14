"""Check all source DAGs in Airflow's runtime, without executing tasks."""
import shlex
import json
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import yaml
from airflow.dag_processing.dagbag import DagBag
import joblake_dag_config

enrichment_config = yaml.safe_load(Path('/opt/joblake/configs/enrichment.yaml').read_text(encoding='utf-8'))
enrichment_timeout = timedelta(seconds=enrichment_config['max_run_seconds'], minutes=5)

for source in ("itviec", "vietnamworks", "topdev", "topcv", "devwork", "careerviet", "vieclam24h", "careerlink", "jobsgo"):
    dag_id = f"joblake_{source}"
    bag = DagBag(dag_folder=f"/opt/airflow/dags/{dag_id}.py")
    assert not bag.import_errors, bag.import_errors
    assert set(bag.dags) == {dag_id}, bag.dags
    dag = bag.dags[dag_id]
    assert set(dag.task_ids) == {"discovery", "detail", "parse", "watcher"}
    assert dag.get_task("discovery").upstream_task_ids == set()
    assert dag.get_task("discovery").downstream_task_ids == {"detail", "watcher"}
    assert dag.get_task("detail").downstream_task_ids == {"parse", "watcher"}
    assert dag.get_task("parse").downstream_task_ids == {"watcher"}
    watcher = dag.get_task("watcher")
    assert watcher.upstream_task_ids == {"discovery", "detail", "parse"}
    assert watcher.downstream_task_ids == set()
    assert watcher.trigger_rule == "one_failed"
    assert watcher.retries == 0
    assert watcher.pool == "joblake_serial"
    assert watcher.pool_slots == 1
    assert not watcher.do_xcom_push
    assert watcher.bash_command.endswith("exit 1")
    assert dag.schedule is None
    assert not dag.catchup
    assert str(dag.timezone) == "Asia/Ho_Chi_Minh"
    assert dag.max_active_runs == 1
    assert dag.max_active_tasks == 1
    if source != "itviec":
        assert dag.is_paused_upon_creation is True
    for task in (dag.get_task(phase) for phase in ("discovery", "detail", "parse")):
        assert task.pool == "joblake_serial"
        assert task.pool_slots == 1
        assert task.retries == (0 if source == 'careerlink' and task.task_id == 'detail' else 2)
        assert task.retry_delay == timedelta(minutes=1)
        assert task.retry_exponential_backoff is False
        assert task.max_retry_delay == timedelta(minutes=1)
        assert task.trigger_rule == ("all_success" if task.task_id == "discovery" else "all_done")
        assert task.cwd == "/opt/joblake"
        assert not task.do_xcom_push
        assert shlex.split(task.bash_command) == [
            "exec", "xvfb-run", "-a", "/opt/joblake/venv/bin/python", "-u",
            "-m", "joblake.main", "--config", f"configs/{source}.yaml",
            "--phase", task.task_id, "--strict",
        ], task.bash_command
    print(f"{dag_id}: import, config mapping and scheduling checks passed")

bag = DagBag(dag_folder="/opt/airflow/dags/joblake_raw_cleanup.py")
assert not bag.import_errors, bag.import_errors
cleanup = bag.dags["joblake_raw_cleanup"].get_task("cleanup_raw")
assert cleanup.pool == "joblake_serial"
assert cleanup.pool_slots == 3
print("joblake_raw_cleanup: reserves all three shared pool slots")

bag = DagBag(dag_folder='/opt/airflow/dags/joblake_supabase_sync.py')
assert not bag.import_errors, bag.import_errors
dag = bag.dags['joblake_supabase_sync']
assert dag.schedule is None and not dag.catchup
assert dag.is_paused_upon_creation is True
assert dag.max_active_runs == 1
assert str(dag.timezone) == 'Asia/Ho_Chi_Minh'
assert set(dag.task_ids) == {'check_connection', 'sync_active_jobs'}
task = dag.get_task('sync_active_jobs')
assert task.upstream_task_ids == {'check_connection'}
assert task.trigger_rule == 'all_success'
assert task.pool == 'joblake_serial' and task.pool_slots == 3
assert dag.params['dry_run'] is False
for preview in (False, True):
    rendered = task.render_template(task.bash_command, {'params': {'dry_run': preview}})
    assert ('--dry-run' in rendered) is preview
print('joblake_supabase_sync: manual active-job sync; no scheduled run')

bag = DagBag(dag_folder='/opt/airflow/dags/joblake_enrichment.py')
assert not bag.import_errors, bag.import_errors
dag = bag.dags['joblake_enrichment']
assert dag.schedule is None and not dag.catchup
assert set(dag.task_ids) == {'enrich_jobs'}
task = dag.get_task('enrich_jobs')
assert not task.upstream_task_ids and not task.downstream_task_ids
assert task.retries == 0 and task.pool_slots == 1
assert task.execution_timeout == enrichment_timeout
assert dag.params['dry_run'] is True
for preview in (False, True):
    rendered = task.render_template(task.bash_command, {'params': {'dry_run': preview, 'max_jobs': 5}})
    assert ('--dry-run' in rendered) is preview
    assert '--max-jobs 5' in rendered
print('joblake_enrichment: standalone manual DAG; logs via unbuffered CLI')

bag = DagBag(dag_folder='/opt/airflow/dags/joblake_enrichment_backfill.py')
assert not bag.import_errors, bag.import_errors
dag = bag.dags['joblake_enrichment_backfill']
assert dag.schedule is None and not dag.catchup
assert dag.is_paused_upon_creation is True
assert dag.max_active_runs == 1 and dag.max_active_tasks == 1
assert str(dag.timezone) == 'Asia/Ho_Chi_Minh'
assert set(dag.task_ids) == {'backfill_jobs'}
assert dag.params['dry_run'] is True and dag.params['lookback_days'] == 30
assert dag.params['date_field'] == 'first_seen_at' and dag.params['sort_order'] == 'newest_first'
task = dag.get_task('backfill_jobs')
assert task.pool == 'joblake_serial' and task.pool_slots == 1 and task.retries == 0
assert task.execution_timeout == enrichment_timeout
assert not task.do_xcom_push and task.append_env
assert task.cwd == '/opt/joblake'
assert not task.upstream_task_ids and not task.downstream_task_ids
assert shlex.split(task.bash_command) == [
    'exec', '/opt/joblake/venv/bin/python', '-u', '-m', 'joblake.main',
    '--phase', 'enrich-backfill', '--backfill-options', '$JOBLAKE_BACKFILL_OPTIONS',
]
for preview in (False, True):
    params = dict(dag.params)
    params.update(dry_run=preview, max_jobs=5, sources=['topcv', 'quote"$(exit 99)'])
    rendered_env = task.render_template(task.env, {'params': params})
    assert json.loads(rendered_env['JOBLAKE_BACKFILL_OPTIONS']) == params
    assert task.render_template(task.bash_command, {'params': params}) == task.bash_command
print('joblake_enrichment_backfill: manual preview by default; parameters passed as JSON data')

# Exercise config changes in this process only; never edit the production YAML.
with TemporaryDirectory() as directory:
    config_path = Path(directory) / 'enrichment.yaml'
    with patch.object(joblake_dag_config, 'ENRICHMENT_CONFIG', config_path):
        for seconds in (14400, 60):
            config_path.write_text(f'max_run_seconds: {seconds}\n', encoding='utf-8')
            for dag_id, task_id in (('joblake_enrichment', 'enrich_jobs'),
                                    ('joblake_enrichment_backfill', 'backfill_jobs')):
                changed = DagBag(dag_folder=f'/opt/airflow/dags/{dag_id}.py')
                assert not changed.import_errors, changed.import_errors
                assert changed.dags[dag_id].get_task(task_id).execution_timeout == timedelta(seconds=seconds + 300)
print('enrichment DAGs: YAML budget changes update both task timeouts on reparse')

bag = DagBag(dag_folder='/opt/airflow/dags/joblake_data_health.py')
assert not bag.import_errors, bag.import_errors
dag = bag.dags['joblake_data_health']
assert set(dag.task_ids) == {'generate_report', 'check_quality'}
assert dag.get_task('check_quality').upstream_task_ids == {'generate_report'}
assert dag.get_task('check_quality').retries == 0
assert dag.get_task('check_quality').execution_timeout == timedelta(minutes=2)
assert dag.get_task('generate_report').retries == 2
print('joblake_data_health: report saved before independent quality gate')

# The daily DAG runs real commands in TaskGroups, so it does not need to
# unpause/trigger child DAGs or occupy workers while waiting for child runs.
import pendulum
from airflow.timetables.base import TimeRestriction
from airflow.timetables.interval import CronDataIntervalTimetable

bag = DagBag(dag_folder='/opt/airflow/dags')
assert not bag.import_errors, bag.import_errors
daily = bag.dags['joblake_daily']
assert isinstance(daily.timetable, CronDataIntervalTimetable)
assert not daily.catchup and daily.is_paused_upon_creation is False
assert daily.max_active_runs == 1 and daily.max_active_tasks == 3
assert str(daily.timezone) == 'Asia/Ho_Chi_Minh'
assert daily.params['dry_run'] is False and daily.params['apply'] is True
assert bag.dags['joblake_raw_cleanup'].schedule is None
source_names = ('itviec', 'vietnamworks', 'topdev', 'topcv', 'devwork',
                'careerviet', 'vieclam24h', 'careerlink', 'jobsgo')
ingestion_ids = {f'{source}.{phase}' for source in source_names
                 for phase in ('discovery', 'detail', 'parse')}
assert set(daily.task_ids) == ingestion_ids | {
    'enrich_jobs', 'check_connection', 'sync_active_jobs', 'cleanup_raw', 'watcher',
}
for source in source_names:
    for phase in ('discovery', 'detail', 'parse'):
        task = daily.get_task(f'{source}.{phase}')
        standalone = bag.dags[f'joblake_{source}'].get_task(phase)
        # Prevent the combined pipeline from drifting from source-specific policy.
        for attr in ('bash_command', 'cwd', 'retries', 'retry_delay',
                     'retry_exponential_backoff', 'max_retry_delay',
                     'pool', 'pool_slots', 'trigger_rule', 'do_xcom_push'):
            assert getattr(task, attr) == getattr(standalone, attr), (task.task_id, attr)
        previous = {'discovery': None, 'detail': 'discovery', 'parse': 'detail'}[phase]
        assert task.upstream_task_ids == ({f'{source}.{previous}'} if previous else set())

assert daily.get_task('enrich_jobs').upstream_task_ids == ingestion_ids
assert daily.get_task('enrich_jobs').trigger_rule == 'all_done'
assert daily.get_task('check_connection').upstream_task_ids == {'enrich_jobs'}
assert daily.get_task('check_connection').trigger_rule == 'all_done'
assert daily.get_task('sync_active_jobs').upstream_task_ids == {'check_connection'}
assert daily.get_task('sync_active_jobs').trigger_rule == 'all_success'
assert daily.get_task('cleanup_raw').upstream_task_ids == {'sync_active_jobs'}
assert daily.get_task('cleanup_raw').trigger_rule == 'all_done'
watcher = daily.get_task('watcher')
assert watcher.upstream_task_ids == set(daily.task_ids) - {'watcher'}
assert watcher.trigger_rule == 'one_failed' and watcher.retries == 0
assert {task.task_id for task in daily.leaves} == {'watcher'}
for task_id, standalone_id in (
    ('enrich_jobs', 'joblake_enrichment'),
    ('check_connection', 'joblake_supabase_sync'),
    ('sync_active_jobs', 'joblake_supabase_sync'),
    ('cleanup_raw', 'joblake_raw_cleanup'),
):
    task = daily.get_task(task_id)
    standalone = bag.dags[standalone_id].get_task(task_id)
    for attr in ('bash_command', 'cwd', 'retries', 'pool', 'pool_slots',
                 'execution_timeout', 'do_xcom_push'):
        assert getattr(task, attr) == getattr(standalone, attr), (task_id, attr)
    for preview in (False, True):
        params = dict(daily.params, dry_run=preview, apply=not preview)
        rendered = task.render_template(task.bash_command, {'params': params})
        if task_id in ('enrich_jobs', 'sync_active_jobs'):
            assert ('--dry-run' in rendered) is preview
        if task_id == 'cleanup_raw':
            assert ('--apply' in rendered) is (not preview)
            assert '--expired-days 7 --unknown-days 30 --max-objects 200 --max-mib 250' in rendered

# A scheduler waking at 09:00 must run today's latest interval immediately.
# Restarting on the same day must wait for tomorrow; days offline are skipped.
restriction = TimeRestriction(earliest=daily.start_date, latest=None, catchup=False)
clock_target = f'{CronDataIntervalTimetable._skip_to_latest.__module__}.utcnow'
with patch(clock_target, return_value=pendulum.datetime(2026, 10, 14, 9, tz='Asia/Ho_Chi_Minh')):
    first = daily.timetable.next_dagrun_info(last_automated_data_interval=None, restriction=restriction)
    assert first.run_after == pendulum.datetime(2026, 10, 14, tz='Asia/Ho_Chi_Minh')
    again = daily.timetable.next_dagrun_info(last_automated_data_interval=first.data_interval,
                                           restriction=restriction)
    assert again.run_after == pendulum.datetime(2026, 10, 15, tz='Asia/Ho_Chi_Minh')
with patch(clock_target, return_value=pendulum.datetime(2026, 10, 18, 16, tz='Asia/Ho_Chi_Minh')):
    resumed = daily.timetable.next_dagrun_info(last_automated_data_interval=first.data_interval,
                                             restriction=restriction)
    assert resumed.run_after == pendulum.datetime(2026, 10, 18, tz='Asia/Ho_Chi_Minh')
print('joblake_daily: command parity, failure visibility, limits, startup and restart scheduling passed')
