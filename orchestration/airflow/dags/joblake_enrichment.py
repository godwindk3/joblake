"""Standalone optional AI enrichment. No dependency on ingestion or serving sync."""
from datetime import timedelta

import pendulum
from airflow.sdk import DAG, Param
from airflow.providers.standard.operators.bash import BashOperator


with DAG(
    dag_id='joblake_enrichment',
    description='Enrich new/changed local parsed jobs with AI; does not sync Supabase',
    start_date=pendulum.datetime(2026, 9, 25, tz='Asia/Ho_Chi_Minh'),
    schedule=None,
    catchup=False,
    is_paused_upon_creation=True,
    max_active_runs=1,
    max_active_tasks=1,
    tags=['joblake', 'enrichment', 'ai'],
    params={
        'dry_run': Param(True, type='boolean', description='Inspect eligibility without API calls or writes'),
        'max_jobs': Param(100, type='integer', minimum=1, maximum=1000,
                          description='Maximum API attempts this run, including failed calls'),
    },
) as dag:
    enrich = BashOperator(
        task_id='enrich_jobs',
        cwd='/opt/joblake',
        pool='joblake_serial',
        retries=0,  # Persistent queue owns retry timing and budgets, not Airflow.
        execution_timeout=timedelta(minutes=25),
        bash_command=(
            'exec /opt/joblake/venv/bin/python -u -m joblake.main --phase enrich '
            '--max-jobs {{ params.max_jobs | int }} '
            '{% if params.dry_run %}--dry-run{% endif %}'
        ),
        do_xcom_push=False,
    )
