"""Create an empty serving schema. Never reset data as part of a sync."""
import logging
import os
from importlib.resources import files

import psycopg
from dotenv import load_dotenv

from joblake.logging import configure_logging
from joblake.supabase_sync import SERVING_DDL

LOGGER = logging.getLogger(__name__)


def main():
    load_dotenv()
    configure_logging()
    if not os.getenv('SUPABASE_DATABASE_URL'):
        LOGGER.error('Missing SUPABASE_DATABASE_URL')
        return 2
    try:
        with psycopg.connect(os.environ['SUPABASE_DATABASE_URL'], connect_timeout=15) as c:
            c.execute("SET LOCAL lock_timeout='10s'")
            c.execute(SERVING_DDL)
            # Private until an application-specific read policy is deliberately configured.
            c.execute('REVOKE ALL ON SCHEMA serving FROM anon, authenticated')
            c.execute('REVOKE ALL ON ALL TABLES IN SCHEMA serving FROM anon, authenticated')
            c.execute(files('joblake').joinpath('sql/serving_search_v1.sql').read_text(encoding='utf-8'))
        LOGGER.info('SUCCESS: empty serving.sources and serving.jobs created with RLS')
        return 0
    except psycopg.Error as exc:
        LOGGER.error('FAIL: setup rolled back (%s); serving must not already exist', type(exc).__name__)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
