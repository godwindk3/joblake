import copy
import os
import unittest
from unittest.mock import MagicMock, patch

from joblake.enrichment.providers import ProviderError, Result, extract, request_body
from joblake.enrichment.schema import FIELDS, validate
from joblake.enrichment.service import load_config, process
from joblake.enrichment.serving import projection
from joblake.supabase_sync import JOB_COLUMNS, JOBS_QUERY
from joblake import main as cli


def empty_result():
    return {**dict.fromkeys(FIELDS), 'evidence': {field: [] for field in FIELDS}}


class EnrichmentTests(unittest.TestCase):
    def setUp(self):
        self.config = load_config('configs/enrichment.yaml')
        self.payload = {'requirements_text': 'Required Python. At least 2 years experience.'}

    def test_null_is_valid_and_no_second_model_needed(self):
        self.assertEqual(validate(empty_result(), self.payload), empty_result())

    def test_evidence_and_range_checked(self):
        result = empty_result()
        result['experience_min_years'] = 2
        result['evidence']['experience_min_years'] = ['At least 2 years experience.']
        validate(result, self.payload)
        result['experience_max_years'] = 1
        result['evidence']['experience_max_years'] = ['At least 2 years experience.']
        with self.assertRaisesRegex(ValueError, 'reversed_experience'):
            validate(result, self.payload)
        result['experience_max_years'] = None
        result['evidence']['experience_max_years'] = []
        result['evidence']['experience_min_years'] = ['Imagined experience']
        with self.assertRaisesRegex(ValueError, 'unsupported_evidence'):
            validate(result, self.payload)

    def test_bad_types_and_unknown_fields_rejected(self):
        for value in (True, float('nan'), -1, '2'):
            result = empty_result()
            result['experience_min_years'] = value
            result['evidence']['experience_min_years'] = ['At least 2 years experience.']
            with self.assertRaises(ValueError):
                validate(result, self.payload)
        result = empty_result()
        result['unexpected'] = True
        with self.assertRaises(ValueError):
            validate(result, self.payload)

    def test_request_contract_and_free_routing(self):
        for provider in self.config['providers']:
            body = request_body(provider, self.payload, 2048)
            if provider['name'] == 'gemini':
                self.assertIn('responseJsonSchema', body['generationConfig'])
            elif provider['name'] == 'groq':
                self.assertTrue(body['response_format']['json_schema']['strict'])
            else:
                self.assertEqual(body['response_format']['type'], provider.get('output_format', 'json_object'))
                self.assertTrue(body['provider']['require_parameters'])
            self.assertNotIn('tools', body)
        provider = copy.deepcopy(self.config['providers'][2])
        provider['model'] = 'paid-model'
        with self.assertRaises(ValueError):
            request_body(provider, self.payload, 2048)

    def test_provider_http_errors_never_expose_body_or_secret(self):
        provider = self.config['providers'][1]
        response = MagicMock(status_code=401, headers={}, text='secret-token')
        with patch.dict(os.environ, {provider['key_env']: 'secret-token'}), patch('requests.post', return_value=response):
            with self.assertRaises(ProviderError) as caught:
                extract(provider, self.payload)
        self.assertEqual(str(caught.exception), 'http_401')

    def test_truncated_response_rejected(self):
        provider = self.config['providers'][1]
        response = MagicMock(status_code=200)
        response.json.return_value = {'choices': [{'finish_reason': 'length', 'message': {'content': '{}'}}]}
        with patch.dict(os.environ, {provider['key_env']: 'test'}), patch('requests.post', return_value=response):
            with self.assertRaisesRegex(ProviderError, 'incomplete_output'):
                extract(provider, self.payload)

    def test_openrouter_embedded_error_uses_provider_cooldown(self):
        provider = self.config['providers'][2]
        response = MagicMock(status_code=200)
        response.json.return_value = {'error': {'code': 503, 'message': 'Private upstream message'}}
        with patch.dict(os.environ, {provider['key_env']: 'test'}), patch('requests.post', return_value=response):
            with self.assertRaises(ProviderError) as caught:
                extract(provider, self.payload)
        self.assertEqual(str(caught.exception), 'http_503')
        self.assertEqual(caught.exception.cooldown, 120)

    def test_openrouter_strict_schema_can_be_selected(self):
        provider = {**self.config['providers'][2], 'output_format': 'json_schema'}
        body = request_body(provider, self.payload, 2048)
        self.assertEqual(body['response_format']['type'], 'json_schema')
        self.assertTrue(body['response_format']['json_schema']['strict'])
        self.assertEqual(body['reasoning'], {'enabled': False})

    def test_provider_output_budget_is_reserved_and_used(self):
        self.config["providers"][2]["enabled"] = True
        store = MagicMock()
        job = {'id': 1, 'source_posting_id': 2, 'attempts': 0, 'input_payload': self.payload}
        store.next_job.side_effect = [job, None]
        store.reserve.side_effect = [None, None, 42]
        call = MagicMock(return_value=Result(empty_result(), 100))
        with patch.dict(os.environ, {p['key_env']: 'test' for p in self.config['providers']}):
            self.assertEqual(process(store, self.config, call=call), 0)
        self.assertEqual(call.call_args.kwargs['max_output'], 4096)
        reservations = store.reserve.call_args_list
        self.assertEqual(reservations[2].args[2] - reservations[0].args[2], 2048)

    def test_one_successful_model_per_job_and_quota_fallback(self):
        store = MagicMock()
        job = {'id': 1, 'source_posting_id': 2, 'attempts': 0, 'input_payload': self.payload}
        store.next_job.side_effect = [job, None]
        store.reserve.side_effect = [None, 42]
        call = MagicMock(return_value=Result(empty_result(), 100))
        with patch.dict(os.environ, {p['key_env']: 'test' for p in self.config['providers']}):
            self.assertEqual(process(store, self.config, call=call), 0)
        self.assertEqual(call.call_count, 1)
        self.assertEqual(call.call_args.args[0]['name'], 'groq')
        store.finish.assert_called_once()

    def test_invalid_result_queues_without_escalation(self):
        store = MagicMock()
        job = {'id': 1, 'source_posting_id': 2, 'attempts': 0, 'input_payload': self.payload}
        store.next_job.side_effect = [job, None]
        store.reserve.return_value = 42
        call = MagicMock(return_value=Result({}, 100))
        with patch.dict(os.environ, {p['key_env']: 'test' for p in self.config['providers']}):
            self.assertEqual(process(store, self.config, call=call), 1)
        self.assertEqual(call.call_count, 1)
        self.assertEqual(store.finish.call_args.kwargs['error'], 'invalid_fields')

    def test_partial_success_completes_and_disabled_provider_is_never_called(self):
        store = MagicMock()
        job = {'id': 1, 'source_posting_id': 2, 'attempts': 0, 'input_payload': self.payload}
        store.next_job.side_effect = [job, {**job, 'id': 2}, None]
        store.reserve.return_value = 42
        call = MagicMock(side_effect=[Result({}, 100), Result(empty_result(), 100)])
        with patch.dict(os.environ, {p['key_env']: 'test' for p in self.config['providers']}):
            self.assertEqual(process(store, self.config, call=call), 0)
        self.assertEqual(store.finish.call_count, 2)
        self.assertTrue(all(c.args[0]['name'] != 'openrouter' for c in call.call_args_list))

    def test_disabled_provider_not_reserved_when_others_exhausted(self):
        store = MagicMock()
        store.next_job.return_value = {'id': 1, 'source_posting_id': 2, 'attempts': 0, 'input_payload': self.payload}
        store.reserve.return_value = None
        store.can_retry_soon.return_value = False
        with patch.dict(os.environ, {p['key_env']: 'test' for p in self.config['providers']}):
            self.assertEqual(process(store, self.config, call=MagicMock()), 0)
        self.assertEqual([c.args[1]['name'] for c in store.reserve.call_args_list], ['gemini', 'groq'])

    def test_validation_diagnostic_identifies_field_without_source_text(self):
        result = empty_result()
        result['work_mode'] = 'remote'
        result['evidence']['work_mode'] = ['private invented excerpt']
        with self.assertRaises(ValueError) as caught:
            validate(result, self.payload)
        self.assertEqual(str(caught.exception), 'unsupported_evidence')
        self.assertEqual(caught.exception.field, 'work_mode')

    def test_sync_without_migrations_stays_compatible(self):
        local, remote = MagicMock(), MagicMock()
        remote.execute.return_value.fetchall.return_value = [(c,) for c in JOB_COLUMNS]
        self.assertEqual(projection(local, remote, JOBS_QUERY, JOB_COLUMNS), (JOBS_QUERY, JOB_COLUMNS))
        local.execute.assert_not_called()

    def test_cli_enrich_does_not_call_sync_or_ingestion(self):
        with patch('sys.argv', ['joblake', '--phase', 'enrich', '--dry-run', '--max-jobs', '5']), \
                patch.object(cli, 'load_dotenv'), \
                patch('joblake.enrichment.service.run', return_value=0) as run, \
                patch('joblake.supabase_sync.sync') as sync:
            with self.assertRaises(SystemExit) as stopped:
                cli.main()
        self.assertEqual(stopped.exception.code, 0)
        run.assert_called_once_with('configs/enrichment.yaml', dry_run=True, max_jobs=5)
        sync.assert_not_called()

    def test_daily_quota_exits_without_attempt_or_busy_loop(self):
        store = MagicMock()
        store.next_job.return_value = {'id': 1, 'source_posting_id': 2, 'attempts': 0,
                                      'input_payload': self.payload}
        store.reserve.return_value = None
        store.can_retry_soon.return_value = False
        call, sleep = MagicMock(), MagicMock()
        with patch.dict(os.environ, {p['key_env']: 'test' for p in self.config['providers']}):
            self.assertEqual(process(store, self.config, call=call, sleep=sleep), 0)
        call.assert_not_called()
        sleep.assert_not_called()


if __name__ == '__main__':
    unittest.main()
