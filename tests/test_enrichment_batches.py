import copy
import unittest
from unittest.mock import MagicMock, patch

from joblake.enrichment.providers import Result, ProviderError, request_body
from joblake.enrichment.schema import FIELDS, validate_batch
from joblake.enrichment.service import process, load_config, estimate_tokens


def empty():
    return {**dict.fromkeys(FIELDS), 'evidence': {field: [] for field in FIELDS}}


def jobs():
    return [dict(id=i, source_posting_id=i, attempts=0, input_payload={'requirements_text': text})
            for i, text in enumerate(['Required Python.', 'Required Java.', 'Required SQL.'], 1)]


def response(items):
    return {'jobs': [{'job_id': str(job['id']), 'result': empty()} for job in items]}


class BatchTests(unittest.TestCase):
    def test_id_mapping_and_cross_job_evidence(self):
        items = jobs()
        data = response(items[::-1])
        data['jobs'][0]['result']['skills_required'] = ['Python']
        data['jobs'][0]['result']['evidence']['skills_required'] = ['Required Python.']
        outcomes = validate_batch(data, items)
        self.assertIsNone(outcomes[1][1])
        self.assertIsNone(outcomes[2][1])
        self.assertEqual(outcomes[3][1], 'unsupported_evidence')

    def test_missing_duplicate_and_unknown_ids(self):
        items = jobs()
        data = response(items[:2])
        data['jobs'].append(copy.deepcopy(data['jobs'][0]))
        outcomes = validate_batch(data, items)
        self.assertEqual(outcomes[1][1], 'duplicate_batch_job')
        self.assertIsNone(outcomes[2][1])
        self.assertEqual(outcomes[3][1], 'missing_batch_job')
        data['jobs'][0]['job_id'] = 'unknown'
        self.assertTrue(all(error == 'unknown_batch_job' for _, error in validate_batch(data, items).values()))

    def test_body_has_single_shared_prompt_schema_and_larger_output(self):
        provider = load_config('configs/enrichment.yaml')['providers'][0]
        body = request_body(provider, jobs(), 6144, batch=True)
        self.assertEqual(body['generationConfig']['maxOutputTokens'], 6144)
        self.assertEqual(body['generationConfig']['responseJsonSchema']['properties']['jobs']['minItems'], 3)
        self.assertLess(estimate_tokens(jobs(), 6144, batch=True),
                        sum(estimate_tokens(j['input_payload'], 2048) for j in jobs()))
        with self.assertRaises(ValueError):
            request_body({'name': 'groq'}, jobs(), 6144, batch=True)

    def setup_worker(self):
        config = load_config('configs/enrichment.yaml')
        config['providers'] = [config['providers'][0]]
        config['providers'][0]['batch_size'] = 3
        config['max_jobs_per_run'] = 1
        store = MagicMock()
        store.next_job.return_value = jobs()[0]
        store.batch_followers.return_value = jobs()[1:]
        store.reserve_batch.return_value = 10
        store.reserve.return_value = 11
        return config, store

    def test_one_request_partial_failure_and_output_budget(self):
        config, store = self.setup_worker()
        data = response(jobs())
        data['jobs'][1]['result'] = {}
        call = MagicMock(return_value=Result(data, 600, 400, 200))
        with patch.dict('os.environ', {'GEMINI_API_KEY': 'test'}):
            self.assertEqual(process(store, config, batch_call=call), 0)
        call.assert_called_once()
        self.assertEqual(call.call_args.kwargs['max_output'], 6144)
        store.reserve_batch.assert_called_once()
        outcomes = store.finish_batch.call_args.args[2]
        self.assertIsNone(outcomes[1][1])
        self.assertEqual(outcomes[2][1], 'invalid_fields')
        self.assertIsNone(outcomes[3][1])

    def test_quota_shrinks_group_then_uses_single(self):
        config, store = self.setup_worker()
        store.reserve_batch.return_value = None
        call = MagicMock(return_value=Result(empty(), 100))
        batch_call = MagicMock()
        with patch.dict('os.environ', {'GEMINI_API_KEY': 'test'}):
            self.assertEqual(process(store, config, call=call, batch_call=batch_call), 0)
        self.assertEqual([len(c.args[0]) for c in store.reserve_batch.call_args_list], [3, 2])
        batch_call.assert_not_called()
        call.assert_called_once()

    def test_retry_job_is_single_and_long_job_is_not_grouped(self):
        for retry in (False, True):
            config, store = self.setup_worker()
            if retry:
                store.next_job.return_value['attempts'] = 1
            else:
                config['providers'][0]['batch_max_input_tokens'] = 1
            call = MagicMock(return_value=Result(empty(), 100))
            with patch.dict('os.environ', {'GEMINI_API_KEY': 'test'}):
                self.assertEqual(process(store, config, call=call), 0)
            store.reserve_batch.assert_not_called()
            call.assert_called_once()

    def test_transport_failure_marks_every_member_and_keeps_unknown_usage(self):
        config, store = self.setup_worker()
        with patch.dict('os.environ', {'GEMINI_API_KEY': 'test'}):
            self.assertEqual(process(store, config, batch_call=MagicMock(side_effect=ProviderError('http_503', 120))), 1)
        outcomes = store.finish_batch.call_args.args[2]
        self.assertEqual([error for _, error in outcomes.values()], ['http_503'] * 3)
        self.assertIsNone(store.finish_batch.call_args.kwargs['tokens'])


if __name__ == '__main__':
    unittest.main()
