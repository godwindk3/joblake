"""Shared timeout configuration without requiring an Airflow installation."""
import importlib.util
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest


MODULE_PATH = (Path(__file__).resolve().parents[1] / 'orchestration' / 'airflow'
               / 'config' / 'joblake_dag_config.py')
spec = importlib.util.spec_from_file_location('enrichment_dag_config_test', MODULE_PATH)
config_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(config_module)


class EnrichmentTimeoutTests(unittest.TestCase):
    def test_yaml_edits_are_read_again_without_restarting_python(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'enrichment.yaml'
            for seconds in (1200, 14400, 60):
                path.write_text(f'max_run_seconds: {seconds}\n', encoding='utf-8')
                self.assertEqual(config_module.enrichment_execution_timeout(path),
                                 timedelta(seconds=seconds + 300))

    def test_invalid_budget_fails_instead_of_using_a_stale_default(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'enrichment.yaml'
            for value in ('{}', '', '[]', 'max_run_seconds: true',
                          'max_run_seconds: 0', 'max_run_seconds: -1',
                          'max_run_seconds: 1.5', 'max_run_seconds: "1200"'):
                with self.subTest(value=value):
                    path.write_text(value, encoding='utf-8')
                    with self.assertRaisesRegex(ValueError, 'max_run_seconds'):
                        config_module.enrichment_execution_timeout(path)

    def test_missing_config_is_not_silently_ignored(self):
        with TemporaryDirectory() as directory:
            with self.assertRaises(FileNotFoundError):
                config_module.enrichment_execution_timeout(Path(directory) / 'missing.yaml')


if __name__ == '__main__':
    unittest.main()
