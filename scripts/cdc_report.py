"""Read-only listing-presence summary and URL events from local PostgreSQL."""
import argparse
import json
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from dotenv import load_dotenv
from joblake.postgres import PostgresSettings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', help='Optional source, e.g. topdev')
    parser.add_argument('--run-id', type=int, help='Only events from this run')
    parser.add_argument('--limit', type=int, default=100)
    args = parser.parse_args()
    if not 1 <= args.limit <= 1000:
        parser.error('--limit must be between 1 and 1000')
    load_dotenv(Path(__file__).resolve().parents[1] / '.env', override=False)
    with psycopg.connect(**PostgresSettings.from_config({}).connection_kwargs(), row_factory=dict_row) as c:
        c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        c.execute("SET LOCAL statement_timeout='20s'")
        counts = c.execute("""SELECT source,listing_status,count(*) AS urls FROM crawl_state.jobs
            WHERE (%s::text IS NULL OR source=%s) GROUP BY source,listing_status ORDER BY source,listing_status""",
            (args.source,args.source)).fetchall()
        runs = c.execute("""SELECT id,source,phase,status,cdc_status,cdc_reason,coverage_complete,
            expired_url_count,reappeared_url_count,cdc_finished_at FROM crawl_state.crawl_runs
            WHERE (%s::text IS NULL OR source=%s) AND (%s::bigint IS NULL OR id=%s)
              AND cdc_status<>'not_applicable' ORDER BY id DESC LIMIT %s""",
            (args.source,args.source,args.run_id,args.run_id,args.limit)).fetchall()
        events = c.execute("""SELECT e.id,e.run_id,j.source,j.url,e.event_type,e.previous_status,
            e.new_status,e.created_at FROM crawl_state.url_events e JOIN crawl_state.jobs j ON j.id=e.job_id
            WHERE (%s::text IS NULL OR j.source=%s) AND (%s::bigint IS NULL OR e.run_id=%s)
            ORDER BY e.id DESC LIMIT %s""",
            (args.source,args.source,args.run_id,args.run_id,args.limit)).fetchall()
        print(json.dumps({'listing_counts':counts,'runs':runs,'events':events}, ensure_ascii=False, indent=2, default=str))


if __name__ == '__main__':
    main()
