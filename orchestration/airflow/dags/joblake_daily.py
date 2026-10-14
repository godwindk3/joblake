"""One daily run of ingestion, enrichment, serving sync and raw retention."""
from datetime import timedelta

import pendulum
from airflow.sdk import DAG, Param, TaskGroup
from airflow.providers.standard.operators.bash import BashOperator
from airflow.timetables.interval import CronDataIntervalTimetable
from joblake_dag_config import enrichment_execution_timeout


SOURCES = (
    'itviec', 'vietnamworks', 'topdev', 'topcv', 'devwork',
    'careerviet', 'vieclam24h', 'careerlink', 'jobsgo',
)

with DAG(
    dag_id='joblake_daily',
    description='Daily: nine sources -> enrichment -> Supabase -> raw cleanup',
    start_date=pendulum.datetime(2026, 9, 1, tz='Asia/Ho_Chi_Minh'),
    # Explicit data intervals: on startup run the latest completed day even
    # after missing midnight. Airflow 3 cron strings can use trigger timetables.
    schedule=CronDataIntervalTimetable('0 0 * * *', timezone='Asia/Ho_Chi_Minh'),
    catchup=False,
    is_paused_upon_creation=False,
    max_active_runs=1,
    max_active_tasks=3,
    tags=['joblake', 'daily'],
    params={
        'dry_run': Param(False, type='boolean',
                         description='Preview enrichment and sync only; crawlers still run'),
        'max_jobs': Param(100, type='integer', minimum=1, maximum=1000,
                          description='Maximum enrichment API attempts per daily run'),
        'apply': Param(True, type='boolean', description='Apply existing raw HTML retention policy'),
        'expired_days': Param(7, type='integer', minimum=1),
        'unknown_days': Param(30, type='integer', minimum=1),
        'max_objects': Param(200, type='integer', minimum=1, maximum=10000),
        'max_mib': Param(250, type='integer', minimum=1, maximum=10240),
    },
    default_args={
        'retries': 2,
        'retry_delay': timedelta(minutes=1),
        'retry_exponential_backoff': False,
        'max_retry_delay': timedelta(minutes=1),
        'pool': 'joblake_serial',
    },
) as dag:
    ingestion = []
    for source in SOURCES:
        with TaskGroup(group_id=source):
            phases = []
            for phase in ('discovery', 'detail', 'parse'):
                phases.append(BashOperator(
                    task_id=phase,
                    retries=0 if source == 'careerlink' and phase == 'detail' else 2,
                    trigger_rule='all_success' if phase == 'discovery' else 'all_done',
                    cwd='/opt/joblake',
                    bash_command=(
                        'exec xvfb-run -a /opt/joblake/venv/bin/python -u '
                        f'-m joblake.main --config configs/{source}.yaml '
                        f'--phase {phase} --strict'
                    ),
                    do_xcom_push=False,
                ))
            phases[0] >> phases[1] >> phases[2]
            ingestion.extend(phases)

    enrich = BashOperator(
        task_id='enrich_jobs',
        trigger_rule='all_done',
        cwd='/opt/joblake',
        retries=0,
        execution_timeout=enrichment_execution_timeout(),
        bash_command=(
            'exec /opt/joblake/venv/bin/python -u -m joblake.main --phase enrich '
            '--max-jobs {{ params.max_jobs | int }} '
            '{% if params.dry_run %}--dry-run{% endif %}'
        ),
        do_xcom_push=False,
    )
    connection = BashOperator(
        task_id='check_connection',
        trigger_rule='all_done',
        cwd='/opt/joblake',
        execution_timeout=timedelta(minutes=2),
        bash_command='exec /opt/joblake/venv/bin/python -u -m joblake.main --phase supabase-test',
        do_xcom_push=False,
    )
    sync = BashOperator(
        task_id='sync_active_jobs',
        cwd='/opt/joblake',
        pool_slots=3,
        execution_timeout=timedelta(minutes=30),
        bash_command=(
            'exec /opt/joblake/venv/bin/python -u -m joblake.main --phase supabase-sync '
            '{% if params.dry_run %}--dry-run{% endif %}'
        ),
        do_xcom_push=False,
    )
    cleanup = BashOperator(
        task_id='cleanup_raw',
        trigger_rule='all_done',
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
    ingestion >> enrich >> connection >> sync >> cleanup

    # all_done permits useful partial progress, but must never hide a failure.
    watcher = BashOperator(
        task_id='watcher',
        bash_command="echo 'A daily pipeline task failed; inspect its task logs.' >&2; exit 1",
        trigger_rule='one_failed',
        retries=0,
        do_xcom_push=False,
    )
    (ingestion + [enrich, connection, sync, cleanup]) >> watcher
