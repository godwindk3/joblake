"""Check all source DAGs in Airflow's runtime, without executing tasks."""
import shlex
from datetime import timedelta
from airflow.dag_processing.dagbag import DagBag

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
assert dag.params['dry_run'] is True
for preview in (False, True):
    rendered = task.render_template(task.bash_command, {'params': {'dry_run': preview, 'max_jobs': 5}})
    assert ('--dry-run' in rendered) is preview
    assert '--max-jobs 5' in rendered
print('joblake_enrichment: standalone manual DAG; logs via unbuffered CLI')

bag = DagBag(dag_folder='/opt/airflow/dags/joblake_data_health.py')
assert not bag.import_errors, bag.import_errors
dag = bag.dags['joblake_data_health']
assert set(dag.task_ids) == {'generate_report', 'check_quality'}
assert dag.get_task('check_quality').upstream_task_ids == {'generate_report'}
assert dag.get_task('check_quality').retries == 0
assert dag.get_task('check_quality').execution_timeout == timedelta(minutes=2)
assert dag.get_task('generate_report').retries == 2
print('joblake_data_health: report saved before independent quality gate')
