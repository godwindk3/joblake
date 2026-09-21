"""Read-only local audit for website handoff. Never emits connection secrets."""
import json
import os
from pathlib import Path
from datetime import datetime, timezone

import psycopg
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
from dotenv import load_dotenv


def main():
    load_dotenv('.env')
    dsn = os.getenv('LOCAL_DATABASE_URL') or make_conninfo(
        host=os.getenv('POSTGRES_HOST', 'localhost'), port=os.getenv('POSTGRES_PORT', '5432'),
        dbname=os.getenv('POSTGRES_DB', 'joblake'), user=os.getenv('POSTGRES_USER', 'joblake'),
        password=os.environ['POSTGRES_PASSWORD'])
    result = {'captured_at': datetime.now(timezone.utc).isoformat()}
    schemas = "('ref','core','crawl_state','public')"
    queries = {
        'database': "SELECT current_setting('server_version') version, pg_database_size(current_database()) bytes, current_setting('transaction_read_only') read_only",
        'tables': f"SELECT n.nspname schema,c.relname name,c.relkind,c.relrowsecurity rls,c.relforcerowsecurity force_rls,pg_total_relation_size(c.oid) bytes FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname IN {schemas} AND c.relkind IN ('r','p','v','m') ORDER BY 1,2",
        'columns': f"SELECT table_schema,table_name,column_name,data_type,udt_name,is_nullable FROM information_schema.columns WHERE table_schema IN {schemas} ORDER BY table_schema,table_name,ordinal_position",
        'constraints': f"SELECT n.nspname schema,c.relname table_name,con.conname,pg_get_constraintdef(con.oid) definition FROM pg_constraint con JOIN pg_class c ON c.oid=con.conrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname IN {schemas} ORDER BY 1,2,3",
        'indexes': f"SELECT schemaname,tablename,indexname,indexdef FROM pg_indexes WHERE schemaname IN {schemas} ORDER BY 1,2,3",
        'migrations': 'SELECT * FROM public.alembic_version',
        'counts': "SELECT 'postings' entity,count(*) n FROM core.source_job_postings UNION ALL SELECT 'parses',count(*) FROM core.job_parse_results UNION ALL SELECT 'current_parses',count(*) FROM core.job_parse_results WHERE is_current UNION ALL SELECT 'crawl_jobs',count(*) FROM crawl_state.jobs",
        'sources': "SELECT s.code,count(DISTINCT p.id) postings,count(r.id) current_parses,max(r.parsed_at) last_parsed FROM ref.sources s LEFT JOIN core.source_job_postings p ON p.source_id=s.id LEFT JOIN core.job_parse_results r ON r.source_posting_id=p.id AND r.is_current GROUP BY s.code ORDER BY s.code",
        'statuses': 'SELECT source,listing_status,count(*) n FROM crawl_state.jobs GROUP BY 1,2 ORDER BY 1,2',
        'quality': 'SELECT quality_status,is_current,count(*) n FROM core.job_parse_results GROUP BY 1,2 ORDER BY 1,2',
        'integrity': "SELECT count(*) FILTER (WHERE j.id IS NULL) missing_crawl_job,count(*) FILTER (WHERE j.source<>s.code) source_mismatch,count(*) FILTER (WHERE r.id IS NULL) no_current_parse FROM core.source_job_postings p JOIN ref.sources s ON s.id=p.source_id LEFT JOIN crawl_state.jobs j ON j.id=p.crawler_job_id LEFT JOIN core.job_parse_results r ON r.source_posting_id=p.id AND r.is_current",
        'duplicate_current': 'SELECT source_posting_id,count(*) n FROM core.job_parse_results WHERE is_current GROUP BY 1 HAVING count(*)>1',
        'publishability': "SELECT s.code,j.listing_status,count(*) n,count(*) FILTER (WHERE r.expires_at<=CURRENT_TIMESTAMP) past_deadline,count(*) FILTER (WHERE nullif(btrim(r.title),'') IS NOT NULL AND p.canonical_url ~ '^https?://') basic_valid FROM core.source_job_postings p JOIN ref.sources s ON s.id=p.source_id JOIN core.job_parse_results r ON r.source_posting_id=p.id AND r.is_current LEFT JOIN crawl_state.jobs j ON j.id=p.crawler_job_id GROUP BY 1,2 ORDER BY 1,2",
        'cdc_runs': "SELECT source,cdc_status,cdc_reason,count(*) n,max(started_at) latest FROM crawl_state.crawl_runs GROUP BY 1,2,3 ORDER BY 1,2,3",
        'sample': "SELECT s.code,p.id,r.title,r.salary_raw,r.location_cities,r.experience_raw,r.employment_type_raw,r.categories_raw,r.domains_raw,r.skills_raw FROM ref.sources s CROSS JOIN LATERAL (SELECT * FROM core.source_job_postings p WHERE p.source_id=s.id ORDER BY md5(p.id::text) LIMIT 5) p JOIN core.job_parse_results r ON r.source_posting_id=p.id AND r.is_current ORDER BY s.code,p.id",
        'sizes': "SELECT round(avg(pg_column_size(r))) avg_parse_bytes,round(avg(octet_length(coalesce(description_text,''))+octet_length(coalesce(requirements_text,''))+octet_length(coalesce(benefits_text,'')))) avg_detail_text_bytes,round(avg(pg_column_size(source_payload))) avg_payload_bytes FROM core.job_parse_results r WHERE is_current",
        'projection_size': "SELECT count(*) n,sum(pg_column_size(ROW(p.id,p.source_id,p.canonical_url,r.title,r.employer_name_raw,r.location_cities,r.salary_raw,r.skills_raw,r.employment_type_raw,r.experience_raw,r.posted_at,p.first_seen_at,r.expires_at,j.listing_status,j.last_seen_at))) lean_row_bytes,sum(octet_length(coalesce(r.description_text,''))+octet_length(coalesce(r.requirements_text,''))+octet_length(coalesce(r.benefits_text,''))) detail_text_bytes FROM core.source_job_postings p JOIN core.job_parse_results r ON r.source_posting_id=p.id AND r.is_current JOIN crawl_state.jobs j ON j.id=p.crawler_job_id",
    }
    fields = ['title','employer_name_raw','description_text','requirements_text','benefits_text','salary_raw','experience_raw','employment_type_raw']
    empty = [f"count(*) FILTER (WHERE nullif(btrim(r.{x}),'') IS NULL) AS missing_{x}" for x in fields]
    empty += [f"count(*) FILTER (WHERE coalesce(cardinality(r.{x}),0)=0) AS missing_{x}" for x in ['location_cities','skills_raw','categories_raw','domains_raw']]
    empty += [f"count(*) FILTER (WHERE r.{x} IS NULL) AS missing_{x}" for x in ['posted_at','expires_at']]
    queries['completeness'] = 'SELECT s.code,count(*) n,' + ','.join(empty) + ' FROM core.job_parse_results r JOIN core.source_job_postings p ON p.id=r.source_posting_id JOIN ref.sources s ON s.id=p.source_id WHERE r.is_current GROUP BY s.code ORDER BY s.code'
    with psycopg.connect(dsn,connect_timeout=10, row_factory=dict_row,
                         options='-c default_transaction_read_only=on -c statement_timeout=30000') as c:
        c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        for name, query in queries.items():
            try:
                with c.transaction():
                    result[name] = c.execute(query).fetchall()
            except psycopg.Error as exc:
                result[name] = {'error': type(exc).__name__, 'sqlstate': exc.sqlstate}
    target=Path('tmp/web-data-audit.json')
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('columns','constraints','indexes','sample','tables','cdc_runs')},ensure_ascii=False,default=str))
    return int(any(isinstance(v, dict) and 'error' in v for v in result.values()))


if __name__ == '__main__':
    raise SystemExit(main())
