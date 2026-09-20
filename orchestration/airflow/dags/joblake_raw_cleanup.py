"""Daily bounded raw retention; processed PostgreSQL records are retained."""
from datetime import timedelta
import pendulum
from airflow.sdk import DAG, Param
from airflow.providers.standard.operators.bash import BashOperator

with DAG(
    dag_id='joblake_raw_cleanup',
    description='Dry-run by default; delete only eligible MinIO raw HTML',
    start_date=pendulum.datetime(2026, 9, 19, tz='Asia/Ho_Chi_Minh'),
    schedule='0 15 * * *',
    catchup=False,
    is_paused_upon_creation=True,
    max_active_runs=1,
    max_active_tasks=1,
    tags=['joblake', 'retention'],
    params={
        'apply': Param(False, type='boolean'),
        'expired_days': Param(7, type='integer', minimum=1),
        'unknown_days': Param(30, type='integer', minimum=1),
        'max_objects': Param(200, type='integer', minimum=1, maximum=10000),
        'max_mib': Param(250, type='integer', minimum=1, maximum=10240),
    },
    default_args={'retries': 2, 'retry_delay': timedelta(minutes=1), 'pool': 'joblake_serial'},
) as dag:
    cleanup = BashOperator(
        task_id='cleanup_raw',
        # Reserve the entire shared pool so cleanup cannot overlap ingestion.
        pool_slots=3,
        cwd='/opt/joblake',
        execution_timeout=timedelta(hours=1),
        bash_command=(
            'exec /opt/joblake/venv/bin/python -u -m joblake.raw_cleanup '
            '--expired-days {{ params.expired_days | int }} '
            '--unknown-days {{ params.unknown_days | int }} '
            '--max-objects {{ params.max_objects | int }} '
            '--max-mib {{ params.max_mib | int }} '
            '{% if params.apply %}--apply{% endif %}'
        ),
        do_xcom_push=False,
    )
