import hashlib
import os
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

from joblake.raw_cleanup import CANDIDATES, object_state, run
from joblake.postgres import PostgresRepository
from joblake.parsing.models import ParsedJob
from joblake.models import DiscoveryRecord, FetchResult, ValidationResult
from joblake.storage import StoredObject, ObjectLocator
from test_postgres_state import PostgresParseStateTests, NOW


class ObjectVerificationTests(unittest.TestCase):
    def test_same_size_replacement_is_not_deleted(self):
        client = Mock()
        client.stat_object.return_value.size = 3
        response = client.get_object.return_value
        response.stream.return_value = [b'new']
        row = dict(bucket_name='b', object_key='k', content_length_bytes=3,
                   content_sha256=hashlib.sha256(b'old').hexdigest())
        self.assertEqual(object_state(client, row), 'changed')
        response.close.assert_called_once()
        response.release_conn.assert_called_once()
        client.remove_object.assert_not_called()


@unittest.skipUnless(os.environ.get('JOBLAKE_TEST_POSTGRES') == '1', 'PostgreSQL opt-in')
class CleanupIntegrationTests(PostgresParseStateTests):
    def seed_parsed(self):
        claim = self._claim(self._start_run())
        saved = PostgresRepository(self.settings).save_parse_result(
            source=claim.source, canonical_url=claim.canonical_url,
            crawler_job_id=claim.job_id, first_seen_at=claim.first_seen_at,
            last_seen_at=claim.last_seen_at, raw_object_id=claim.raw_object_id,
            raw_provider='minio', raw_bucket='joblake', raw_object_key='raw/detail/one.html',
            raw_object_version=None, raw_sha256='a'*64, fetched_at=NOW,
            parser_name='itviec', parser_version='1.0.0',
            parsed_job=ParsedJob(title='Retained title'), quality_status='partial',
            completeness_score=20, missing_fields=[], warnings=[])
        self.state.complete_parse(claim, completed_at=NOW, parsed_field_count=1,
            missing_required_fields=[], warnings=[], output_location=saved.output_location)
        with self.state._connect() as c:
            c.execute("UPDATE crawl_state.jobs SET listing_status='expired',expired_at=NOW()-INTERVAL '10 days'")
        return claim

    def execute_cleanup(self, apply):
        client = Mock()
        client.get_bucket_versioning.return_value.status = None
        client.get_bucket_lifecycle.return_value.rules = []
        storage = SimpleNamespace(client=client, bucket_name='joblake', prefix='raw')
        with patch('joblake.raw_cleanup.MinioRawStorage.from_config', return_value=storage), patch(
                'joblake.raw_cleanup.PostgresSettings.from_config', return_value=self.settings), patch(
                'joblake.raw_cleanup.object_state', return_value='matching'):
            result = run({'storage': {}}, apply=apply)
        return result, client

    def test_dry_run_then_delete_preserves_processed_data_and_requeues(self):
        claim = self.seed_parsed()
        result, client = self.execute_cleanup(False)
        self.assertEqual(result['candidates'], 1)
        client.remove_object.assert_not_called()
        result, client = self.execute_cleanup(True)
        self.assertEqual(result['deleted'], 1)
        client.remove_object.assert_called_once()
        with self.state._connect() as c:
            self.assertEqual(c.execute('SELECT title FROM core.job_parse_results').fetchone()['title'], 'Retained title')
            self.assertIsNotNone(c.execute('SELECT purged_at FROM crawl_state.raw_objects').fetchone()['purged_at'])
        self.assertEqual(self.state.load_raw_objects_for_integrity('itviec', 100), [])
        result, client = self.execute_cleanup(True)
        self.assertEqual(result['deleted'], 0)
        run_id = self.state.start_run('itviec', NOW)
        record = DiscoveryRecord('itviec', claim.canonical_url, 'all', 'https://itviec.com', 1, NOW)
        self.state.upsert_discovered_jobs([record], run_id)
        self.assertIsNotNone(self.state.claim_next_job(run_id=run_id, source='itviec', now=NOW, max_attempts=3))

    def test_active_and_unparsed_are_protected(self):
        with self.state._connect() as c:
            c.execute("UPDATE crawl_state.jobs SET listing_status='expired',expired_at=NOW()-INTERVAL '10 days'")
        result, _ = self.execute_cleanup(False)
        self.assertEqual(result['candidates'], 0)
        self.seed_parsed()
        with self.state._connect() as c:
            c.execute("UPDATE crawl_state.jobs SET listing_status='active'")
        self.assertEqual(self.execute_cleanup(False)[0]['candidates'], 0)

    def test_busy_source_is_skipped(self):
        self.seed_parsed()
        with self.state.source_run('itviec'):
            result, client = self.execute_cleanup(True)
        self.assertEqual(result['busy_sources'], ['itviec'])
        client.remove_object.assert_not_called()

    def test_reupload_preserves_attempt_history_and_allows_same_parser(self):
        old = self.seed_parsed()
        self.execute_cleanup(True)
        now = datetime.now(timezone.utc).isoformat()
        run_id = self.state.start_run('itviec', now)
        self.state.upsert_discovered_jobs([
            DiscoveryRecord('itviec', old.canonical_url, 'all', 'https://itviec.com', 1, now)
        ], run_id)
        claim = self.state.claim_next_job(run_id=run_id, source='itviec', now=now, max_attempts=3)
        fetch = FetchResult(old.canonical_url, old.canonical_url, 200, 'text/html', now, 'new')
        stored = StoredObject(ObjectLocator('minio', 'joblake', 'raw/detail/one.html'), 3, 'b'*64, now)
        self.state.complete_upload(claim=claim, stored=stored, fetch_result=fetch,
            validation=ValidationResult(True, False, 'v1'), completed_at=now)
        parse = self.state.claim_next_raw_for_parse(run_id=run_id, source='itviec',
            parser_name='itviec', parser_version='1.0.0',
            started_at=datetime.now(timezone.utc).isoformat(), max_attempts=3)
        self.assertIsNotNone(parse)
        self.assertEqual(parse.attempt_number, 2)
        self.assertEqual(parse.expected_sha256, 'b'*64)
        with self.state._connect() as c:
            self.assertEqual(c.execute('SELECT count(*) AS n FROM core.job_parse_results').fetchone()['n'], 1)

    def test_changed_raw_and_delete_failure_keep_metadata(self):
        self.seed_parsed()
        client = Mock()
        client.get_bucket_versioning.return_value.status = None
        client.get_bucket_lifecycle.return_value.rules = []
        storage = SimpleNamespace(client=client, bucket_name='joblake', prefix='raw')
        with patch('joblake.raw_cleanup.MinioRawStorage.from_config', return_value=storage), patch(
                'joblake.raw_cleanup.PostgresSettings.from_config', return_value=self.settings):
            with patch('joblake.raw_cleanup.object_state', return_value='changed'):
                self.assertEqual(run({'storage': {}}, apply=True)['changed'], 1)
                client.remove_object.assert_not_called()
            client.remove_object.side_effect = RuntimeError('network failure')
            with patch('joblake.raw_cleanup.object_state', return_value='matching'):
                with self.assertRaises(RuntimeError):
                    run({'storage': {}}, apply=True)
            with self.state._connect() as c:
                self.assertIsNone(c.execute('SELECT purged_at FROM crawl_state.raw_objects').fetchone()['purged_at'])
            with patch('joblake.raw_cleanup.object_state', return_value='missing'):
                self.assertEqual(run({'storage': {}}, apply=True)['missing'], 1)

    def test_unknown_requires_spaced_complete_scans_in_current_scope(self):
        self.seed_parsed()
        with self.state._connect() as c:
            c.execute("UPDATE crawl_state.jobs SET listing_status='unknown'")
            first = c.execute("""INSERT INTO crawl_state.crawl_runs
                (source,status,started_at,cdc_finished_at,scope_hash,cdc_status,coverage_complete)
                VALUES ('itviec','completed',NOW()-INTERVAL '10 days',NOW()-INTERVAL '10 days',
                        'scope','baseline',true) RETURNING id""").fetchone()['id']
            c.execute("INSERT INTO crawl_state.cdc_sources VALUES ('itviec','scope',%s)", (first,))
        self.assertEqual(self.execute_cleanup(False)[0]['candidates'], 0)
        with self.state._connect() as c:
            c.execute("""INSERT INTO crawl_state.crawl_runs
                (source,status,started_at,cdc_finished_at,scope_hash,cdc_status,coverage_complete)
                VALUES ('itviec','completed',NOW(),NOW(),'scope','applied',true)""")
        self.assertEqual(self.execute_cleanup(False)[0]['candidates'], 1)
        with self.state._connect() as c:
            c.execute("UPDATE crawl_state.cdc_sources SET scope_hash='new-scope'")
        self.assertEqual(self.execute_cleanup(False)[0]['candidates'], 0)
