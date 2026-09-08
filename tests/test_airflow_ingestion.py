"""Scheduler exit codes, without crawling websites or accessing live databases."""
import unittest
from unittest.mock import MagicMock, patch

from joblake import main as cli
from joblake.models import FetchError, SourceBlockedError
from joblake.pipeline import IngestionPipeline


class SchedulerCliTests(unittest.TestCase):
    def invoke(self, status, strict=True):
        args = ["joblake", "--config", "configs/itviec.yaml", "--phase", "detail"]
        if strict:
            args.append("--strict")
        with patch("sys.argv", args), patch.object(cli, "load_dotenv"), patch(
            "joblake.pipeline.run_pipeline", return_value=status
        ) as run:
            cli.main()
        run.assert_called_once_with("configs/itviec.yaml", phase="detail")

    def test_completed_and_empty_queue_are_success(self):
        self.invoke("completed")

    def test_failed_and_blocked_runs_fail_scheduler_task(self):
        for status in ("failed", "blocked"):
            with self.subTest(status=status), self.assertRaises(SystemExit) as result:
                self.invoke(status)
            self.assertEqual(result.exception.code, 1)

    def test_suspicious_run_allows_downstream_scheduler_phase(self):
        self.invoke("suspicious")

    def test_manual_cli_keeps_existing_exit_behavior(self):
        self.invoke("suspicious", strict=False)


class PipelineOutcomeTests(unittest.TestCase):
    def pipeline(self):
        return IngestionPipeline(
            config={}, source=MagicMock(), storage=MagicMock(), state=MagicMock(),
            fetcher_factory=MagicMock(),
        )

    def test_discovery_errors_are_returned_after_state_is_saved(self):
        for error, expected in ((SourceBlockedError("blocked"), "blocked"),
                                (FetchError("offline"), "failed")):
            with self.subTest(expected=expected):
                pipeline = self.pipeline()
                crawler = MagicMock()
                crawler.run.side_effect = error
                crawler.run_records = []
                crawler.new_job_count = 0
                with patch.object(pipeline, "_recover_interrupted_work"), patch.object(
                    pipeline, "_create_discovery_crawler", return_value=crawler
                ):
                    self.assertEqual(pipeline.run("discovery"), expected)
                self.assertEqual(pipeline.state.finish_run.call_args.kwargs["status"], expected)

    def test_detail_blocked_status_reaches_caller(self):
        pipeline = self.pipeline()
        with patch.object(pipeline, "_recover_interrupted_work"), patch.object(
            pipeline, "_run_details", return_value="blocked"
        ):
            self.assertEqual(pipeline.run("detail"), "blocked")

    def test_parse_quality_errors_are_visible_to_scheduler(self):
        pipeline = self.pipeline()
        service = MagicMock()
        service.run.return_value.has_failures = True
        pipeline.parse_service_factory = MagicMock(return_value=service)
        self.assertEqual(pipeline.run("parse"), "suspicious")


if __name__ == "__main__":
    unittest.main()
