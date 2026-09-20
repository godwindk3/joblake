"""Manual active-job reconciliation; ingestion is triggered independently."""
from datetime import timedelta

import pendulum
from airflow.sdk import DAG, Param
from airflow.providers.standard.operators.bash import BashOperator

with DAG(
    dag_id='joblake_supabase_sync',
    description='Manual sync of active local jobs; remove inactive jobs from Supabase',
    start_date=pendulum.datetime(2026, 9, 20, tz='Asia/Ho_Chi_Minh'),
    schedule=None,
    catchup=False,
    is_paused_upon_creation=True,
    max_active_runs=1,
    max_active_tasks=1,
    tags=['joblake', 'supabase'],
    params={'dry_run': Param(False, type='boolean', description='Preview counts without changing serving rows')},
    default_args={
        'retries': 2, 'retry_delay': timedelta(minutes=1),
        'retry_exponential_backoff': False, 'max_retry_delay': timedelta(minutes=1),
        'pool': 'joblake_serial',
    },
) as dag:
    connection = BashOperator(
        task_id='check_connection',
        cwd='/opt/joblake',
        execution_timeout=timedelta(minutes=2),
        bash_command='exec /opt/joblake/venv/bin/python -u -m joblake.main --phase supabase-test',
        do_xcom_push=False,
    )
    sync = BashOperator(
        task_id='sync_active_jobs',
        cwd='/opt/joblake',
        # Existing pool has three slots. Prevent ingestion/cleanup overlap during export.
        pool_slots=3,
        execution_timeout=timedelta(minutes=30),
        bash_command=(
            'exec /opt/joblake/venv/bin/python -u -m joblake.main --phase supabase-sync '
            '{% if params.dry_run %}--dry-run{% endif %}'
        ),
        do_xcom_push=False,
    )
    connection >> sync
