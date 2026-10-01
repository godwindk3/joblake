import unittest
from unittest.mock import MagicMock, patch

from joblake.postgres import PostgresSettings
from joblake.postgres_state import PostgresStateStore


class SourceLockWaitTests(unittest.TestCase):
    def store(self, wait=0):
        store = PostgresStateStore(PostgresSettings('localhost', 5432, 'test', 'test', 'test'),
                                   source_lock_wait_seconds=wait)
        connection = MagicMock()
        store._open_connection = MagicMock()
        store._open_connection.return_value.__enter__.return_value = connection
        return store, connection

    @patch('joblake.postgres_state.time.sleep')
    def test_waits_for_release_before_entering_phase(self, sleep):
        store, connection = self.store(60)
        connection.execute.return_value.fetchone.side_effect = [
            {'acquired': False}, {'acquired': False}, {'acquired': True}]
        with store.source_run('careerlink'):
            self.assertIs(store._run_connection, connection)
            self.assertEqual(sleep.call_count, 2)
        self.assertIsNone(store._run_connection)
        self.assertIn('pg_advisory_unlock', connection.execute.call_args.args[0])

    def test_default_still_fails_immediately_without_unlocking_other_owner(self):
        store, connection = self.store()
        connection.execute.return_value.fetchone.return_value = {'acquired': False}
        with self.assertRaisesRegex(RuntimeError, 'Another JobLake phase'):
            with store.source_run('careerlink'):
                self.fail('must not enter')
        self.assertEqual(connection.execute.call_count, 1)

    @patch('joblake.postgres_state.time.sleep')
    @patch('joblake.postgres_state.time.monotonic', side_effect=[0, 0, 60])
    def test_wait_has_deadline(self, monotonic, sleep):
        store, connection = self.store(60)
        connection.execute.return_value.fetchone.return_value = {'acquired': False}
        with self.assertRaisesRegex(RuntimeError, 'Another JobLake phase'):
            with store.source_run('careerlink'):
                self.fail('must not enter')
        self.assertIsNone(store._run_connection)
        self.assertEqual(connection.execute.call_count, 2)

    def test_rejects_unbounded_wait(self):
        for wait in [-1, 301, float('inf'), float('nan'), True, '60']:
            with self.subTest(wait=wait), self.assertRaises(ValueError):
                self.store(wait)
