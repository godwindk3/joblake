"""Daily read-only data health report across all configured sources."""
from datetime import timedelta

import pendulum
from airflow.sdk import DAG, Param
from airflow.providers.standard.operators.bash import BashOperator


with DAG(
    dag_id='joblake_data_health',
    description='Current data quality, errors, backlog and recent activity by source',
    start_date=pendulum.datetime(2026, 9, 20, tz='Asia/Ho_Chi_Minh'),
    schedule='0 7 * * *',
    catchup=False,
    is_paused_upon_creation=True,
    max_active_runs=1,
    max_active_tasks=1,
    tags=['joblake', 'reporting'],
    params={
        'window_hours': Param(24, type='integer', minimum=1, maximum=8760),
        'stale_hours': Param(6, type='integer', minimum=1, maximum=8760),
        'samples': Param(5, type='integer', minimum=1, maximum=100),
    },
    default_args={'retries': 2, 'retry_delay': timedelta(minutes=5), 'pool': 'joblake_serial'},
) as dag:
    report = BashOperator(
        task_id='generate_report',
        cwd='/opt/joblake',
        execution_timeout=timedelta(minutes=20),
        bash_command=(
            'exec /opt/joblake/venv/bin/python -u -m joblake.data_health '
            '--window-hours {{ params.window_hours | int }} '
            '--stale-hours {{ params.stale_hours | int }} '
            '--samples {{ params.samples | int }}'
        ),
        do_xcom_push=False,
    )
