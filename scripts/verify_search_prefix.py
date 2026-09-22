"""Read-only post-deployment smoke checks using the website reader credentials."""
import argparse
import json
from pathlib import Path

import psycopg
from dotenv import dotenv_values


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reader-env', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    checks = []
    with psycopg.connect(dotenv_values(args.reader_env)['DATABASE_URL'],
                         connect_timeout=15, prepare_threshold=None) as c:
        c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        c.execute("SET LOCAL statement_timeout='30s'")
        assert c.execute('SELECT current_user').fetchone()[0] == 'joblake_web_reader'

        def rpc(query, source=None, city=None, limit=100, offset=0):
            return c.execute('SELECT id,score FROM serving.search_jobs(%s,%s,%s,%s,%s)',
                             (query, source, city, limit, offset)).fetchall()

        def expected(query):
            return c.execute('''SELECT j.id,ts_rank(j.search_vector,%s::tsquery) AS score
                FROM serving.jobs j JOIN serving.sources s ON s.id=j.source_id
                WHERE j.search_vector @@ %s::tsquery
                ORDER BY score DESC,j.posted_at DESC NULLS LAST,j.id DESC LIMIT 100''',
                (query, query)).fetchall()

        for raw, q in [('data eng', 'data & eng:*'), ('data enginee', 'data & enginee:*'),
                       ('data engineer', 'data & engineer:*'), ('enginee', 'enginee:*'),
                       ('data en', 'data & en'), ('dat enginee', 'dat & enginee:*')]:
            assert rpc(raw) == expected(q), raw
            assert rpc(raw) == rpc(raw + ' \t\n'), raw
            checks.append(raw)
        for raw in ['"data engineer"', '"data enginee"', 'data OR enginee', 'data or enginee',
                    'data -engineer', 'data -(enginee)', '"full-stack" dev']:
            q = c.execute("SELECT websearch_to_tsquery('simple',serving.normalize_search(%s))::text", (raw,)).fetchone()[0]
            assert rpc(raw) == expected(q), raw
            checks.append(raw)
        for raw, normalized in [('kỹ thuậ', 'ky thua'), ('C++', 'cplusplus'), ('C#', 'csharp'),
                                ('.NET', 'dotnet'), ('Node.js', 'nodejs')]:
            assert rpc(raw) == rpc(normalized), raw
            checks.append(raw)
        for raw in ['!!!', ':*&|<>', "'; DROP TABLE serving.jobs; --", 'x' * 200]:
            rpc(raw)
        assert rpc('') == rpc(None)
        for params in [('x' * 201, 20, 0), ('x', 101, 0), ('x', 0, 0),
                       ('x', 20, -1), ('x', 20, 10001)]:
            try:
                with c.transaction():
                    rpc(params[0], limit=params[1], offset=params[2])
            except psycopg.errors.InvalidParameterValue:
                pass
            else:
                raise AssertionError('Expected invalid_parameter_value')
        checks.append('empty, punctuation, special characters, bounds')
        all_rows = c.execute("""SELECT j.id,ts_rank(search_vector,'data & eng:*'::tsquery) AS score
            FROM serving.jobs j WHERE search_vector @@ 'data & eng:*'::tsquery
            ORDER BY score DESC,posted_at DESC NULLS LAST,id DESC""").fetchall()
        pages = []
        for offset in range(0, len(all_rows) + 20, 20):
            pages.extend(rpc('data eng', limit=20, offset=offset))
        assert pages == all_rows and len({r[0] for r in pages}) == len(pages)
        checks.append('stable pagination without duplicates')
        source, city = c.execute("""SELECT s.code,j.location_cities[1]
            FROM serving.jobs j JOIN serving.sources s ON j.source_id=s.id
            WHERE j.search_vector @@ 'data & eng:*'::tsquery
              AND cardinality(j.location_cities)>0 LIMIT 1""").fetchone()
        filtered = rpc('data eng', source, city)
        assert filtered
        for job_id, _ in filtered:
            assert c.execute('''SELECT s.code=%s AND j.location_cities @> ARRAY[%s]::text[]
                FROM serving.jobs j JOIN serving.sources s ON s.id=j.source_id WHERE j.id=%s''',
                (source, city, job_id)).fetchone()[0]
        checks.append('source and city filters')
        for table in ['serving.jobs', 'serving.sources']:
            for privilege in ['INSERT', 'UPDATE', 'DELETE', 'TRUNCATE']:
                assert not c.execute('SELECT has_table_privilege(current_user,%s,%s)', (table, privilege)).fetchone()[0]
        assert c.execute("SELECT NOT prosecdef FROM pg_proc WHERE oid='serving.search_jobs(text,text,text,integer,integer)'::regprocedure").fetchone()[0]
        checks.append('reader has no writes; SECURITY INVOKER')
    args.output.write_text(json.dumps({'passed': checks, 'pagination_rows': len(pages)},
                                      ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'{len(checks)} checks passed; {len(pages)} rows paginated without duplicates')


if __name__ == '__main__':
    main()
