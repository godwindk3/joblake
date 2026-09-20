"""Bounded, opt-in MinIO retention. Never deletes core/ref analytical rows."""
import argparse
import hashlib
import json
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from dotenv import load_dotenv
from minio.error import S3Error

from joblake.config import load_config
from joblake.postgres import PostgresSettings
from joblake.storage import MinioRawStorage


CANDIDATES = """
SELECT j.id AS job_id,j.source,j.listing_status AS reason,r.*
FROM crawl_state.jobs j JOIN crawl_state.raw_objects r ON r.job_id=j.id
WHERE j.source=%s AND r.purged_at IS NULL AND r.storage_provider='minio'
 AND j.raw_status IN ('raw_ready','storage_missing')
 AND NOT EXISTS (SELECT 1 FROM crawl_state.parse_attempts a
                 WHERE a.job_id=j.id AND a.status='parsing')
 AND EXISTS (SELECT 1 FROM core.source_job_postings p
             JOIN ref.sources s ON s.id=p.source_id
             JOIN core.job_parse_results pr ON pr.source_posting_id=p.id
             WHERE s.code=j.source AND p.crawler_job_id=j.id
               AND pr.is_current AND pr.raw_sha256=r.content_sha256
               AND pr.raw_bucket=r.bucket_name AND pr.raw_object_key=r.object_key)
 AND (
   (j.listing_status='expired' AND j.expired_at < CURRENT_TIMESTAMP - %s * INTERVAL '1 day'
    AND j.last_seen_at < j.expired_at)
   OR (j.listing_status='unknown' AND r.stored_at < CURRENT_TIMESTAMP - %s * INTERVAL '1 day'
       AND EXISTS (
         SELECT 1 FROM crawl_state.crawl_runs cr
         JOIN crawl_state.cdc_sources cs ON cs.source=cr.source AND cs.scope_hash=cr.scope_hash
         WHERE cr.source=j.source AND cr.cdc_status IN ('baseline','applied')
           AND cr.coverage_complete AND cr.started_at > j.last_seen_at
         GROUP BY cr.scope_hash
         HAVING count(*) >= 2 AND max(cr.cdc_finished_at)-min(cr.cdc_finished_at) >= INTERVAL '7 days'))
 )
ORDER BY r.stored_at,r.id
"""


def object_state(client, row):
    """Verify content, not just size: fixed URL keys can be overwritten."""
    try:
        stat = client.stat_object(row['bucket_name'], row['object_key'])
    except S3Error as exc:
        if exc.code in ('NoSuchKey', 'NoSuchObject'):
            return 'missing'
        raise
    if stat.size != row['content_length_bytes']:
        return 'changed'
    response = client.get_object(row['bucket_name'], row['object_key'])
    try:
        digest = hashlib.sha256()
        for chunk in response.stream(1024 * 1024):
            digest.update(chunk)
    finally:
        response.close()
        response.release_conn()
    return 'matching' if digest.hexdigest() == row['content_sha256'] else 'changed'


def check_storage_policy(client, bucket):
    if client.get_bucket_versioning(bucket).status in ('Enabled', 'Suspended'):
        raise RuntimeError('Apply requires an unversioned bucket; version cleanup needs a separate policy')
    try:
        lifecycle = client.get_bucket_lifecycle(bucket)
    except S3Error as exc:
        if exc.code == 'NoSuchLifecycleConfiguration':
            return
        raise
    if any(rule.status == 'Enabled' and rule.expiration is not None for rule in lifecycle.rules):
        raise RuntimeError('Review/disable bucket expiration rules before apply; they bypass DB retention')


def run(config, *, apply=False, expired_days=7, unknown_days=30,
        max_objects=200, max_bytes=250 * 1024 * 1024):
    if min(expired_days, unknown_days, max_objects, max_bytes) < 1:
        raise ValueError('Retention and limits must be positive')
    config['storage']['ensure_bucket'] = False
    storage = MinioRawStorage.from_config(config)
    if apply:
        check_storage_policy(storage.client, storage.bucket_name)
    report = dict(mode='apply' if apply else 'dry_run', candidates=0,
                  candidate_bytes=0, deleted=0, deleted_bytes=0, missing=0,
                  changed=0, busy_sources=[], groups={}, selected=[])
    kwargs = PostgresSettings.from_config(config).connection_kwargs()
    with psycopg.connect(**kwargs, row_factory=dict_row, autocommit=True) as c:
        c.execute("SET statement_timeout='30s'")
        sources = c.execute('SELECT DISTINCT source FROM crawl_state.jobs ORDER BY source').fetchall()
        for source in sources:
            lock = 'joblake-state:' + source['source']
            if not c.execute('SELECT pg_try_advisory_lock(hashtextextended(%s,0)) AS ok', (lock,)).fetchone()['ok']:
                report['busy_sources'].append(source['source'])
                continue
            try:
                rows = c.execute(CANDIDATES, (source['source'], expired_days, unknown_days)).fetchall()
                for row in rows:
                    # Only this configured bucket/detail prefix is in scope.
                    if row['bucket_name'] != storage.bucket_name or not row['object_key'].startswith(storage.prefix + '/detail/'):
                        continue
                    report['candidates'] += 1
                    report['candidate_bytes'] += row['content_length_bytes']
                    group = report['groups'].setdefault(source['source'] + ':' + row['reason'], {'objects': 0, 'bytes': 0})
                    group['objects'] += 1
                    group['bytes'] += row['content_length_bytes']
                    if len(report['selected']) >= max_objects or sum(x['bytes'] for x in report['selected']) + row['content_length_bytes'] > max_bytes:
                        continue
                    report['selected'].append({'job_id': row['job_id'], 'key': row['object_key'], 'reason': row['reason'], 'bytes': row['content_length_bytes']})
                    if not apply:
                        continue
                    # Intent is committed before I/O. Retry rechecks the same candidate;
                    # a missing object completes the database side after an interrupted delete.
                    log_id = c.execute('''INSERT INTO crawl_state.raw_cleanup_log
                        (job_id,bucket_name,object_key,object_version,content_sha256,bytes,reason,status)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,'pending') RETURNING id''',
                        (row['job_id'], row['bucket_name'], row['object_key'], row['object_version'], row['content_sha256'], row['content_length_bytes'], row['reason'])).fetchone()['id']
                    state = object_state(storage.client, row)
                    if state == 'matching':
                        # Verify the lock-owning connection is alive immediately before deletion.
                        c.execute('SELECT 1')
                        storage.client.remove_object(row['bucket_name'], row['object_key'])
                        state = 'deleted'
                    with c.transaction():
                        c.execute('UPDATE crawl_state.raw_cleanup_log SET status=%s,finished_at=CURRENT_TIMESTAMP WHERE id=%s', (state, log_id))
                        if state != 'changed':
                            c.execute('UPDATE crawl_state.raw_objects SET purged_at=CURRENT_TIMESTAMP WHERE id=%s', (row['id'],))
                            c.execute("UPDATE crawl_state.jobs SET raw_status='storage_missing' WHERE id=%s", (row['job_id'],))
                    report[state] += 1
                    if state == 'deleted':
                        report['deleted_bytes'] += row['content_length_bytes']
            finally:
                c.execute('SELECT pg_advisory_unlock(hashtextextended(%s,0))', (lock,))
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config', default='configs/itviec.yaml')
    p.add_argument('--apply', action='store_true')
    p.add_argument('--expired-days', type=int, default=7)
    p.add_argument('--unknown-days', type=int, default=30)
    p.add_argument('--max-objects', type=int, default=200)
    p.add_argument('--max-mib', type=int, default=250)
    args = p.parse_args()
    load_dotenv(Path.cwd() / '.env', override=False)
    result = run(load_config(args.config), apply=args.apply,
                 expired_days=args.expired_days, unknown_days=args.unknown_days,
                 max_objects=args.max_objects, max_bytes=args.max_mib * 1024 * 1024)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
