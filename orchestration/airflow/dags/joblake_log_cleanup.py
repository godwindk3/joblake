"""Daily retention of completed JobLake task logs; no business data deletion."""
from datetime import timedelta

import pendulum
from airflow.sdk import DAG
from airflow.providers.standard.operators.bash import BashOperator

with DAG(
    dag_id="joblake_log_cleanup",
    description="Delete completed JobLake task log files older than 14 days",
    start_date=pendulum.datetime(2026, 9, 1, tz="Asia/Ho_Chi_Minh"),
    schedule="0 5 * * *",
    catchup=False,
    is_paused_upon_creation=False,
    max_active_runs=1,
    max_active_tasks=1,
    tags=["joblake", "maintenance"],
) as dag:
    BashOperator(
        task_id="cleanup_task_logs",
        bash_command="PYTHONPATH=/opt/joblake/src python -m joblake.log_cleanup --days 14 --apply",
        do_xcom_push=False,
        execution_timeout=timedelta(minutes=30),
        retries=0,
    )
