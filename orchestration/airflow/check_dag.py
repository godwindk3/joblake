"""Check all source DAGs in Airflow's runtime, without executing tasks."""
import shlex
from airflow.dag_processing.dagbag import DagBag

for source in ("itviec", "vietnamworks", "topdev", "topcv"):
    dag_id = f"joblake_{source}"
    bag = DagBag(dag_folder=f"/opt/airflow/dags/{dag_id}.py")
    assert not bag.import_errors, bag.import_errors
    assert set(bag.dags) == {dag_id}, bag.dags
    dag = bag.dags[dag_id]
    assert set(dag.task_ids) == {"discovery", "detail", "parse"}
    assert dag.get_task("discovery").upstream_task_ids == set()
    assert dag.get_task("discovery").downstream_task_ids == {"detail"}
    assert dag.get_task("detail").downstream_task_ids == {"parse"}
    assert dag.get_task("parse").downstream_task_ids == set()
    assert dag.schedule is None
    assert not dag.catchup
    assert str(dag.timezone) == "Asia/Ho_Chi_Minh"
    assert dag.max_active_runs == 1
    assert dag.max_active_tasks == 1
    if source != "itviec":
        assert dag.is_paused_upon_creation is True
    for task in dag.tasks:
        assert task.pool == "joblake_serial"
        assert task.retries == 0
        assert task.trigger_rule == "all_success"
        assert task.cwd == "/opt/joblake"
        assert not task.do_xcom_push
        assert shlex.split(task.bash_command) == [
            "exec", "xvfb-run", "-a", "/opt/joblake/venv/bin/python", "-u",
            "-m", "joblake.main", "--config", f"configs/{source}.yaml",
            "--phase", task.task_id, "--strict",
        ], task.bash_command
    print(f"{dag_id}: import, config mapping and scheduling checks passed")
