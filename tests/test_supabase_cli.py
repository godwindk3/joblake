import os
import unittest
from unittest.mock import MagicMock, patch

from psycopg.conninfo import conninfo_to_dict
from joblake import main as cli
from joblake.supabase_sync import configure, sync
from joblake.supabase_verify import compare_table


class SupabaseCliTests(unittest.TestCase):
    def test_local_configuration_preserves_port_and_special_password(self):
        with patch.dict(os.environ, {
            'POSTGRES_PORT': '5433', 'POSTGRES_PASSWORD': 'example@:# password',
        }, clear=True):
            configure()
            settings = conninfo_to_dict(os.environ['LOCAL_DATABASE_URL'])
            self.assertEqual(settings['port'], '5433')
            self.assertEqual(settings['password'], 'example@:# password')

    def test_verify_count_and_id_mapping(self):
        with patch('joblake.supabase_verify.row', side_effect=[(627, 388, 1014)] * 2):
            result = compare_table(None, None, 'core', 'job_parse_results')
        self.assertEqual(result.local_count, result.remote_count)
        self.assertEqual(result.remote_count, 627)
        self.assertEqual(result.remote_min_id, 388)

    def test_docker_loopback_url_uses_host_override_preserving_credentials(self):
        with patch.dict(os.environ, {
            'LOCAL_DATABASE_URL': "host=localhost port=5433 dbname=joblake user=test password='a @:#'",
            'POSTGRES_HOST': 'host.docker.internal',
        }, clear=True), patch('joblake.supabase_sync.Path.exists', return_value=True):
            configure()
            settings = conninfo_to_dict(os.environ['LOCAL_DATABASE_URL'])
            self.assertEqual(settings['host'], 'host.docker.internal')
            self.assertEqual(settings['port'], '5433')
            self.assertEqual(settings['password'], 'a @:#')

    def test_docker_does_not_rewrite_explicit_non_loopback_database(self):
        original = 'host=database.example dbname=custom'
        with patch.dict(os.environ, {'LOCAL_DATABASE_URL': original, 'POSTGRES_HOST': 'host.docker.internal'}, clear=True), patch('joblake.supabase_sync.Path.exists', return_value=True):
            configure()
            self.assertEqual(os.environ['LOCAL_DATABASE_URL'], original)

    def test_cli_routes_sync_without_ingestion(self):
        with patch('sys.argv', ['joblake', '--phase', 'supabase-sync', '--dry-run']), patch.object(cli, 'load_dotenv'), patch('joblake.supabase_sync.configure'), patch('joblake.supabase_sync.sync', return_value=0) as command:
            with self.assertRaises(SystemExit) as outcome:
                cli.main()
        self.assertEqual(outcome.exception.code, 0)
        command.assert_called_once_with(dry_run=True)

    def test_sync_lock_conflict_aborts_transaction(self):
        remote = MagicMock()
        remote.__enter__.return_value = remote
        remote.execute.return_value.fetchone.return_value = (False,)
        with patch.dict(os.environ, {'LOCAL_DATABASE_URL': 'dbname=local', 'SUPABASE_DATABASE_URL': 'dbname=remote'}), patch('joblake.supabase_sync.psycopg.connect', return_value=remote):
            self.assertEqual(sync(), 1)
        self.assertIs(remote.__exit__.call_args.args[0], ValueError)

    def test_cli_verify_routes_to_active_serving_verifier(self):
        with patch('sys.argv', ['joblake', '--phase', 'supabase-verify']), patch.object(cli, 'load_dotenv'), patch('joblake.supabase_sync.configure'), patch('joblake.supabase_sync.sync', return_value=0) as command:
            with self.assertRaises(SystemExit):
                cli.main()
        command.assert_called_once_with(verify_only=True)


if __name__ == '__main__':
    unittest.main()
