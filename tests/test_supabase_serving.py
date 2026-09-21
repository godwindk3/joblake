"""Real SQL tests in a uniquely named disposable LOCAL database, never Supabase.

Opt in with JOBLAKE_TEST_SERVING=1. Requires local CREATEDB permission.
"""
import os
import unittest
import uuid
from importlib.resources import files
from unittest.mock import patch

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from dotenv import load_dotenv

from joblake.supabase_sync import SERVING_DDL, configure, sync

LOCAL_DDL = """
CREATE SCHEMA ref;
CREATE SCHEMA core;
CREATE SCHEMA crawl_state;
CREATE TABLE ref.sources (id bigint PRIMARY KEY, code text UNIQUE, display_name text);
CREATE TABLE crawl_state.crawl_runs (
    id bigint PRIMARY KEY, source text, coverage_complete boolean, cdc_status text);
CREATE TABLE crawl_state.cdc_sources (source text PRIMARY KEY, scope_hash text, last_applied_run_id bigint);
CREATE TABLE crawl_state.jobs (
    id bigint PRIMARY KEY, source text, listing_status text, tracking_scope_hash text,
    last_seen_at timestamptz DEFAULT '2026-09-20T00:00:00Z');
CREATE TABLE core.source_job_postings (
    id bigint PRIMARY KEY, source_id bigint, canonical_url text, crawler_job_id bigint);
CREATE TABLE core.job_parse_results (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_posting_id bigint, is_current boolean DEFAULT true, quality_status text DEFAULT 'partial',
    title text, employer_name_raw text, description_text text, requirements_text text,
    benefits_text text, benefit_items text[] DEFAULT '{}', categories_raw text[] DEFAULT '{}',
    skills_raw text[] DEFAULT '{}', location_cities text[] DEFAULT '{}', salary_raw text,
    employment_type_raw text, experience_raw text, posted_at timestamptz, expires_at timestamptz);
"""


@unittest.skipUnless(os.getenv('JOBLAKE_TEST_SERVING') == '1', 'Local SQL integration opt-in required')
class ServingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        load_dotenv()
        configure()
        cls.admin_url = os.environ['LOCAL_DATABASE_URL']
        cls.database = 'joblake_serving_test_' + uuid.uuid4().hex[:12]
        with psycopg.connect(cls.admin_url, autocommit=True) as c:
            c.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(cls.database)))
        cls.url = make_conninfo(cls.admin_url, dbname=cls.database)
        with psycopg.connect(cls.url) as c:
            c.execute(LOCAL_DDL)
            c.execute(SERVING_DDL)
            c.execute(files('joblake').joinpath('sql/serving_search_v1.sql').read_text(encoding='utf-8'))

    @classmethod
    def tearDownClass(cls):
        with psycopg.connect(cls.admin_url, autocommit=True) as c:
            c.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(cls.database)))

    def execute(self, query, params=None):
        with psycopg.connect(self.url) as c:
            cur = c.execute(query, params)
            return cur.fetchall() if cur.description else []

    def setUp(self):
        self.execute('''TRUNCATE serving.jobs,serving.sources,ref.sources,
            core.source_job_postings,core.job_parse_results,crawl_state.jobs,
            crawl_state.crawl_runs,crawl_state.cdc_sources RESTART IDENTITY''')
        self.execute("""
            INSERT INTO ref.sources VALUES (1,'example','Example'),(2,'other','Other');
            INSERT INTO crawl_state.crawl_runs VALUES (1,'example',true,'applied'),(2,'other',true,'baseline');
            INSERT INTO crawl_state.cdc_sources VALUES ('example','scope',1),('other','scope',2);
        """)
        self.add_job(1)
        self.add_job(2, 'expired')
        self.add_job(3, 'unknown')
        self.add_job(4, content=False)
        self.add_job(5, source=2)
        self.env = patch.dict(os.environ, {'LOCAL_DATABASE_URL': self.url, 'SUPABASE_DATABASE_URL': self.url})
        self.env.start()
        self.addCleanup(self.env.stop)

    def add_job(self, job_id, status='active', content=True, source=1):
        code = 'example' if source == 1 else 'other'
        self.execute('INSERT INTO crawl_state.jobs(id,source,listing_status,tracking_scope_hash) VALUES (%s,%s,%s,%s)',
                     (job_id, code, status, 'scope'))
        self.execute('INSERT INTO core.source_job_postings VALUES (%s,%s,%s,%s)',
                     (job_id, source, f'https://{code}.test/jobs/{job_id}', job_id))
        if content:
            self.execute('''INSERT INTO core.job_parse_results(source_posting_id,title,description_text,benefit_items)
                VALUES (%s,%s,%s,%s)''', (job_id, 'Kỹ sư phần mềm', 'Nội dung tiếng Việt', ['Bảo hiểm','Thưởng']))

    def ids(self):
        return self.execute('SELECT id FROM serving.jobs ORDER BY id')

    def test_active_only_unicode_and_benefit_fallback(self):
        self.assertEqual(sync(), 0)
        self.assertEqual(self.ids(), [(1,), (5,)])
        self.assertEqual(self.execute('SELECT title,benefits_text FROM serving.jobs WHERE id=1'),
                         [('Kỹ sư phần mềm', 'Bảo hiểm\nThưởng')])
        self.assertEqual(sync(verify_only=True), 0)

    def test_search_accents_filters_and_no_body_search(self):
        self.assertEqual(sync(), 0)
        self.execute("UPDATE serving.jobs SET location_cities=ARRAY['Hà Nội'] WHERE id=1")
        self.assertEqual(self.execute("SELECT id FROM serving.search_jobs('ky su','example','Hà Nội')"), [(1,)])
        self.assertEqual(self.execute("SELECT id FROM serving.search_jobs('kỹ sư','example','Hà Nội')"), [(1,)])
        self.assertEqual(self.execute("SELECT id FROM serving.search_jobs('Nội dung')"), [])
        self.assertEqual(self.execute("SELECT id FROM serving.search_jobs('ky su','other','Hà Nội')"), [])

    def test_search_technology_names_are_distinct(self):
        self.assertEqual(sync(), 0)
        for query, alias in [('C++','cplusplus'), ('C#','csharp'), ('.NET','dotnet'), ('Node.js','nodejs')]:
            with self.subTest(query=query):
                self.execute('UPDATE serving.jobs SET title=%s WHERE id=1', (query+' Developer',))
                self.execute("UPDATE serving.jobs SET title='C Developer' WHERE id=5")
                self.assertEqual(self.execute('SELECT id FROM serving.search_jobs(%s)', (query,)), [(1,)])
                self.assertEqual(self.execute('SELECT id FROM serving.search_jobs(%s)', (alias,)), [(1,)])

    def test_search_rank_trigger_and_pagination(self):
        self.assertEqual(sync(), 0)
        self.execute("UPDATE serving.jobs SET title='Python Developer' WHERE id=1")
        self.execute("UPDATE serving.jobs SET employer_name_raw='Python', title='Other role' WHERE id=5")
        self.assertEqual(self.execute("SELECT id FROM serving.search_jobs('Python')"), [(1,), (5,)])
        self.assertEqual(self.execute("SELECT id FROM serving.search_jobs('Python',NULL,NULL,1,1)"), [(5,)])
        self.execute("UPDATE serving.jobs SET title='Java Developer' WHERE id=1")
        self.assertEqual(self.execute("SELECT id FROM serving.search_jobs('Python')"), [(5,)])
        self.assertEqual(self.execute("SELECT id FROM serving.search_jobs('Java')"), [(1,)])

    def test_search_blank_punctuation_and_bounds(self):
        self.assertEqual(sync(), 0)
        self.assertEqual(len(self.execute("SELECT id FROM serving.search_jobs('')")), 2)
        self.assertEqual(self.execute("SELECT id FROM serving.search_jobs('!!!')"), [])
        for params in [('x',0,0), ('x',101,0), ('x',20,-1), ('x'*201,20,0)]:
            with self.assertRaises(psycopg.errors.InvalidParameterValue):
                self.execute('SELECT * FROM serving.search_jobs(%s,NULL,NULL,%s,%s)', params)

    def test_staging_does_not_copy_search_column_or_indexes(self):
        from joblake.supabase_sync import stage_snapshot
        with psycopg.connect(self.url) as local, psycopg.connect(self.url) as remote:
            stage_snapshot(local, remote)
            columns = remote.execute("SELECT attname FROM pg_attribute WHERE attrelid='pg_temp.sync_jobs'::regclass AND attnum>0").fetchall()
            self.assertNotIn(('search_vector',), columns)
            self.assertEqual(remote.execute("SELECT count(*) FROM pg_index WHERE indrelid='pg_temp.sync_jobs'::regclass").fetchone()[0], 1)

    def test_expiry_unknown_and_reappearance_without_new_parse(self):
        self.assertEqual(sync(), 0)
        self.execute("UPDATE crawl_state.jobs SET listing_status='expired' WHERE id=1")
        self.assertEqual(sync(), 0)
        self.assertEqual(self.ids(), [(5,)])
        self.execute("UPDATE crawl_state.jobs SET listing_status='active' WHERE id=1")
        self.assertEqual(sync(), 0)
        self.execute("UPDATE crawl_state.jobs SET listing_status='unknown' WHERE id=1")
        self.assertEqual(sync(), 0)
        self.assertEqual(self.ids(), [(5,)])

    def test_parse_failure_retains_old_active_content(self):
        self.assertEqual(sync(), 0)
        self.execute("UPDATE core.job_parse_results SET quality_status='rejected',title='broken' WHERE source_posting_id=1")
        self.execute("UPDATE crawl_state.jobs SET last_seen_at=last_seen_at+interval '1 day' WHERE id=1")
        self.assertEqual(sync(), 0)
        self.assertEqual(self.execute('SELECT title FROM serving.jobs WHERE id=1'), [('Kỹ sư phần mềm',)])
        self.assertEqual(sync(verify_only=True), 0)

    def test_idempotent_sync_does_not_rewrite_unchanged_rows(self):
        self.assertEqual(sync(), 0)
        before = self.execute('SELECT id,xmin::text,updated_at FROM serving.jobs ORDER BY id')
        self.assertEqual(sync(), 0)
        self.assertEqual(before, self.execute('SELECT id,xmin::text,updated_at FROM serving.jobs ORDER BY id'))

    def test_dry_run_does_not_insert_or_delete(self):
        self.assertEqual(sync(dry_run=True), 0)
        self.assertEqual(self.ids(), [])
        self.assertEqual(sync(), 0)
        self.execute("UPDATE crawl_state.jobs SET listing_status='expired' WHERE id=1")
        self.assertEqual(sync(dry_run=True), 0)
        self.assertEqual(self.ids(), [(1,), (5,)])

    def test_missing_mapping_aborts_without_deleting(self):
        self.assertEqual(sync(), 0)
        self.execute('DELETE FROM crawl_state.jobs WHERE id=1')
        self.assertEqual(sync(), 1)
        self.assertEqual(self.ids(), [(1,), (5,)])

    def test_invalid_active_baseline_aborts(self):
        self.execute("UPDATE crawl_state.crawl_runs SET coverage_complete=false WHERE id=1")
        self.assertEqual(sync(), 1)
        self.assertEqual(self.ids(), [])

    def test_all_expired_removes_all_jobs_but_not_sources(self):
        self.assertEqual(sync(), 0)
        self.execute("UPDATE crawl_state.jobs SET listing_status='expired'")
        self.assertEqual(sync(), 0)
        self.assertEqual(self.ids(), [])
        self.assertEqual(self.execute('SELECT count(*) FROM serving.sources'), [(2,)])

    def test_identity_collision_rolls_back(self):
        self.assertEqual(sync(), 0)
        self.execute("UPDATE serving.jobs SET canonical_url='https://wrong.test' WHERE id=1")
        self.assertEqual(sync(), 1)
        self.assertEqual(self.ids(), [(1,), (5,)])

    def test_empty_source_catalog_does_not_erase_destination(self):
        self.assertEqual(sync(), 0)
        self.execute('DELETE FROM core.source_job_postings; DELETE FROM ref.sources')
        self.assertEqual(sync(), 1)
        self.assertEqual(self.ids(), [(1,), (5,)])

    def test_source_identity_collision_does_not_change_destination(self):
        self.assertEqual(sync(), 0)
        self.execute("UPDATE serving.sources SET code='wrong-source' WHERE id=1")
        self.assertEqual(sync(), 1)
        self.assertEqual(self.ids(), [(1,), (5,)])

    def test_content_update_and_remote_orphan_reconciliation(self):
        self.assertEqual(sync(), 0)
        self.execute("UPDATE core.job_parse_results SET title='New title' WHERE source_posting_id=1")
        self.execute('DELETE FROM core.source_job_postings WHERE id=5')
        self.assertEqual(sync(), 0)
        self.assertEqual(self.ids(), [(1,)])
        self.assertEqual(self.execute('SELECT title FROM serving.jobs'), [('New title',)])

    def test_verification_failure_rolls_back_upsert_and_delete(self):
        self.assertEqual(sync(), 0)
        self.execute("UPDATE crawl_state.jobs SET listing_status='expired' WHERE id=1")
        self.execute("UPDATE core.job_parse_results SET title='changed' WHERE source_posting_id=5")
        with patch('joblake.supabase_sync.verify_staged', side_effect=ValueError('injected verification failure')):
            self.assertEqual(sync(), 1)
        self.assertEqual(self.ids(), [(1,), (5,)])
        self.assertEqual(self.execute('SELECT title FROM serving.jobs WHERE id=5'), [('Kỹ sư phần mềm',)])

    def test_concurrent_sync_lock_rejects_second_writer(self):
        with psycopg.connect(self.url) as c:
            c.execute('SELECT pg_advisory_xact_lock(741205,1)')
            self.assertEqual(sync(), 1)
        self.assertEqual(sync(), 0)

    def test_verifier_detects_content_drift_without_repair(self):
        self.assertEqual(sync(), 0)
        self.execute("UPDATE serving.jobs SET title='drift' WHERE id=1")
        self.assertEqual(sync(verify_only=True), 1)
        self.assertEqual(self.execute('SELECT title FROM serving.jobs WHERE id=1'), [('drift',)])


if __name__ == '__main__':
    unittest.main()
