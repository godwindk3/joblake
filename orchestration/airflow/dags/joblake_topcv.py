"""TopCV. CLI reloads the mounted YAML at each task start."""
import pendulum

from airflow.sdk import DAG
from airflow.providers.standard.operators.bash import BashOperator


with DAG(
    dag_id="joblake_topcv",
    description="TopCV discovery -> raw HTML -> local PostgreSQL",
    start_date=pendulum.datetime(2026, 9, 1, tz="Asia/Ho_Chi_Minh"),
    schedule=None,
    is_paused_upon_creation=True,
    catchup=False,
    max_active_runs=1,
    max_active_tasks=1,
    tags=["joblake", "topcv"],
    default_args={"retries": 0, "pool": "joblake_serial"},
) as dag:
    tasks = []
    for phase in ("discovery", "detail", "parse"):
        tasks.append(BashOperator(
            task_id=phase,
            cwd="/opt/joblake",
            bash_command=(
                "exec xvfb-run -a /opt/joblake/venv/bin/python -u "
                "-m joblake.main --config configs/topcv.yaml "
                f"--phase {phase} --strict"
            ),
            do_xcom_push=False,
        ))
    tasks[0] >> tasks[1] >> tasks[2]
