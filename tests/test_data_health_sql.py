"""Full migration and health SQL checks in a uniquely named disposable database."""
import os
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from alembic import command
from alembic.config import Config
from dotenv import load_dotenv

from joblake.data_health import collect_report
from joblake.postgres import PostgresSettings


@unittest.skipUnless(os.getenv('JOBLAKE_TEST_POSTGRES') == '1', 'PostgreSQL integration opt-in required')
class DataHealthSQLTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1]
        load_dotenv(root / '.env', override=False)
        cls.admin = PostgresSettings.from_config()
        cls.settings = replace(cls.admin, database='joblake_health_test_' + uuid4().hex[:12])
        with psycopg.connect(**cls.admin.connection_kwargs(), autocommit=True) as connection:
            connection.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(cls.settings.database)))
        cls.addClassCleanup(cls.drop_database)
        with patch.object(PostgresSettings, 'from_config', return_value=cls.settings):
            command.upgrade(Config(str(root / 'alembic.ini')), 'head')

    @classmethod
    def drop_database(cls):
        with psycopg.connect(**cls.admin.connection_kwargs(), autocommit=True) as connection:
            connection.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(
                sql.Identifier(cls.settings.database)))

    def test_full_migration_and_recovered_parse_counted_once(self):
        with psycopg.connect(**self.settings.connection_kwargs(), row_factory=dict_row) as connection:
            connection.execute("""
                INSERT INTO crawl_state.jobs(id,source,url,first_seen_at,last_seen_at)
                SELECT n,'example','https://example.test/' || n,now(),now()
                FROM generate_series(1,3) n;
                INSERT INTO crawl_state.raw_objects(
                  id,job_id,storage_provider,bucket_name,object_key,requested_url,
                  http_status,content_length_bytes,content_sha256,fetched_at,stored_at,
                  validation_version,validation_report)
                SELECT id,id,'minio','test',id::text,url,200,10,'hash',now(),now(),'v1','{}'
                FROM crawl_state.jobs;
                INSERT INTO crawl_state.parse_attempts(
                  job_id,raw_object_id,parser_name,parser_version,attempt_number,status,started_at)
                VALUES
                  (1,1,'test','v1',1,'validation_error',now()-interval '2 hours'),
                  (1,1,'test','v1',2,'success',now()-interval '1 hour'),
                  (2,2,'test','v1',1,'parse_error',now()-interval '2 hours'),
                  (2,2,'test','v1',2,'raw_missing',now()-interval '1 hour'),
                  (3,3,'test','v1',1,'validation_error',now()-interval '2 days'),
                  (3,3,'test','v1',2,'parsing',now());
            """)
        with psycopg.connect(**self.settings.connection_kwargs(), row_factory=dict_row) as connection:
            report = collect_report(connection, ['example', 'empty'])
        self.assertEqual(report['sources_without_jobs'], ['empty'])
        self.assertEqual(report['sections']['parse_outcomes_in_window'], [
            {'source': 'example', 'status': 'raw_missing', 'jobs': 1},
            {'source': 'example', 'status': 'success', 'jobs': 1},
        ])
