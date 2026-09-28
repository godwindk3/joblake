"""Read-only verification of installed enrichment schemas. Never calls model APIs."""
import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv

from joblake.enrichment.serving import COLUMNS
from joblake.enrichment.service import load_config
from joblake.supabase_sync import configure
from datetime import datetime


def main():
    load_dotenv(Path(__file__).resolve().parents[1] / '.env')
    configure()
    config = load_config('configs/enrichment.yaml')
    with psycopg.connect(os.environ['LOCAL_DATABASE_URL']) as c:
        c.execute('SET TRANSACTION READ ONLY')
        cutoff = c.execute('SELECT eligible_from FROM core.enrichment_settings').fetchone()[0]
        assert cutoff == datetime.fromisoformat(config['eligible_from'])
        print('Local cutoff:', cutoff.isoformat())
        print('Eligible current jobs:', c.execute('SELECT count(*) FROM core.enrichment_candidates').fetchone()[0])
        print('Queue:', c.execute('SELECT status,count(*) FROM core.job_enrichments GROUP BY status').fetchall())
    with psycopg.connect(os.environ['SUPABASE_DATABASE_URL']) as c:
        c.execute('SET TRANSACTION READ ONLY')
        cols = {r[0] for r in c.execute("""SELECT column_name FROM information_schema.columns
            WHERE table_schema='serving' AND table_name='jobs'""")}
        assert set(COLUMNS).issubset(cols)
        rls = c.execute("SELECT relrowsecurity FROM pg_class WHERE oid='serving.jobs'::regclass").fetchone()[0]
        assert rls, 'Serving RLS must remain enabled'
        print('Serving enrichment columns: PASS; RLS enabled: PASS')
    print('Enrichment installation verified')


if __name__ == '__main__':
    main()
