"""Read-only FTS plans on a fixed snapshot; never crawls, syncs or backfills.

Run with --target remote (Supabase) or local and --output PATH.
Includes the actual RPC and its underlying SELECT (PL/pgSQL hides inner plans).
"""
import argparse
import json
import os
from pathlib import Path

import psycopg
from dotenv import dotenv_values, load_dotenv

from joblake.supabase_sync import configure


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', choices=['local', 'remote'], required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--reader-env', type=Path, help='Optional file containing the website DATABASE_URL')
    args = parser.parse_args()
    load_dotenv()
    configure()
    env_name = 'SUPABASE_DATABASE_URL' if args.target == 'remote' else 'LOCAL_DATABASE_URL'
    report = {'target': args.target, 'plans': []}
    url = dotenv_values(args.reader_env)['DATABASE_URL'] if args.reader_env else os.environ[env_name]
    # Compatible with the website's transaction pooler.
    with psycopg.connect(url, connect_timeout=15, prepare_threshold=None) as c:
        c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        c.execute("SET LOCAL statement_timeout='30s'")
        report['version'] = c.execute('SELECT version()').fetchone()[0]
        report['rows'] = c.execute('SELECT count(*) FROM serving.jobs').fetchone()[0]
        report['definition'] = c.execute("SELECT pg_get_functiondef('serving.search_jobs(text,text,text,integer,integer)'::regprocedure)").fetchone()[0]
        if c.execute('SELECT current_user').fetchone()[0] != 'joblake_web_reader':
            c.execute('SET LOCAL ROLE joblake_web_reader')
        report['reader_privileges'] = dict(c.execute("""SELECT p,has_table_privilege(current_user,'serving.jobs',p)
            FROM unnest(ARRAY['SELECT','INSERT','UPDATE','DELETE','TRUNCATE']) p""").fetchall())
        for query, prefix in [('data eng', 'data & eng:*'), ('data enginee', 'data & enginee:*'),
                              ('data engineer', 'data & engineer:*'), ('dev', 'dev:*')]:
            for mode in ['legacy', 'prefix', 'rpc']:
                if mode == 'rpc':
                    statement = 'SELECT * FROM serving.search_jobs(%s,NULL,NULL,20,0)'
                    params = (query,)
                else:
                    q = (c.execute("SELECT websearch_to_tsquery('pg_catalog.simple',serving.normalize_search(%s))::text", (query,)).fetchone()[0]
                         if mode == 'legacy' else prefix)
                    statement = '''SELECT j.id,j.title,j.employer_name_raw,j.canonical_url,
                        s.code,s.display_name,j.location_cities,j.salary_raw,j.employment_type_raw,
                        j.experience_raw,j.posted_at,j.last_seen_at,ts_rank(j.search_vector,%s::tsquery) AS score
                        FROM serving.jobs j JOIN serving.sources s ON s.id=j.source_id
                        WHERE j.search_vector @@ %s::tsquery
                        ORDER BY score DESC,j.posted_at DESC NULLS LAST,j.id DESC LIMIT 20'''
                    params = (q, q)
                # Warm once, retain three measured samples and all buffers/plans.
                c.execute(statement, params).fetchall()
                samples = [c.execute('EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) ' + statement, params).fetchone()[0][0]
                           for _ in range(3)]
                entry = {'query': query, 'mode': mode, 'samples': samples}
                if mode != 'rpc':
                    entry['matches'] = c.execute('SELECT count(*) FROM serving.jobs WHERE search_vector @@ %s::tsquery', (q,)).fetchone()[0]
                report['plans'].append(entry)
        report['sample_titles'] = c.execute("SELECT title,score FROM serving.search_jobs('data engineer',NULL,NULL,10,0)").fetchall()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    for entry in report['plans']:
        print(entry['query'], entry['mode'], 'matches=', entry.get('matches'),
              'ms=', [round(s['Execution Time'], 3) for s in entry['samples']])


if __name__ == '__main__':
    main()
