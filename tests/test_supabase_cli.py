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

    def test_cli_routes_sync_without_ingestion(self):
        with patch('sys.argv', ['joblake', '--phase', 'supabase-sync', '--dry-run']), patch.object(cli, 'load_dotenv'), patch('joblake.supabase_sync.configure'), patch('joblake.supabase_sync.sync', return_value=0) as command:
            with self.assertRaises(SystemExit) as outcome:
                cli.main()
        self.assertEqual(outcome.exception.code, 0)
        command.assert_called_once_with(dry_run=True)

    def test_sync_collision_aborts_transaction(self):
        local, remote = MagicMock(), MagicMock()
        local.__enter__.return_value = local
        remote.__enter__.return_value = remote
        reader = local.cursor.return_value.__enter__.return_value
        reader.fetchmany.return_value = [(1, 'topdev')]
        reader.description = [MagicMock(), MagicMock()]
        reader.description[0].name = 'id'
        reader.description[1].name = 'code'
        remote.execute.return_value.fetchone.return_value = ('other-source',)
        with patch.dict(os.environ, {'LOCAL_DATABASE_URL': 'dbname=local', 'SUPABASE_DATABASE_URL': 'dbname=remote'}), patch('joblake.supabase_sync.psycopg.connect', side_effect=[local, remote]):
            self.assertEqual(sync(), 1)
        self.assertIs(remote.__exit__.call_args.args[0], ValueError)


if __name__ == '__main__':
    unittest.main()
