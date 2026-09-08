"""Small one-way sync for the existing ID-preserving JobLake replica."""
import logging
import os

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.types.json import Jsonb

from joblake.logging import configure_logging


LOGGER = logging.getLogger(__name__)

TABLES = (
    ("ref", "sources", ("code",)),
    ("core", "source_job_postings", ("source_id", "canonical_url")),
    ("core", "job_parse_results", ("source_posting_id", "raw_sha256", "parser_name", "parser_version")),
)


def configure():
    # Prefer an explicit URL; otherwise reuse the parser's existing settings.
    if not os.environ.get("LOCAL_DATABASE_URL") and os.environ.get("POSTGRES_PASSWORD"):
        os.environ["LOCAL_DATABASE_URL"] = make_conninfo(
            host=os.getenv("POSTGRES_HOST", "localhost"),
            port=os.getenv("POSTGRES_PORT", "5432"),
            dbname=os.getenv("POSTGRES_DB", "joblake"),
            user=os.getenv("POSTGRES_USER", "joblake"),
            password=os.environ["POSTGRES_PASSWORD"],
        )


def sync(*, dry_run=False):
    configure_logging()
    configure()
    if not all(os.getenv(k) for k in ("LOCAL_DATABASE_URL", "SUPABASE_DATABASE_URL")):
        LOGGER.error("FAIL: configure local PostgreSQL and SUPABASE_DATABASE_URL")
        return 2
    try:
        with psycopg.connect(os.environ["LOCAL_DATABASE_URL"], connect_timeout=10) as local, psycopg.connect(os.environ["SUPABASE_DATABASE_URL"], connect_timeout=10) as remote:
            local.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            # Serialize syncs and exclude remote writers during identity/current updates.
            remote.execute("SET LOCAL lock_timeout = '10s'")
            remote.execute("SET LOCAL TIME ZONE 'UTC'")
            remote.execute("LOCK TABLE ref.sources, core.source_job_postings, core.job_parse_results IN EXCLUSIVE MODE")
            for schema, table, keys in TABLES:
                relation = sql.Identifier(schema, table)
                with local.cursor(name=f"sync_{table}") as reader:
                    reader.execute(sql.SQL("SELECT * FROM {} ORDER BY id").format(relation))
                    # Server cursors expose description after the first fetch.
                    records = reader.fetchmany(200)
                    columns = [c.name for c in reader.description]
                    count = 0
                    while records:
                        for values in records:
                            record = dict(zip(columns, values))
                            existing = remote.execute(sql.SQL("SELECT {} FROM {} WHERE id = %s").format(sql.SQL(', ').join(map(sql.Identifier, keys)), relation), (record['id'],)).fetchone()
                            if existing is not None and tuple(record[k] for k in keys) != existing:
                                raise ValueError(f"ID collision in {schema}.{table}; sync requires the original migrated replica")
                            if table == 'job_parse_results' and record['is_current']:
                                remote.execute("UPDATE core.job_parse_results SET is_current = false WHERE source_posting_id = %s AND id <> %s AND is_current", (record['source_posting_id'], record['id']))
                            assignments = sql.SQL(', ').join(sql.SQL('{} = EXCLUDED.{}').format(sql.Identifier(c), sql.Identifier(c)) for c in columns if c != 'id')
                            query = sql.SQL('INSERT INTO {} ({}) VALUES ({}) ON CONFLICT (id) DO UPDATE SET {}').format(relation, sql.SQL(', ').join(map(sql.Identifier, columns)), sql.SQL(', ').join(sql.Placeholder() for _ in columns), assignments)
                            params = [Jsonb(v) if c in ('warnings', 'source_payload') else v for c, v in zip(columns, values)]
                            remote.execute(query, params)
                            count += 1
                        records = reader.fetchmany(200)
                    LOGGER.info(f"{schema}.{table}: {count} rows processed")
            if dry_run:
                remote.rollback()
                LOGGER.info("SUCCESS: dry run rolled back; no rows saved")
            else:
                # ALTER SEQUENCE RESTART is transactional, unlike setval.
                for schema, table, _ in TABLES:
                    seq = f'{table}_id_seq'
                    last, called = remote.execute(sql.SQL('SELECT last_value, is_called FROM {}').format(sql.Identifier(schema, seq))).fetchone()
                    maximum = remote.execute(sql.SQL('SELECT max(id) FROM {}').format(sql.Identifier(schema, table))).fetchone()[0] or 0
                    next_id = max(last + int(called), maximum + 1)
                    remote.execute(sql.SQL('ALTER SEQUENCE {} RESTART WITH {}').format(sql.Identifier(schema, seq), sql.Literal(next_id)))
                LOGGER.info("Sync transaction ready to commit")
        LOGGER.info("SUCCESS: sync completed")
        return 0
    except (psycopg.Error, ValueError) as exc:
        LOGGER.error(f"FAIL: sync rolled back ({type(exc).__name__}); check connectivity, schema and ID/key conflicts")
        return 1
