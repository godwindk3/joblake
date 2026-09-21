"""Read-only PostgreSQL health snapshots; JSON details and Markdown summary."""
import argparse
import json
import os
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import psycopg
import yaml
from dotenv import load_dotenv
from psycopg.rows import dict_row

from joblake.postgres import PostgresSettings


QUERIES = {
    "inventory": """
        SELECT source, count(*) total_jobs,
          count(*) FILTER (WHERE listing_status='active') active,
          count(*) FILTER (WHERE listing_status='expired') expired,
          count(*) FILTER (WHERE listing_status='unknown') unknown,
          count(*) FILTER (WHERE first_seen_at >= %(since)s) new_jobs,
          count(*) FILTER (WHERE raw_status='pending') pending_fetch,
          count(*) FILTER (WHERE raw_status='retryable_error' AND next_retry_at <= %(at)s) overdue_retry,
          count(*) FILTER (WHERE raw_status IN ('fetching','validating','uploading')
            AND updated_at < %(stale)s) stuck_fetch,
          min(first_seen_at) FILTER (WHERE raw_status='pending') oldest_pending_at
        FROM crawl_state.jobs GROUP BY source ORDER BY source""",
    "raw_and_backlog": """
        SELECT j.source, count(*) FILTER (WHERE o.purged_at IS NULL) raw_available,
          count(*) FILTER (WHERE o.purged_at IS NOT NULL) intentionally_purged,
          count(*) FILTER (WHERE o.purged_at IS NULL AND NOT EXISTS (
            SELECT 1 FROM core.job_parse_results r
            WHERE r.crawler_raw_object_id=o.id AND r.is_current
              AND r.raw_sha256=o.content_sha256
              AND r.quality_status IN ('accepted','partial'))) awaiting_usable_parse,
          min(o.fetched_at) FILTER (WHERE o.purged_at IS NULL AND NOT EXISTS (
            SELECT 1 FROM core.job_parse_results r
            WHERE r.crawler_raw_object_id=o.id AND r.is_current
              AND r.raw_sha256=o.content_sha256
              AND r.quality_status IN ('accepted','partial'))) oldest_unparsed_at
        FROM crawl_state.raw_objects o JOIN crawl_state.jobs j ON j.id=o.job_id
        GROUP BY j.source ORDER BY j.source""",
    "current_fetch_errors": """
        SELECT source, raw_status, last_error_type error_type, last_http_status http_status,
          count(*) jobs FROM crawl_state.jobs
        WHERE raw_status IN ('retryable_error','permanent_error','blocked','storage_missing','storage_corrupt')
        GROUP BY source,raw_status,last_error_type,last_http_status ORDER BY source,jobs DESC""",
    "current_parse_status": """
        WITH latest AS (
          SELECT DISTINCT ON (job_id) * FROM crawl_state.parse_attempts
          ORDER BY job_id,started_at DESC,id DESC)
        SELECT j.source,a.status,a.parser_version,count(*) jobs,
          count(*) FILTER (WHERE a.status='parsing' AND a.started_at < %(stale)s) stuck_parse
        FROM latest a JOIN crawl_state.jobs j ON j.id=a.job_id
        GROUP BY j.source,a.status,a.parser_version ORDER BY j.source,a.status""",
    "quality": """
        SELECT s.code source,r.quality_status,count(*) jobs,
          round(avg(r.completeness_score),2) average_completeness
        FROM core.job_parse_results r
        JOIN core.source_job_postings p ON p.id=r.source_posting_id
        JOIN ref.sources s ON s.id=p.source_id WHERE r.is_current
        GROUP BY s.code,r.quality_status ORDER BY s.code,r.quality_status""",
    "freshness": """
        SELECT source,phase,max(finished_at) last_success_at,
          extract(epoch FROM (%(at)s-max(finished_at)))/3600 hours_since_success
        FROM crawl_state.crawl_runs WHERE status='completed'
        GROUP BY source,phase ORDER BY source,phase""",
    "runs_in_window": """
        SELECT source,phase,status,cdc_status,cdc_reason,count(*) runs,
          sum(discovered_url_count) discovered_urls,sum(new_url_count) new_urls,
          sum(expired_url_count) expired_urls,sum(reappeared_url_count) reappeared_urls
        FROM crawl_state.crawl_runs WHERE started_at >= %(since)s
        GROUP BY source,phase,status,cdc_status,cdc_reason ORDER BY source,phase,status""",
    "fetch_attempts_in_window": """
        SELECT j.source,a.status,a.error_type,a.http_status,count(*) attempts,
          count(DISTINCT a.job_id) affected_jobs
        FROM crawl_state.fetch_attempts a JOIN crawl_state.jobs j ON j.id=a.job_id
        WHERE a.started_at >= %(since)s
        GROUP BY j.source,a.status,a.error_type,a.http_status ORDER BY j.source,attempts DESC""",
    "parse_attempts_in_window": """
        SELECT j.source,a.status,a.error_type,a.parser_version,count(*) attempts,
          count(DISTINCT a.job_id) affected_jobs
        FROM crawl_state.parse_attempts a JOIN crawl_state.jobs j ON j.id=a.job_id
        WHERE a.started_at >= %(since)s
        GROUP BY j.source,a.status,a.error_type,a.parser_version ORDER BY j.source,attempts DESC""",
    "issue_samples": """
        WITH latest AS (
          SELECT DISTINCT ON (job_id) * FROM crawl_state.parse_attempts
          ORDER BY job_id,started_at DESC,id DESC), issues AS (
          SELECT source,id job_id,url,'fetch' stage,raw_status status,
            last_error_type error_type,last_attempt_at occurred_at,fetch_attempt_count attempts
          FROM crawl_state.jobs
          WHERE raw_status IN ('retryable_error','permanent_error','blocked','storage_missing','storage_corrupt')
          UNION ALL
          SELECT j.source,j.id,j.url,'parse',a.status,a.error_type,a.started_at,a.attempt_number
          FROM latest a JOIN crawl_state.jobs j ON j.id=a.job_id
          WHERE a.status NOT IN ('success','parsing')
        ), ranked AS (
          SELECT *,row_number() OVER (
            PARTITION BY source,stage,status,error_type ORDER BY occurred_at DESC NULLS LAST,job_id) sample_rank
          FROM issues)
        SELECT * FROM ranked WHERE sample_rank <= %(samples)s ORDER BY source,stage,status,sample_rank""",
}

_FIELDS = ('title', 'employer_name_raw', 'description_text', 'requirements_text', 'salary_raw')
QUERIES['completeness'] = """
    SELECT s.code source,count(*) current_parses,""" + ','.join(
    f"count(*) FILTER (WHERE nullif(btrim(r.{field}),'') IS NULL) missing_{field}"
    for field in _FIELDS
) + """,count(*) FILTER (WHERE coalesce(cardinality(r.location_cities),0)=0) missing_location_cities
    FROM core.job_parse_results r
    JOIN core.source_job_postings p ON p.id=r.source_posting_id
    JOIN ref.sources s ON s.id=p.source_id WHERE r.is_current
    GROUP BY s.code ORDER BY s.code"""


def collect_report(connection, expected_sources, *, window_hours=24, stale_hours=6, samples=5):
    """One consistent snapshot. A failed query aborts instead of producing a partial report."""
    connection.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
    at = connection.execute('SELECT CURRENT_TIMESTAMP AS at').fetchone()['at']
    params = dict(at=at, since=at-timedelta(hours=window_hours),
                  stale=at-timedelta(hours=stale_hours), samples=samples)
    sections = {name: connection.execute(query, params).fetchall()
                for name, query in QUERIES.items()}
    sources = sorted(set(expected_sources) | {
        row['source'] for rows in sections.values() for row in rows})
    present = {row['source'] for row in sections['inventory']}
    inventory = {row['source']: row for row in sections['inventory']}
    summary = []
    for source in sources:
        total = inventory.get(source, {}).get('total_jobs', 0)
        fetch_errors = sum(row['jobs'] for row in sections['current_fetch_errors'] if row['source'] == source)
        parse_errors = sum(row['jobs'] for row in sections['current_parse_status']
                           if row['source'] == source and row['status'] not in ('success', 'parsing'))
        summary.append(dict(source=source, total_jobs=total,
                            current_fetch_errors=fetch_errors,
                            current_fetch_error_pct=round(100*fetch_errors/total, 2) if total else None,
                            latest_parse_errors=parse_errors))
    sections = {'summary': summary, **sections}
    for row in sections['completeness']:
        for key, value in list(row.items()):
            if key.startswith('missing_'):
                row[key + '_pct'] = round(100 * value / row['current_parses'], 2)
    return dict(schema_version=1, captured_at=at, window_start=params['since'],
                window_hours=window_hours, stale_hours=stale_hours,
                sources=sources, sources_without_jobs=sorted(set(sources)-present),
                sections=sections)


def render_markdown(report):
    lines = ['# JobLake data health', '', f"Captured: {report['captured_at']}",
             f"Window: {report['window_hours']} hours; stuck threshold: {report['stale_hours']} hours.", '',
             'Current errors and historical attempts are separate. Optional missing fields are warnings.',
             'Raw availability is database metadata, not a live MinIO integrity check.', '',
             'Sources without jobs: ' + (', '.join(report['sources_without_jobs']) or 'none')]
    def cell(value):
        return str(value if value is not None else '—').replace('|', '\\|').replace('\n', ' ').replace('\r', ' ')
    for name, rows in report['sections'].items():
        lines.extend(['', '## ' + name, ''])
        if not rows:
            lines.append('No records.')
            continue
        columns = list(rows[0])
        lines.extend(['| ' + ' | '.join(columns) + ' |', '| ' + ' | '.join(['---']*len(columns)) + ' |'])
        lines.extend('| ' + ' | '.join(cell(row[c]) for c in columns) + ' |' for row in rows)
    return '\n'.join(lines) + '\n'


def save_report(report, output_dir):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = report['captured_at'].strftime('%Y%m%dT%H%M%S%fZ') + '-' + uuid4().hex[:8]
    paths = []
    for extension, content in [('json', json.dumps(report, ensure_ascii=False, indent=2, default=str)),
                               ('md', render_markdown(report))]:
        path = output_dir / f'{stem}.{extension}'
        temporary = path.with_suffix(path.suffix + '.tmp')
        temporary.write_text(content, encoding='utf-8')
        os.replace(temporary, path)
        paths.append(path)
    return paths


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', default='data/state/reports/data_health')
    parser.add_argument('--config-dir', default='configs')
    parser.add_argument('--window-hours', type=int, default=24)
    parser.add_argument('--stale-hours', type=int, default=6)
    parser.add_argument('--samples', type=int, default=5)
    args = parser.parse_args(argv)
    if not (1 <= args.window_hours <= 8760 and 1 <= args.stale_hours <= 8760 and 1 <= args.samples <= 100):
        parser.error('hours must be 1..8760 and samples must be 1..100')
    load_dotenv()
    configs = sorted(Path(args.config_dir).glob('*.yaml'))
    if not configs:
        parser.error('config directory contains no source YAML files')
    sources = [yaml.safe_load(path.read_text(encoding='utf-8'))['source'] for path in configs]
    settings = PostgresSettings.from_config()
    with psycopg.connect(**settings.connection_kwargs(), row_factory=dict_row,
                         options='-c default_transaction_read_only=on -c statement_timeout=60000') as connection:
        report = collect_report(connection, sources, window_hours=args.window_hours,
                                stale_hours=args.stale_hours, samples=args.samples)
    paths = save_report(report, args.output_dir)
    print(render_markdown(report))
    print('Saved reports: ' + ', '.join(str(path) for path in paths))


if __name__ == '__main__':
    main()
