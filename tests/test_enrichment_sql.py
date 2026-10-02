"""Local disposable PostgreSQL tests; JOBLAKE_TEST_ENRICHMENT=1 opts in."""
import os
import unittest
import uuid
from importlib.resources import files

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from dotenv import load_dotenv

from joblake.enrichment.store import Store
from joblake.enrichment.serving import projection
from joblake.enrichment.schema import FIELDS
from joblake.enrichment.backfill import normalize, preview, selected_candidates, run as backfill_run
from joblake.enrichment.service import load_config, process
from joblake.enrichment.providers import Result
from joblake.supabase_sync import configure, JOBS_QUERY, JOB_COLUMNS, SERVING_DDL, sync
from unittest.mock import patch
from test_supabase_serving import LOCAL_DDL


@unittest.skipUnless(os.getenv('JOBLAKE_TEST_ENRICHMENT') == '1', 'Local SQL opt-in required')
class EnrichmentSQLTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        load_dotenv()
        configure()
        cls.admin = os.environ['LOCAL_DATABASE_URL']
        cls.name = 'joblake_enrichment_test_' + uuid.uuid4().hex[:12]
        with psycopg.connect(cls.admin, autocommit=True) as c:
            c.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(cls.name)))
        cls.url = make_conninfo(cls.admin, dbname=cls.name)
        with psycopg.connect(cls.url) as c:
            c.execute(LOCAL_DDL)
            c.execute("ALTER TABLE core.job_parse_results ADD COLUMN fetched_at timestamptz DEFAULT '2026-09-26T01:00:00+07:00'")
            c.execute(files('joblake').joinpath('sql/enrichment.sql').read_text(encoding='utf-8'))
            c.execute(files('joblake').joinpath('sql/enrichment_batches.sql').read_text(encoding='utf-8'))
            c.execute(SERVING_DDL)
            c.execute(files('joblake').joinpath('sql/serving_enrichment.sql').read_text(encoding='utf-8'))

    @classmethod
    def tearDownClass(cls):
        with psycopg.connect(cls.admin, autocommit=True) as c:
            c.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(cls.name)))

    def setUp(self):
        self.c = psycopg.connect(self.url, autocommit=True)
        self.addCleanup(self.c.close)
        self.c.execute('TRUNCATE core.enrichment_attempts,core.job_enrichments,core.enrichment_provider_state,core.job_parse_results,core.source_job_postings,crawl_state.jobs,ref.sources CASCADE')
        self.c.execute("INSERT INTO ref.sources VALUES (1,'test','Test')")
        self.c.execute("INSERT INTO crawl_state.jobs(id,source,listing_status) VALUES (1,'test','active')")
        self.c.execute("INSERT INTO core.source_job_postings VALUES (1,1,'https://example.test/1',1)")
        self.store = Store(self.c)
        self.assertTrue(self.store.lock())

    def add_parse(self, text, fetched='2026-09-26T01:00:00+07:00'):
        self.c.execute('UPDATE core.job_parse_results SET is_current=false WHERE source_posting_id=1')
        return self.c.execute("""INSERT INTO core.job_parse_results(source_posting_id,title,requirements_text,fetched_at)
            VALUES (1,'Engineer',%s,%s) RETURNING id""", (text, fetched)).fetchone()[0]

    def test_cutoff_same_content_and_changed_content(self):
        self.add_parse('Python required', '2026-09-25T10:00:00+07:00')
        self.store.enqueue()
        self.assertEqual(self.store.summary(), {})
        self.add_parse('Python required')
        self.store.enqueue()
        self.assertEqual(self.store.summary(), {})
        self.add_parse('SQL required')
        self.store.enqueue()
        self.store.enqueue()
        self.assertEqual(self.store.summary(), {'pending': 1})

    def test_reserve_restart_quota_and_exhaustion(self):
        self.add_parse('SQL required')
        self.store.enqueue()
        job = self.store.next_job(3)
        provider = dict(name='groq', model='test', requests_per_day=1, tokens_per_day=5000,
                        requests_per_minute=10, tokens_per_minute=5000)
        self.assertIsNotNone(self.store.reserve(job, provider, 1000))
        self.store.enqueue()
        recovered = self.store.next_job(3)
        self.assertEqual(recovered['attempts'], 1)
        self.assertIsNone(self.store.reserve(recovered, provider, 1000))
        with psycopg.connect(self.url, autocommit=True) as second:
            self.assertFalse(Store(second).lock())
        self.c.execute('UPDATE core.job_enrichments SET attempts=3')
        self.assertIsNone(self.store.next_job(3))
        self.assertEqual(self.store.summary(), {'failed': 1})

    def test_success_cached_projection_and_stale_not_exported(self):
        self.add_parse('Python required')
        self.store.enqueue()
        job = self.store.next_job(3)
        provider = dict(name='groq', model='test', requests_per_day=10, tokens_per_day=5000,
                        requests_per_minute=10, tokens_per_minute=5000)
        attempt = self.store.reserve(job, provider, 1000)
        result = {**dict.fromkeys(FIELDS), 'skills_required': ['Python'], 'evidence': {}}
        self.store.finish(job, attempt, result=result, tokens=500)
        query, columns = projection(self.c, self.c, JOBS_QUERY, JOB_COLUMNS)
        exported = dict(zip(columns, self.c.execute(query).fetchone()))
        self.assertEqual(exported['skills_required'], ['Python'])
        self.assertEqual(exported['enrichment_status'], 'succeeded')
        self.add_parse('Python required')
        self.store.enqueue()
        self.assertIsNone(self.store.next_job(3))
        self.add_parse('Java required')
        exported = dict(zip(columns, self.c.execute(query).fetchone()))
        self.assertIsNone(exported['skills_required'])
        self.assertEqual(exported['enrichment_status'], 'not_enriched')
        self.store.enqueue()
        self.c.execute("UPDATE crawl_state.jobs SET listing_status='expired'")
        self.assertIsNone(self.store.next_job(3))
        self.assertEqual(self.c.execute(query).fetchall(), [])

    def test_real_sync_before_enrichment_then_after_and_stale_clear(self):
        self.c.execute("INSERT INTO crawl_state.crawl_runs VALUES (1,'test',true,'applied')")
        self.c.execute("INSERT INTO crawl_state.cdc_sources VALUES ('test','scope',1)")
        self.c.execute("UPDATE crawl_state.jobs SET tracking_scope_hash='scope'")
        self.add_parse('Python required')
        with patch.dict(os.environ, {'LOCAL_DATABASE_URL': self.url, 'SUPABASE_DATABASE_URL': self.url}):
            self.assertEqual(sync(), 0)
            self.assertEqual(self.c.execute('SELECT enrichment_status FROM serving.jobs').fetchone()[0], 'not_enriched')
            self.store.enqueue()
            job = self.store.next_job(3)
            provider = dict(name='groq', model='test', requests_per_day=10, tokens_per_day=5000,
                            requests_per_minute=10, tokens_per_minute=5000)
            attempt = self.store.reserve(job, provider, 1000)
            result = {**dict.fromkeys(FIELDS), 'skills_required': ['Python'], 'evidence': {}}
            self.store.finish(job, attempt, result=result, tokens=500)
            self.assertEqual(sync(), 0)
            self.assertEqual(sync(verify_only=True), 0)
            self.assertEqual(self.c.execute('SELECT skills_required FROM serving.jobs').fetchone()[0], ['Python'])
            self.add_parse('Java required')
            self.assertEqual(sync(), 0)
            self.assertIsNone(self.c.execute('SELECT skills_required FROM serving.jobs').fetchone()[0])

    def backfill_preview(self, **options):
        options = normalize(dict(as_of='2026-10-02T10:00:00+07:00', lookback_days=60, **options))
        with self.c.transaction():
            self.c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
            return preview(self.c, options, load_config('configs/enrichment.yaml'))

    def add_other_job(self, posting_id, first_seen='2026-09-20T00:00:00+07:00'):
        self.c.execute("INSERT INTO crawl_state.jobs(id,source,listing_status) VALUES (%s,'test','active')", (posting_id,))
        self.c.execute("""INSERT INTO core.source_job_postings(id,source_id,canonical_url,crawler_job_id,first_seen_at)
            VALUES (%s,1,%s,%s,%s)""", (posting_id, f'https://example.test/{posting_id}', posting_id, first_seen))
        self.c.execute("""INSERT INTO core.job_parse_results(source_posting_id,title,requirements_text,fetched_at)
            VALUES (%s,'Engineer','SQL required','2026-09-20T01:00:00+07:00')""", (posting_id,))

    def backfill_store(self, selected):
        return Store(self.c, candidates=selected_candidates(selected), ordered_selection=True)

    def test_backfill_preview_limits_and_filters_without_writes(self):
        self.add_parse('Python required', '2026-09-20T01:00:00+07:00')
        self.add_other_job(2)
        self.add_other_job(3, '2026-09-25T00:00:00+07:00')
        report, selected = self.backfill_preview(max_jobs=2)
        self.assertEqual(report['counts']['ready'], 3)
        self.assertEqual(report['counts']['selected'], 2)
        self.assertEqual([r['source_posting_id'] for r in selected], [3, 2])
        self.assertEqual(self.store.summary(), {})
        self.assertEqual(self.c.execute('SELECT count(*) FROM core.enrichment_attempts').fetchone()[0], 0)
        _, selected = self.backfill_preview(sort_order='oldest_first', max_jobs=2)
        self.assertEqual([r['source_posting_id'] for r in selected], [1, 2])
        _, selected = self.backfill_preview(posting_ids=[2, 3], date_from='2026-09-20', date_to='2026-09-25')
        self.assertEqual([r['source_posting_id'] for r in selected], [2])
        report, _ = self.backfill_preview(sources=['other'])
        self.assertEqual(report['counts']['matched'], 0)
        report, selected = self.backfill_preview(date_field='posted_at')
        self.assertEqual(report['counts']['missing_date'], 3)
        self.assertEqual(selected, [])

    def test_backfill_queue_survives_regular_worker_and_shares_quota(self):
        self.add_parse('Python required', '2026-09-20T01:00:00+07:00')
        self.add_other_job(2)
        _, selected = self.backfill_preview(max_jobs=1)
        backfill = self.backfill_store(selected)
        backfill.enqueue()
        self.store.enqueue()  # Normal cutoff must not supersede the backfill queue.
        self.assertEqual(self.store.summary(), {'pending': 1})
        self.assertIsNone(self.store.next_job(3))  # Normal worker retains its original cutoff.
        job = backfill.next_job(3)
        self.assertEqual(job['source_posting_id'], 2)
        provider = dict(name='groq', model='test', requests_per_day=1, tokens_per_day=5000,
                        requests_per_minute=10, tokens_per_minute=5000)
        attempt = backfill.reserve(job, provider, 1000)
        backfill.finish(job, attempt, error='test_retry')
        self.c.execute("UPDATE core.job_enrichments SET next_attempt_at=now()-interval '1 minute'")
        # Enqueue a new post-cutoff content version in the ordinary worker.
        self.add_parse('Java required')
        self.store.enqueue()
        new_job = self.store.next_job(3)
        self.assertEqual(new_job['source_posting_id'], 1)
        self.assertIsNone(self.store.reserve(new_job, provider, 1000))
        self.assertEqual(backfill.next_job(3)['attempts'], 1)

    def test_backfill_rechecks_changed_content_and_expired_jobs(self):
        self.add_parse('Python required', '2026-09-20T01:00:00+07:00')
        _, selected = self.backfill_preview()
        backfill = self.backfill_store(selected)
        backfill.enqueue()
        job = backfill.next_job(3)
        provider = dict(name='groq', model='test', requests_per_day=10, tokens_per_day=5000,
                        requests_per_minute=10, tokens_per_minute=5000)
        self.c.execute("UPDATE crawl_state.jobs SET listing_status='expired'")
        self.assertIsNone(backfill.reserve(job, provider, 1000))
        self.assertIsNone(backfill.next_job(3))
        self.c.execute("UPDATE crawl_state.jobs SET listing_status='active'")
        self.add_parse('Java required')
        self.assertIsNone(backfill.reserve(job, provider, 1000))
        self.store.enqueue()
        self.assertEqual(self.c.execute('SELECT status FROM core.job_enrichments WHERE id=%s',
                                       (job['id'],)).fetchone()[0], 'superseded')

    def test_backfill_classifies_success_failure_cooldown_and_processing(self):
        self.add_parse('Python required', '2026-09-20T01:00:00+07:00')
        for posting_id in range(2, 7):
            self.add_other_job(posting_id)
        _, selected = self.backfill_preview()
        backfill = self.backfill_store(selected)
        backfill.enqueue()
        self.c.execute("UPDATE core.job_enrichments SET status='succeeded',result='{}' WHERE source_posting_id=1")
        self.c.execute("UPDATE core.job_enrichments SET status='failed',attempts=1 WHERE source_posting_id=2")
        self.c.execute("UPDATE core.job_enrichments SET status='retry_wait',attempts=3 WHERE source_posting_id=3")
        self.c.execute("""UPDATE core.job_enrichments SET status='retry_wait',attempts=1,
            next_attempt_at=now()+interval '1 hour' WHERE source_posting_id=4""")
        self.c.execute("UPDATE core.job_enrichments SET status='processing',attempts=1 WHERE source_posting_id=5")
        self.c.execute("UPDATE core.job_enrichments SET next_attempt_at=now()-interval '1 minute' WHERE source_posting_id=6")
        report, selected = self.backfill_preview()
        self.assertEqual(report['counts']['succeeded'], 1)
        self.assertEqual(report['counts']['failed_or_exhausted'], 2)
        self.assertEqual(report['counts']['retry_later'], 1)
        self.assertEqual(report['counts']['processing'], 1)
        self.assertEqual([r['source_posting_id'] for r in selected], [6])

    def test_backfill_api_limit_resume_and_success_reuse(self):
        self.add_parse('Python required', '2026-09-20T01:00:00+07:00')
        self.add_other_job(2)
        self.add_other_job(3, '2026-09-25T00:00:00+07:00')
        _, selected = self.backfill_preview(max_jobs=2)
        backfill = self.backfill_store(selected)
        backfill.enqueue()
        config = load_config('configs/enrichment.yaml')
        config['max_jobs_per_run'] = 1
        result = {**dict.fromkeys(FIELDS), 'evidence': {field: [] for field in FIELDS}}
        calls = []
        def fake_extract(provider, payload, **kwargs):
            calls.append(payload)
            return Result(result, 100)
        with patch.dict(os.environ, {'GEMINI_API_KEY': 'test'}):
            self.assertEqual(process(backfill, config, call=fake_extract), 0)
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.c.execute("SELECT source_posting_id FROM core.job_enrichments WHERE status='succeeded'").fetchall(), [(3,)])
        report, selected = self.backfill_preview()
        self.assertEqual(report['counts']['succeeded'], 1)
        self.assertEqual([r['source_posting_id'] for r in selected], [2, 1])

    def test_backfill_dry_run_entrypoint_does_not_recover_or_call_api(self):
        self.add_parse('Python required', '2026-09-20T01:00:00+07:00')
        with patch.dict(os.environ, {'LOCAL_DATABASE_URL': self.url}), patch(
                'joblake.enrichment.backfill.process') as worker, patch.object(Store, 'recover') as recover:
            self.assertEqual(backfill_run(options=dict(as_of='2026-10-02', lookback_days=60)), 0)
        worker.assert_not_called()
        recover.assert_not_called()
        self.assertEqual(self.store.summary(), {})

    def test_backfill_execution_entrypoint_shares_lock_and_respects_selection(self):
        self.add_parse('Python required', '2026-09-20T01:00:00+07:00')
        self.add_other_job(2)
        options = dict(dry_run=False, as_of='2026-10-02', lookback_days=60, max_jobs=1, max_api_attempts=1)
        result = {**dict.fromkeys(FIELDS), 'evidence': {field: [] for field in FIELDS}}
        calls = []
        def fake_extract(provider, payload, **kwargs):
            calls.append(payload)
            return Result(result, 100)
        def fake_process(store, config):
            return process(store, config, call=fake_extract)
        with patch.dict(os.environ, {'LOCAL_DATABASE_URL': self.url, 'GEMINI_API_KEY': 'test'}), patch(
                'joblake.enrichment.backfill.process', side_effect=fake_process):
            # This test's regular worker still owns the session lock.
            self.assertEqual(backfill_run(options=options), 1)
            self.assertEqual(calls, [])
            self.assertEqual(self.store.summary(), {})
            self.c.execute('SELECT pg_advisory_unlock(741205, 2)')
            self.assertEqual(backfill_run(options=options), 0)
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.c.execute('SELECT source_posting_id,status,attempts FROM core.job_enrichments').fetchall(),
                         [(2, 'succeeded', 1)])

    def test_batch_one_request_three_attempts_partial_commit_and_retry(self):
        self.add_parse('Python required')
        self.add_other_job(2)
        self.add_other_job(3)
        _, selected = self.backfill_preview()
        store = self.backfill_store(selected)
        store.enqueue()
        job = store.next_job(3)
        group = [job, *store.batch_followers(job, 3)]
        provider = dict(name='gemini', model='test', requests_per_day=1, tokens_per_day=20000,
                        requests_per_minute=10, tokens_per_minute=20000)
        request = store.reserve_batch(group, provider, 9000, input_bytes=12000)
        self.assertEqual(self.c.execute('SELECT count(*) FROM core.enrichment_attempts').fetchone()[0], 1)
        self.assertEqual(self.c.execute('SELECT count(*) FROM core.enrichment_attempt_jobs').fetchone()[0], 3)
        self.assertEqual(self.c.execute('SELECT sum(attempts) FROM core.job_enrichments').fetchone()[0], 3)
        result = {**dict.fromkeys(FIELDS), 'evidence': {field: [] for field in FIELDS}}
        outcomes = {j['id']: (result, None) for j in group}
        outcomes[group[1]['id']] = (None, 'unsupported_evidence')
        store.finish_batch(group, request, outcomes, tokens=3000, input_tokens=2000, output_tokens=1000)
        self.assertEqual(self.c.execute('SELECT status,actual_tokens FROM core.enrichment_attempts').fetchone(), ('partial', 3000))
        self.assertEqual(store.summary(), {'succeeded': 2, 'retry_wait': 1})
        self.c.execute("UPDATE core.job_enrichments SET next_attempt_at=now()-interval '1 minute'")
        retry = store.next_job(3)
        self.assertEqual(retry['id'], group[1]['id'])
        self.assertEqual(retry['attempts'], 1)
        self.assertEqual(store.batch_followers(retry, 3), [])
        self.assertIsNone(store.reserve(retry, provider, 2000))  # One shared daily request already consumed.

    def test_batch_crash_recovery_keeps_one_reservation_and_all_attempts(self):
        self.add_parse('Python required')
        self.add_other_job(2)
        _, selected = self.backfill_preview()
        store = self.backfill_store(selected)
        store.enqueue()
        head = store.next_job(3)
        group = [head, *store.batch_followers(head, 3)]
        provider = dict(name='gemini', model='test', requests_per_day=10, tokens_per_day=20000,
                        requests_per_minute=10, tokens_per_minute=20000)
        store.reserve_batch(group, provider, 6000)
        store.recover()
        self.assertEqual(store.summary(), {'retry_wait': 2})
        self.assertEqual(self.c.execute('SELECT status,reserved_tokens,actual_tokens FROM core.enrichment_attempts').fetchone(),
                         ('interrupted', 6000, None))
        self.assertEqual(self.c.execute("SELECT count(*) FROM core.enrichment_attempt_jobs WHERE status='interrupted'").fetchone()[0], 2)
        self.assertEqual(self.c.execute('SELECT sum(attempts) FROM core.job_enrichments').fetchone()[0], 2)

    def test_batch_stale_member_reserves_nothing_and_benchmark_does_not_touch_jobs(self):
        self.add_parse('Python required')
        self.add_other_job(2)
        _, selected = self.backfill_preview()
        store = self.backfill_store(selected)
        store.enqueue()
        head = store.next_job(3)
        group = [head, *store.batch_followers(head, 3)]
        self.c.execute("UPDATE crawl_state.jobs SET listing_status='expired' WHERE id=1")
        provider = dict(name='gemini', model='test', requests_per_day=10, tokens_per_day=20000,
                        requests_per_minute=10, tokens_per_minute=20000)
        self.assertIsNone(store.reserve_batch(group, provider, 6000))
        self.assertEqual(self.c.execute('SELECT count(*) FROM core.enrichment_attempts').fetchone()[0], 0)
        request = store.reserve_batch(group, provider, 6000, purpose='benchmark')
        store.finish_batch(group, request, {j['id']: ({}, None) for j in group}, tokens=1234, purpose='benchmark')
        self.assertEqual(store.summary(), {'pending': 2})
        self.assertEqual(self.c.execute('SELECT sum(attempts) FROM core.job_enrichments').fetchone()[0], 0)
        self.assertEqual(self.c.execute('SELECT count(*) FROM core.enrichment_attempt_jobs').fetchone()[0], 0)
        self.assertEqual(self.c.execute('SELECT purpose,actual_tokens FROM core.enrichment_attempts').fetchone(), ('benchmark', 1234))

    def test_calibration_requires_measured_inputs_same_model_and_shape(self):
        provider = dict(name='gemini', model='test')
        self.assertEqual(self.store.input_token_ratio(provider), 0.5)
        for _ in range(20):
            self.c.execute("""INSERT INTO core.enrichment_attempts(provider,model,reserved_tokens,
                actual_tokens,input_bytes,input_tokens) VALUES ('gemini','test',4000,2000,10000,1500)""")
        self.assertEqual(self.store.input_token_ratio(provider), 0.25)
        self.assertEqual(self.store.input_token_ratio(provider, batch=True), 0.5)
        self.assertEqual(self.store.input_token_ratio(dict(provider, model='other')), 0.5)

    def test_batch_worker_end_to_end_one_call_updates_three_jobs(self):
        self.add_parse('Python required')
        self.add_other_job(2)
        self.add_other_job(3)
        _, selected = self.backfill_preview()
        store = self.backfill_store(selected)
        store.enqueue()
        self.c.execute("UPDATE core.job_enrichments SET next_attempt_at=now()-interval '1 minute'")
        config = load_config('configs/enrichment.yaml')
        config['providers'][0]['batch_size'] = 3
        config['max_jobs_per_run'] = 1
        calls = []
        result = {**dict.fromkeys(FIELDS), 'evidence': {field: [] for field in FIELDS}}
        def fake_batch(provider, group, **kwargs):
            calls.append((group, kwargs))
            return Result({'jobs': [{'job_id': str(j['id']), 'result': result} for j in group]}, 3000, 2000, 1000)
        with patch.dict(os.environ, {'GEMINI_API_KEY': 'test'}):
            self.assertEqual(process(store, config, batch_call=fake_batch), 0)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1]['max_output'], 6144)
        self.assertEqual(store.summary(), {'succeeded': 3})
        self.assertEqual(self.c.execute('SELECT item_count,actual_tokens,input_tokens,output_tokens FROM core.enrichment_attempts').fetchall(),
                         [(3, 3000, 2000, 1000)])
        self.assertEqual(self.c.execute("SELECT count(*) FROM core.current_job_enrichments WHERE status='succeeded'").fetchone()[0], 3)

    def test_batch_preview_reports_request_savings_without_writes(self):
        self.add_parse('Python required')
        self.add_other_job(2)
        self.add_other_job(3)
        config = load_config('configs/enrichment.yaml')
        config['providers'][0]['batch_size'] = 3
        options = normalize(dict(as_of='2026-10-02', lookback_days=60))
        with self.c.transaction():
            self.c.execute('SET TRANSACTION READ ONLY')
            report, _ = preview(self.c, options, config)
        gemini, groq = report['providers'][:2]
        self.assertEqual(gemini['planned_requests'], 1)
        self.assertEqual(groq['planned_requests'], 3)
        self.assertLess(gemini['selected_estimated_tokens'], gemini['single_job_estimated_tokens'])
        self.assertEqual(self.store.summary(), {})


if __name__ == '__main__':
    unittest.main()
