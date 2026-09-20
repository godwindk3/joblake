"""CareerLink. CLI reloads the mounted YAML at each task start."""
from datetime import timedelta

import pendulum

from airflow.sdk import DAG
from airflow.providers.standard.operators.bash import BashOperator


with DAG(
    dag_id="joblake_careerlink",
    description="CareerLink discovery -> raw HTML -> local PostgreSQL",
    start_date=pendulum.datetime(2026, 9, 1, tz="Asia/Ho_Chi_Minh"),
    schedule=None,
    is_paused_upon_creation=True,
    catchup=False,
    max_active_runs=1,
    max_active_tasks=1,
    tags=["joblake", "careerlink"],
    default_args={
        "retries": 2,
        "retry_delay": timedelta(minutes=5),
        "retry_exponential_backoff": True,
        "max_retry_delay": timedelta(minutes=30),
        "pool": "joblake_serial",
    },
) as dag:
    tasks = []
    for phase in ("discovery", "detail", "parse"):
        tasks.append(BashOperator(
            task_id=phase,
            trigger_rule="all_success" if phase == "discovery" else "all_done",
            cwd="/opt/joblake",
            bash_command=(
                "exec xvfb-run -a /opt/joblake/venv/bin/python -u "
                "-m joblake.main --config configs/careerlink.yaml "
                f"--phase {phase} --strict"
            ),
            do_xcom_push=False,
        ))
    tasks[0] >> tasks[1] >> tasks[2]

    # Keep failed phases visible in the DAG result even if parse succeeds.
    watcher = BashOperator(
        task_id="watcher",
        bash_command="echo 'An ingestion phase failed; inspect its task logs.' >&2; exit 1",
        trigger_rule="one_failed",
        retries=0,
        do_xcom_push=False,
    )
    tasks >> watcher
