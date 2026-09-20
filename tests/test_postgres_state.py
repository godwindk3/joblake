"""Real PostgreSQL integration tests; opt in with JOBLAKE_TEST_POSTGRES=1.

Each test class creates/drops its own uniquely named database, never the configured DB.
"""
import importlib.util
import os
import sqlite3
import tempfile
import unittest
import uuid
from contextlib import closing
from dataclasses import replace
from pathlib import Path

import psycopg
from psycopg import sql
from dotenv import load_dotenv
from sqlalchemy import create_engine
from alembic.migration import MigrationContext
from alembic.operations import Operations

from joblake.models import DiscoveryRecord
from joblake.postgres import PostgresSettings, PostgresRepository
from joblake.parsing.models import ParsedJob
from joblake.postgres_state import PostgresStateStore
from joblake.pipeline import IngestionPipeline
from joblake.state import SQLiteStateStore
import test_pipeline as pipeline_fixtures
import test_parse_state as parse_fixtures

ROOT = Path(__file__).resolve().parents[1]
NOW = "2026-01-03T00:00:00+00:00"


def module_at(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@unittest.skipUnless(os.environ.get("JOBLAKE_TEST_POSTGRES") == "1", "PostgreSQL integration opt-in required")
class PostgresStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        load_dotenv(ROOT / ".env", override=False)
        cls.admin = PostgresSettings.from_config({})
        cls.settings = replace(cls.admin, database="joblake_test_" + uuid.uuid4().hex[:12])
        with psycopg.connect(**cls.admin.connection_kwargs(), autocommit=True) as c:
            c.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(cls.settings.database)))
        migration = module_at("state_migration", ROOT / "migrations/versions/0002_crawl_state.py")
        with psycopg.connect(**cls.settings.connection_kwargs()) as c:
            c.execute("CREATE SCHEMA crawl_state")
            c.execute(migration.SCHEMA_SQL)
        core_migration = module_at("core_migration", ROOT / "migrations/versions/0001_parsed_jobs.py")
        engine = create_engine(cls.settings.sqlalchemy_url())
        try:
            with engine.begin() as connection, Operations.context(MigrationContext.configure(connection)):
                core_migration.upgrade()
                cdc_migration = module_at("cdc_migration", ROOT / "migrations/versions/0003_url_cdc.py")
                cdc_migration.upgrade()
                module_at("location_migration", ROOT / "migrations/versions/0004_location_cities.py").upgrade()
                module_at("cleanup_migration", ROOT / "migrations/versions/0005_raw_cleanup.py").upgrade()
        finally:
            engine.dispose()

    @classmethod
    def tearDownClass(cls):
        with psycopg.connect(**cls.admin.connection_kwargs(), autocommit=True) as c:
            c.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(cls.settings.database)))

    def setUp(self):
        self.state = PostgresStateStore(self.settings)
        with self.state._connect() as c:
            c.execute("TRUNCATE core.job_parse_results, core.source_job_postings, ref.sources RESTART IDENTITY")
            c.execute("TRUNCATE crawl_state.url_events, crawl_state.cdc_sources, crawl_state.crawl_runs, crawl_state.discovery_targets, crawl_state.jobs, crawl_state.fetch_attempts, crawl_state.raw_objects, crawl_state.parse_attempts RESTART IDENTITY")

    def record(self):
        return DiscoveryRecord("example", "https://example.com/job/one", "all", "https://example.com/jobs", 1, NOW)

    def test_discovery_and_detail_replay(self):
        config = pipeline_fixtures.IngestionPipelineTests._config("unused")
        calls = []
        storage = pipeline_fixtures.PipelineStorage()
        pipeline = IngestionPipeline(config, source=pipeline_fixtures.PipelineSource(config), state=self.state,
            storage=storage, fetcher_factory=lambda section: pipeline_fixtures.PipelineFetcher(
                "discovery" if section is config["discovery"] else "detail", calls))
        self.assertEqual(pipeline.run("full"), "completed")
        first_details = len(storage.details)
        self.assertEqual(first_details, 2)
        self.assertEqual(pipeline.run("full"), "completed")
        self.assertEqual(len(storage.details), first_details)
        with self.state._connect() as c:
            rows = c.execute("SELECT new_url_count FROM crawl_state.crawl_runs ORDER BY id").fetchall()
        self.assertEqual([r["new_url_count"] for r in rows], [2, 0])

    def test_source_lock_blocks_other_process_session(self):
        other = PostgresStateStore(self.settings)
        with self.state.source_run("example"):
            with self.assertRaises(RuntimeError):
                with other.source_run("example"):
                    self.fail("lock bypassed")
            with other.source_run("different"):
                pass
        with other.source_run("example"):
            pass

    def test_retry_and_fetch_recovery(self):
        run = self.state.start_run("example", NOW)
        self.assertEqual(self.state.upsert_discovered_jobs([self.record(), self.record()], run), 1)
        claim = self.state.claim_next_job(run_id=run, source="example", now=NOW, max_attempts=3)
        self.assertIsNotNone(claim)
        self.assertIsNone(self.state.claim_next_job(run_id=run, source="example", now=NOW, max_attempts=3))
        self.state.recover_stale_fetches("example", NOW)
        retry = self.state.claim_next_job(run_id=run, source="example", now=NOW, max_attempts=3)
        self.assertEqual(retry.attempt_number, 2)
        self.state.fail_attempt(claim=retry, attempt_status="fetch_error", completed_at=NOW,
            error_type="Test", error_message="retry later", max_attempts=3,
            next_retry_at="2026-01-04T00:00:00+00:00")
        self.assertIsNone(self.state.claim_next_job(run_id=run, source="example", now=NOW, max_attempts=3))

    def test_import_preserves_rows_ids_and_sequences(self):
        migration = module_at("import_state", ROOT / "scripts/migrate_state_to_postgres.py")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.db"
            legacy = SQLiteStateStore(str(path))
            run = legacy.start_run("example", NOW)
            legacy.upsert_discovered_jobs([self.record()], run)
            with closing(sqlite3.connect(path)) as source, psycopg.connect(**self.settings.connection_kwargs()) as target:
                report = migration.import_state(source, target)
                self.assertEqual(report["jobs"]["rows"], 1)
                migration.verify(source, target)
            next_run = self.state.start_run("example", NOW)
            self.assertGreater(next_run, run)
            with closing(sqlite3.connect(path)) as source, psycopg.connect(**self.settings.connection_kwargs()) as target:
                with self.assertRaises(RuntimeError):
                    migration.import_state(source, target)

    def test_upload_recovery_after_object_saved_before_state_commit(self):
        config = pipeline_fixtures.IngestionPipelineTests._config("unused")
        source = pipeline_fixtures.PipelineSource(config)
        run = self.state.start_run("example", NOW)
        self.state.upsert_discovered_jobs([self.record()], run)
        claim = self.state.claim_next_job(run_id=run, source="example", now=NOW, max_attempts=3)
        fetch = pipeline_fixtures.PipelineFetcher("detail", []).fetch(self.record().url)
        validation = source.validate_detail_html(fetch, self.record().url)
        storage = pipeline_fixtures.PipelineStorage()
        payload = storage.prepare_detail(discovery_record=claim.record, fetch_result=fetch)
        self.state.mark_validating(claim)
        self.state.mark_uploading(claim=claim, payload=payload, fetch_result=fetch, validation=validation)
        stored = storage.save_prepared_detail(payload)
        pending = self.state.load_pending_uploads("example")
        self.assertEqual(len(pending), 1)
        self.state.complete_recovered_upload(pending[0], stored, NOW)
        self.state.complete_recovered_upload(pending[0], stored, NOW)
        self.assertEqual(self.state.load_pending_uploads("example"), [])
        self.assertIsNone(self.state.claim_next_job(run_id=run, source="example", now=NOW, max_attempts=3))
        with self.state._connect() as c:
            self.assertEqual(c.execute("SELECT count(*) AS n FROM crawl_state.raw_objects").fetchone()["n"], 1)


@unittest.skipUnless(os.environ.get("JOBLAKE_TEST_POSTGRES") == "1", "PostgreSQL integration opt-in required")
class PostgresParseStateTests(PostgresStateTests, parse_fixtures.ParseStateTests):
    def setUp(self):
        PostgresStateTests.setUp(self)
        with self.state._connect() as c:
            job_id = c.execute("INSERT INTO crawl_state.jobs(source,url,first_seen_at,last_seen_at,raw_status) VALUES ('itviec','https://itviec.com/it-jobs/backend-1',%s,%s,'raw_ready') RETURNING id", (NOW, NOW)).fetchone()["id"]
            c.execute("""INSERT INTO crawl_state.raw_objects
                (job_id,storage_provider,bucket_name,object_key,requested_url,final_url,http_status,
                 content_type,content_length_bytes,content_sha256,fetched_at,stored_at,validation_version,validation_report)
                VALUES (%s,'minio','joblake','raw/detail/one.html','https://itviec.com/it-jobs/backend-1',
                        'https://itviec.com/it-jobs/backend-1',200,'text/html',10,%s,%s,%s,'v1','{}')""", (job_id, "a"*64, NOW, NOW))

    def tearDown(self):
        pass

    def test_parse_output_replay_after_state_commit_was_lost(self):
        run = self._start_run()
        claim = self._claim(run)
        repository = PostgresRepository(self.settings)
        def save(current):
            return repository.save_parse_result(
                source=current.source, canonical_url=current.canonical_url,
                crawler_job_id=current.job_id, first_seen_at=current.first_seen_at,
                last_seen_at=current.last_seen_at, raw_object_id=current.raw_object_id,
                raw_provider=current.locator.provider, raw_bucket=current.locator.bucket_name,
                raw_object_key=current.locator.object_key, raw_object_version=current.locator.object_version,
                raw_sha256=current.expected_sha256, fetched_at=current.fetched_at,
                parser_name="itviec", parser_version="1.0.0",
                parsed_job=ParsedJob(title="Backend Developer"), quality_status="partial",
                completeness_score=20, missing_fields=[], warnings=[])
        saved = save(claim)
        # Simulate process exit after output commit and before complete_parse.
        self.state.recover_stale_parses("itviec", "2026-01-04T00:00:00+00:00", "2026-01-04T00:00:00+00:00")
        retry = self._claim(self._start_run())
        replayed = save(retry)
        self.assertEqual(saved.parse_result_id, replayed.parse_result_id)
        self.state.complete_parse(retry, completed_at=NOW, parsed_field_count=1,
            missing_required_fields=[], warnings=[], output_location=replayed.output_location)
        self.assertIsNone(self._claim(self._start_run()))
        with self.state._connect() as c:
            self.assertEqual(c.execute("SELECT count(*) AS n FROM core.job_parse_results").fetchone()["n"], 1)

    # Keep the inherited parse behavior tests; avoid rerunning generic tests on seeded data.
    test_discovery_and_detail_replay = None
    test_source_lock_blocks_other_process_session = None
    test_retry_and_fetch_recovery = None
    test_import_preserves_rows_ids_and_sequences = None
    test_upload_recovery_after_object_saved_before_state_commit = None
