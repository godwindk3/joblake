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
        self.c.execute('UPDATE core.job_parse_results SET is_current=false')
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


if __name__ == '__main__':
    unittest.main()
