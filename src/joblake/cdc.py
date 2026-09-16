"""Listing-presence CDC. This never interprets absence as an HTTP deletion."""
import hashlib
import json


def discovery_scope(config):
    targets = [target for target in config['discovery']['targets'] if target.get('enabled', True)]
    names = [target['name'] for target in targets]
    if len(names) != len(set(names)):
        raise ValueError('Discovery target names must be unique')
    # Include adapter-specific target filters too, excluding only traversal controls.
    business_targets = [{k: v for k, v in target.items()
                         if k not in {'enabled', 'start_page', 'total_pages'}} for target in targets]
    payload = {'source': config['source'], 'adapter': config.get('source_adapter'),
               'scope_version': config.get('cdc', {}).get('scope_version', 1),
               'targets': sorted(business_targets, key=lambda item: item['name'])}
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False,
                                      separators=(',', ':')).encode()).hexdigest()
    return digest, sorted(names)


class PostgresCdcMixin:
    def prepare_cdc_run(self, run_id, phase, config):
        enabled = config.get('cdc', {}).get('enabled', False) and phase in {'full', 'discovery'}
        scope, names = discovery_scope(config) if enabled else (None, [])
        with self._connect() as c:
            c.execute("""UPDATE crawl_state.crawl_runs SET cdc_status='skipped',
                cdc_reason='interrupted_run', cdc_finished_at=CURRENT_TIMESTAMP
                WHERE source=(SELECT source FROM crawl_state.crawl_runs WHERE id=%s)
                  AND id<%s AND cdc_status='pending'""", (run_id, run_id))
            c.execute("""UPDATE crawl_state.crawl_runs SET phase=%s, scope_hash=%s,
                expected_targets=%s::jsonb, cdc_status=%s WHERE id=%s""",
                (phase, scope, json.dumps(names), 'pending' if enabled else 'not_applicable', run_id))

    def record_discovery_coverage(self, target_id, complete, reason):
        with self._connect() as c:
            c.execute("""UPDATE crawl_state.discovery_targets
                SET coverage_complete=%s, termination_reason=%s WHERE id=%s""",
                (complete, reason, target_id))

    def finalize_cdc(self, run_id, finished_at):
        if self._run_connection is None:
            raise RuntimeError('CDC finalization requires the source_run lock')
        with self._connect() as c:
            run = c.execute('SELECT * FROM crawl_state.crawl_runs WHERE id=%s FOR UPDATE', (run_id,)).fetchone()
            if run is None:
                raise ValueError('Unknown CDC run')
            if run['source'] != self._run_source:
                raise RuntimeError('CDC source does not match the held lock')
            if run['cdc_status'] != 'pending':
                return self._cdc_summary(run)
            targets = c.execute('SELECT * FROM crawl_state.discovery_targets WHERE run_id=%s', (run_id,)).fetchall()
            expected = run['expected_targets']
            reason = None
            if run['phase'] not in {'full', 'discovery'} or run['status'] != 'running':
                reason = 'invalid_run'
            elif c.execute("""SELECT 1 FROM crawl_state.crawl_runs
                WHERE source=%s AND id>%s AND phase IN ('full','discovery') LIMIT 1""",
                (run['source'], run_id)).fetchone():
                reason = 'superseded_run'
            elif not expected or sorted(t['target_name'] for t in targets) != sorted(expected):
                reason = 'incomplete_targets'
            elif any(not t['coverage_complete'] or t['status'] != 'completed' for t in targets):
                reason = 'incomplete_coverage'
            elif not c.execute('SELECT 1 FROM crawl_state.jobs WHERE source=%s AND last_seen_run_id=%s LIMIT 1',
                               (run['source'], run_id)).fetchone():
                reason = 'zero_urls'
            if reason:
                return self._finish_cdc(c, run_id, 'skipped', reason, finished_at, False, 0, 0)

            previous = c.execute('SELECT * FROM crawl_state.cdc_sources WHERE source=%s FOR UPDATE',
                                 (run['source'],)).fetchone()
            baseline = previous is None or previous['scope_hash'] != run['scope_hash']
            expired = reappeared = 0
            if baseline:
                c.execute("""UPDATE crawl_state.jobs SET listing_status='unknown', expired_at=NULL,
                    expired_run_id=NULL, tracking_scope_hash=NULL WHERE source=%s""", (run['source'],))
            else:
                for event, old, new, seen in [('EXPIRED', 'active', 'expired', False),
                                              ('REAPPEARED', 'expired', 'active', True)]:
                    rows = c.execute("""SELECT id FROM crawl_state.jobs
                        WHERE source=%s AND tracking_scope_hash=%s AND listing_status=%s
                        AND ((last_seen_run_id IS NOT DISTINCT FROM %s) = %s) FOR UPDATE""",
                        (run['source'], run['scope_hash'], old, run_id, seen)).fetchall()
                    for row in rows:
                        c.execute("""INSERT INTO crawl_state.url_events
                            (job_id,run_id,event_type,previous_status,new_status,created_at)
                            VALUES (%s,%s,%s,%s,%s,%s)""", (row['id'], run_id, event, old, new, finished_at))
                        c.execute("""UPDATE crawl_state.jobs SET listing_status=%s,
                            expired_at=%s, expired_run_id=%s, updated_at=CURRENT_TIMESTAMP WHERE id=%s""",
                            (new, finished_at if not seen else None, run_id if not seen else None, row['id']))
                    if seen:
                        reappeared = len(rows)
                    else:
                        expired = len(rows)
            c.execute("""UPDATE crawl_state.jobs SET listing_status='active', tracking_scope_hash=%s,
                expired_at=NULL, expired_run_id=NULL, updated_at=CURRENT_TIMESTAMP
                WHERE source=%s AND last_seen_run_id=%s""", (run['scope_hash'], run['source'], run_id))
            c.execute("""INSERT INTO crawl_state.cdc_sources(source,scope_hash,last_applied_run_id)
                VALUES (%s,%s,%s) ON CONFLICT (source) DO UPDATE SET
                scope_hash=EXCLUDED.scope_hash,last_applied_run_id=EXCLUDED.last_applied_run_id""",
                (run['source'], run['scope_hash'], run_id))
            return self._finish_cdc(c, run_id, 'baseline' if baseline else 'applied',
                'initial_or_changed_scope' if baseline else None, finished_at, True, expired, reappeared)

    @staticmethod
    def _cdc_summary(run):
        return {'status': run['cdc_status'], 'reason': run['cdc_reason'],
                'expired': run['expired_url_count'], 'reappeared': run['reappeared_url_count']}

    def _finish_cdc(self, c, run_id, status, reason, at, complete, expired, reappeared):
        row = c.execute("""UPDATE crawl_state.crawl_runs SET cdc_status=%s, cdc_reason=%s,
            cdc_finished_at=%s, coverage_complete=%s, expired_url_count=%s, reappeared_url_count=%s
            WHERE id=%s RETURNING *""", (status, reason, at, complete, expired, reappeared, run_id)).fetchone()
        return self._cdc_summary(row)
