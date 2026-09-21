"""Reconcile a compact active-job serving set from authoritative local state."""
import logging
import os
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from joblake.logging import configure_logging

LOGGER = logging.getLogger(__name__)

# No raw objects, parser metadata, JSON payload, history, or duplicate benefit list.
JOB_COLUMNS = (
    'id', 'source_id', 'canonical_url', 'title', 'employer_name_raw',
    'description_text', 'requirements_text', 'benefits_text', 'categories_raw',
    'skills_raw', 'location_cities', 'salary_raw', 'employment_type_raw',
    'experience_raw', 'posted_at', 'expires_at', 'last_seen_at',
)
SOURCE_COLUMNS = ('id', 'code', 'display_name')
STATE_COLUMNS = ('id', 'source_id', 'canonical_url', 'listing_status', 'last_seen_at')

SERVING_DDL = """
CREATE SCHEMA serving;
CREATE TABLE serving.sources (
    id bigint PRIMARY KEY,
    code text NOT NULL UNIQUE,
    display_name text NOT NULL
);
CREATE TABLE serving.jobs (
    id bigint PRIMARY KEY,
    source_id bigint NOT NULL REFERENCES serving.sources(id),
    canonical_url text NOT NULL,
    title text NOT NULL CHECK (btrim(title) <> ''),
    employer_name_raw text,
    description_text text,
    requirements_text text,
    benefits_text text,
    categories_raw text[] NOT NULL,
    skills_raw text[] NOT NULL,
    location_cities text[] NOT NULL,
    salary_raw text,
    employment_type_raw text,
    experience_raw text,
    posted_at timestamptz,
    expires_at timestamptz,
    last_seen_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX jobs_source_id_idx ON serving.jobs(source_id);
CREATE INDEX jobs_posted_at_idx ON serving.jobs(posted_at DESC NULLS LAST, id DESC);
ALTER TABLE serving.sources ENABLE ROW LEVEL SECURITY;
ALTER TABLE serving.jobs ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON SCHEMA serving FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA serving FROM PUBLIC;
COMMENT ON SCHEMA serving IS 'JobLake active jobs serving v1; local PostgreSQL is authoritative';
"""

STATE_QUERY = """
SELECT p.id, p.source_id, p.canonical_url, j.listing_status, j.last_seen_at
FROM core.source_job_postings p
JOIN ref.sources s ON s.id=p.source_id
JOIN crawl_state.jobs j ON j.id=p.crawler_job_id AND j.source=s.code
ORDER BY p.id
"""
JOBS_QUERY = """
SELECT p.id, p.source_id, p.canonical_url, r.title, r.employer_name_raw,
       r.description_text, r.requirements_text,
       COALESCE(NULLIF(btrim(r.benefits_text), ''),
                NULLIF(array_to_string(r.benefit_items, E'\\n'), '')) AS benefits_text,
       r.categories_raw, r.skills_raw, r.location_cities, r.salary_raw,
       r.employment_type_raw, r.experience_raw, r.posted_at, r.expires_at,
       j.last_seen_at
FROM core.source_job_postings p
JOIN ref.sources s ON s.id=p.source_id
JOIN crawl_state.jobs j ON j.id=p.crawler_job_id AND j.source=s.code
JOIN core.job_parse_results r ON r.source_posting_id=p.id AND r.is_current
WHERE j.listing_status='active' AND r.quality_status IN ('accepted','partial')
  AND NULLIF(btrim(r.title), '') IS NOT NULL
ORDER BY p.id
"""


def configure():
    local_url = os.environ.get('LOCAL_DATABASE_URL')
    # The root .env is shared with Windows; localhost inside Airflow is the container.
    # Only rewrite loopback, and only inside Docker with an explicit non-loopback host.
    loopback = {'localhost', '127.0.0.1', '::1'}
    docker_host = os.getenv('POSTGRES_HOST')
    if local_url and Path('/.dockerenv').exists() and docker_host and docker_host not in loopback:
        if conninfo_to_dict(local_url).get('host') in loopback:
            os.environ['LOCAL_DATABASE_URL'] = make_conninfo(local_url, host=docker_host)
    if not os.environ.get('LOCAL_DATABASE_URL') and os.environ.get('POSTGRES_PASSWORD'):
        os.environ['LOCAL_DATABASE_URL'] = make_conninfo(
            host=os.getenv('POSTGRES_HOST', 'localhost'),
            port=os.getenv('POSTGRES_PORT', '5432'),
            dbname=os.getenv('POSTGRES_DB', 'joblake'),
            user=os.getenv('POSTGRES_USER', 'joblake'),
            password=os.environ['POSTGRES_PASSWORD'],
        )


def identifiers(columns, alias=None):
    return sql.SQL(', ').join(
        sql.Identifier(alias, c) if alias else sql.Identifier(c) for c in columns
    )


def copy_query(local, remote, table, columns, query):
    count = 0
    with local.cursor(name=f'export_{table}') as reader, remote.cursor() as writer:
        reader.execute(query)
        with writer.copy(sql.SQL('COPY {} ({}) FROM STDIN').format(
            sql.Identifier(table), identifiers(columns)
        )) as stream:
            for values in reader:
                stream.write_row(values)
                count += 1
    return count


def stage_snapshot(local, remote):
    # Never let a broken join silently turn into mass deletion.
    invalid = local.execute("""
        SELECT count(*) FROM core.source_job_postings p
        LEFT JOIN ref.sources s ON s.id=p.source_id
        LEFT JOIN crawl_state.jobs j ON j.id=p.crawler_job_id
        WHERE s.id IS NULL OR j.id IS NULL OR j.source IS DISTINCT FROM s.code
    """).fetchone()[0]
    if invalid:
        raise ValueError('Local posting/state mapping is incomplete or inconsistent')
    invalid = local.execute("""
        SELECT count(*) FROM crawl_state.jobs j
        LEFT JOIN crawl_state.cdc_sources c ON c.source=j.source
        LEFT JOIN crawl_state.crawl_runs r ON r.id=c.last_applied_run_id
        WHERE j.listing_status='active' AND (
            c.source IS NULL OR j.tracking_scope_hash IS DISTINCT FROM c.scope_hash
            OR r.id IS NULL OR r.source IS DISTINCT FROM j.source OR NOT r.coverage_complete
            OR r.cdc_status NOT IN ('baseline','applied'))
    """).fetchone()[0]
    if invalid:
        raise ValueError('Active state lacks a complete committed CDC baseline')
    remote.execute('CREATE TEMP TABLE sync_sources (LIKE serving.sources INCLUDING ALL) ON COMMIT DROP')
    remote.execute("""CREATE TEMP TABLE sync_state (
        id bigint PRIMARY KEY, source_id bigint NOT NULL, canonical_url text NOT NULL,
        listing_status text NOT NULL CHECK (listing_status IN ('active','expired','unknown')),
        last_seen_at timestamptz NOT NULL) ON COMMIT DROP""")
    # Copy only exported columns: no derived search vector, triggers or GIN indexes.
    remote.execute(sql.SQL('CREATE TEMP TABLE sync_jobs ON COMMIT DROP AS SELECT {} FROM serving.jobs WITH NO DATA').format(identifiers(JOB_COLUMNS)))
    remote.execute('ALTER TABLE sync_jobs ADD PRIMARY KEY (id)')
    sources = copy_query(local, remote, 'sync_sources', SOURCE_COLUMNS,
                         'SELECT id,code,display_name FROM ref.sources ORDER BY id')
    if not sources:
        raise ValueError('Local source catalog is empty; refusing reconciliation')
    copy_query(local, remote, 'sync_state', STATE_COLUMNS, STATE_QUERY)
    copy_query(local, remote, 'sync_jobs', JOB_COLUMNS, JOBS_QUERY)
    for table in ('sync_sources', 'sync_state', 'sync_jobs'):
        remote.execute(sql.SQL('ANALYZE {}').format(sql.Identifier(table)))
    if remote.execute("""SELECT EXISTS (
        SELECT 1 FROM serving.sources t JOIN sync_sources s
          ON t.id=s.id OR t.code=s.code
        WHERE (t.id,t.code) IS DISTINCT FROM (s.id,s.code))""").fetchone()[0]:
        raise ValueError('Source identity collision; refusing reconciliation')
    if remote.execute("""SELECT EXISTS (
        SELECT 1 FROM serving.jobs t JOIN sync_state s ON t.id=s.id
        WHERE (t.source_id,t.canonical_url) IS DISTINCT FROM (s.source_id,s.canonical_url))
        OR EXISTS (SELECT 1 FROM serving.sources t
                   WHERE NOT EXISTS (SELECT 1 FROM sync_sources s WHERE s.id=t.id))
    """).fetchone()[0]:
        raise ValueError('Destination is not the serving replica of this local database')


def different(columns):
    return sql.SQL('ROW({}) IS DISTINCT FROM ROW({})').format(
        identifiers(columns, 't'), identifiers(columns, 's'))


def changes(remote):
    result = {}
    for table, columns in (('sources', SOURCE_COLUMNS), ('jobs', JOB_COLUMNS)):
        result[table] = remote.execute(sql.SQL("""
            SELECT count(*) FILTER (WHERE t.id IS NULL),
                   count(*) FILTER (WHERE t.id IS NOT NULL AND {})
            FROM {} s LEFT JOIN {} t ON t.id=s.id
        """).format(different(columns), sql.Identifier('sync_' + table),
                     sql.Identifier('serving', table))).fetchone()
    result['delete'] = remote.execute("""
        SELECT count(*) FROM serving.jobs t
        WHERE NOT EXISTS (SELECT 1 FROM sync_state s WHERE s.id=t.id AND s.listing_status='active')
    """).fetchone()[0]
    result['refresh_retained'] = remote.execute("""
        SELECT count(*) FROM serving.jobs t JOIN sync_state s ON s.id=t.id
        WHERE s.listing_status='active' AND t.last_seen_at IS DISTINCT FROM s.last_seen_at
          AND NOT EXISTS (SELECT 1 FROM sync_jobs e WHERE e.id=t.id)
    """).fetchone()[0]
    result['active_without_content'] = remote.execute("""
        SELECT count(*) FROM sync_state s WHERE s.listing_status='active'
        AND NOT EXISTS (SELECT 1 FROM sync_jobs e WHERE e.id=s.id)
    """).fetchone()[0]
    return result


def upsert(remote, table, columns):
    updates = sql.SQL(', ').join(sql.SQL('{}=EXCLUDED.{}').format(
        sql.Identifier(c), sql.Identifier(c)) for c in columns if c != 'id')
    if table == 'jobs':
        updates += sql.SQL(', updated_at=CURRENT_TIMESTAMP')
    remote.execute(sql.SQL("""
        INSERT INTO {} AS t ({}) SELECT {} FROM {} AS s WHERE true
        ON CONFLICT (id) DO UPDATE SET {} WHERE {}
    """).format(sql.Identifier('serving', table), identifiers(columns),
                 identifiers(columns, 's'), sql.Identifier('sync_' + table), updates,
                 sql.SQL('ROW({}) IS DISTINCT FROM ROW({})').format(
                     identifiers(columns, 't'), identifiers(columns, 'excluded'))))


def reconcile(remote):
    upsert(remote, 'sources', SOURCE_COLUMNS)
    upsert(remote, 'jobs', JOB_COLUMNS)
    # Missing parse content is not evidence of expiry. Preserve the last good content.
    remote.execute("""
        UPDATE serving.jobs t SET last_seen_at=s.last_seen_at, updated_at=CURRENT_TIMESTAMP
        FROM sync_state s WHERE t.id=s.id AND s.listing_status='active'
          AND t.last_seen_at IS DISTINCT FROM s.last_seen_at
          AND NOT EXISTS (SELECT 1 FROM sync_jobs e WHERE e.id=t.id)
    """)
    remote.execute("""
        DELETE FROM serving.jobs t WHERE NOT EXISTS (
            SELECT 1 FROM sync_state s WHERE s.id=t.id AND s.listing_status='active')
    """)
    verify_staged(remote)


def verify_staged(remote):
    remaining = changes(remote)
    if any(remaining[t] != (0, 0) for t in ('sources', 'jobs')) or any(
        remaining[t] for t in ('delete', 'refresh_retained')
    ):
        raise ValueError('Serving rows differ from the authoritative staged snapshot')


def sync(*, dry_run=False, verify_only=False):
    configure_logging()
    configure()
    if not all(os.getenv(k) for k in ('LOCAL_DATABASE_URL', 'SUPABASE_DATABASE_URL')):
        LOGGER.error('FAIL: configure local PostgreSQL and SUPABASE_DATABASE_URL')
        return 2
    try:
        with psycopg.connect(os.environ['SUPABASE_DATABASE_URL'], connect_timeout=15) as remote:
            remote.execute("SET LOCAL lock_timeout='10s'")
            remote.execute("SET LOCAL statement_timeout='120s'")
            remote.execute("SET LOCAL TIME ZONE 'UTC'")
            # Acquire before taking the local snapshot: concurrent syncs cannot apply old state last.
            if not remote.execute('SELECT pg_try_advisory_xact_lock(741205, 1)').fetchone()[0]:
                raise ValueError('Another serving sync is running')
            remote.execute('LOCK TABLE serving.sources, serving.jobs IN SHARE ROW EXCLUSIVE MODE')
            with psycopg.connect(os.environ['LOCAL_DATABASE_URL'], connect_timeout=15) as local:
                local.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
                local.execute("SET LOCAL statement_timeout='120s'")
                stage_snapshot(local, remote)
            for row in remote.execute("""
                SELECT s.code, count(j.id) FILTER (WHERE j.listing_status='active'),
                       count(j.id) FILTER (WHERE j.listing_status='expired'),
                       count(j.id) FILTER (WHERE j.listing_status='unknown'), count(e.id)
                FROM sync_sources s LEFT JOIN sync_state j ON j.source_id=s.id
                LEFT JOIN sync_jobs e ON e.id=j.id GROUP BY s.code ORDER BY s.code
            """):
                LOGGER.info('Source %s: active=%s expired=%s unknown=%s publishable=%s', *row)
            LOGGER.info('Serving changes: %s', changes(remote))
            if verify_only:
                verify_staged(remote)
                remote.rollback()
            elif dry_run:
                # Staging is temporary; never write production rows even transiently.
                remote.rollback()
            else:
                reconcile(remote)
        LOGGER.info('SUCCESS: %s', 'verification passed' if verify_only else
                    'dry run; no serving rows changed' if dry_run else 'serving sync committed')
        return 0
    except ValueError as exc:
        LOGGER.error('FAIL: serving operation rolled back: %s', exc)
        return 1
    except psycopg.Error as exc:
        # Do not log exception text: a connection error can contain credentials.
        LOGGER.error('FAIL: serving operation rolled back (%s, SQLSTATE=%s); check schema and connection', type(exc).__name__, exc.sqlstate)
        return 1
