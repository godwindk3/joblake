"""Manual historical enrichment; preview by default, shared production quota ledger."""
import pendulum
from airflow.sdk import DAG, Param
from airflow.providers.standard.operators.bash import BashOperator
from joblake_dag_config import enrichment_execution_timeout


with DAG(
    dag_id='joblake_enrichment_backfill',
    description='Preview or enrich older active jobs, newest first; sync remains separate',
    start_date=pendulum.datetime(2026, 10, 2, tz='Asia/Ho_Chi_Minh'),
    schedule=None,
    catchup=False,
    is_paused_upon_creation=True,
    max_active_runs=1,
    max_active_tasks=1,
    tags=['joblake', 'enrichment', 'backfill', 'ai'],
    params={
        'dry_run': Param(True, type='boolean', description='Preview counts and sample; no database writes or API calls'),
        'lookback_days': Param(30, type='integer', minimum=1, maximum=36500,
                               description='Days before date_to or run start; explicit date_from overrides this'),
        'date_from': Param(None, type=['null', 'string'],
                           description='Inclusive ISO date/time; local Vietnam time if no offset'),
        'date_to': Param(None, type=['null', 'string'],
                         description='Exclusive ISO date/time; defaults to as_of/run start'),
        'as_of': Param(None, type=['null', 'string'],
                       description='Copy from dry-run report to reuse its window; otherwise actual run start'),
        'date_field': Param('first_seen_at', enum=['first_seen_at', 'posted_at', 'fetched_at'],
                            description='Date used for filtering and ordering; missing dates are skipped'),
        'sources': Param([], type='array', items={'type': 'string', 'minLength': 1}, maxItems=100,
                         description='Source codes; empty means all sources'),
        'posting_ids': Param([], type='array', items={'type': 'integer', 'minimum': 1,
                                                     'maximum': 9223372036854775807}, maxItems=1000,
                             description='core.source_job_postings IDs; combined with all other filters'),
        'sort_order': Param('newest_first', enum=['newest_first', 'oldest_first']),
        'max_jobs': Param(100, type='integer', minimum=1, maximum=1000,
                          description='Maximum distinct ready jobs selected'),
        'max_api_attempts': Param(100, type='integer', minimum=1, maximum=1000,
                                  description='Maximum API attempts, including retries/failures'),
    },
) as dag:
    enrich = BashOperator(
        task_id='backfill_jobs',
        cwd='/opt/joblake',
        pool='joblake_serial',
        retries=0,
        execution_timeout=enrichment_execution_timeout(),
        # Pass user parameters as data, never interpolate them into shell source.
        env={'JOBLAKE_BACKFILL_OPTIONS': '{{ params | tojson }}'},
        append_env=True,
        bash_command=(
            'exec /opt/joblake/venv/bin/python -u -m joblake.main --phase enrich-backfill '
            '--backfill-options "$JOBLAKE_BACKFILL_OPTIONS"'
        ),
        do_xcom_push=False,
    )
