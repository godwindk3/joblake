import unittest
from unittest.mock import MagicMock, patch

from joblake.pipeline import IngestionPipeline


class DetailErrorLimitTests(unittest.TestCase):
    def run_details(self, outcomes, limit):
        config = {'detail': {'max_consecutive_errors': limit, 'delay': {}}, 'state': {}}
        state = MagicMock()
        state.claim_next_job.side_effect = [MagicMock() for _ in outcomes] + [None]
        pipeline = IngestionPipeline(config, source=MagicMock(), state=state,
                                     storage=MagicMock(), fetcher_factory=MagicMock())
        results = iter(outcomes)

        def crawl(**kwargs):
            if next(results):
                pipeline._detail_error_count += 1
            return True

        with patch.object(pipeline, '_crawl_detail', side_effect=crawl) as fetch, \
                patch.object(pipeline, '_sleep'):
            status = pipeline._run_details(1)
        return status, fetch.call_count

    def test_repeated_errors_stop_before_claiming_rest_of_queue(self):
        self.assertEqual(self.run_details([True] * 8, 3), ('failed', 3))

    def test_success_resets_streak(self):
        self.assertEqual(self.run_details([True, True, False, True, True], 3), ('suspicious', 5))

    def test_other_sources_keep_existing_behavior_without_limit(self):
        self.assertEqual(self.run_details([True] * 5, None), ('suspicious', 5))

    def test_all_successful(self):
        self.assertEqual(self.run_details([False] * 5, 3), ('completed', 5))

    def test_invalid_limit_rejected(self):
        with self.assertRaises(ValueError):
            self.run_details([False], 0)
