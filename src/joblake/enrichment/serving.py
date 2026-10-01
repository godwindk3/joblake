"""Optional enrichment projection; existing sync works before either migration."""
import logging

from joblake.enrichment.schema import ARRAYS, FIELDS

LOGGER = logging.getLogger(__name__)
COLUMNS = (*FIELDS, 'enrichment_status', 'enriched_at')


def projection(local, remote, base_query, base_columns):
    columns = {r[0] for r in remote.execute("""SELECT column_name FROM information_schema.columns
        WHERE table_schema='serving' AND table_name='jobs'""").fetchall()}
    if not set(COLUMNS).issubset(columns):
        LOGGER.info('Serving enrichment columns absent; syncing original parser fields only')
        return base_query, base_columns
    available = local.execute("SELECT to_regclass('core.current_job_enrichments') IS NOT NULL").fetchone()[0]
    expressions = []
    for field in FIELDS:
        kind = 'text[]' if field in ARRAYS else ('double precision' if field.startswith('experience_') else 'text')
        if not available:
            expression = f'NULL::{kind}'
        elif field in ARRAYS:
            expression = (f"CASE WHEN e.status='succeeded' AND jsonb_typeof(e.result->'{field}')='array' "
                          f"THEN ARRAY(SELECT jsonb_array_elements_text(e.result->'{field}')) ELSE NULL END")
        else:
            expression = f"CASE WHEN e.status='succeeded' THEN (e.result->>'{field}')::{kind} ELSE NULL END"
        expressions.append(f'{expression} AS {field}')
    expressions.extend([
        "coalesce(e.status,'not_enriched') AS enrichment_status" if available else "'not_enriched'::text AS enrichment_status",
        "CASE WHEN e.status='succeeded' THEN e.enriched_at END AS enriched_at" if available else 'NULL::timestamptz AS enriched_at',
    ])
    query = base_query.replace('j.last_seen_at\nFROM', 'j.last_seen_at,\n       ' + ',\n       '.join(expressions) + '\nFROM')
    if available:
        query = query.replace('WHERE j.listing_status=',
                              'LEFT JOIN core.current_job_enrichments e ON e.parse_result_id=r.id\nWHERE j.listing_status=')
    return query, (*base_columns, *COLUMNS)


def setup():
    import os
    from importlib.resources import files
    import psycopg
    if not os.getenv('SUPABASE_DATABASE_URL'):
        LOGGER.error('SUPABASE_DATABASE_URL is required')
        return 2
    try:
        with psycopg.connect(os.environ['SUPABASE_DATABASE_URL'], connect_timeout=15) as c:
            c.execute("SET LOCAL lock_timeout='10s'")
            c.execute(files('joblake').joinpath('sql/serving_enrichment.sql').read_text(encoding='utf-8'))
        LOGGER.info('Serving enrichment columns ready; existing data and access policies preserved')
        return 0
    except psycopg.Error as exc:
        LOGGER.error('Serving enrichment setup failed (%s, SQLSTATE=%s)', type(exc).__name__, exc.sqlstate)
        return 1
