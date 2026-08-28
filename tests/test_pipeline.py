import hashlib
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from joblake.models import FetchError, FetchResult
from joblake.pipeline import IngestionPipeline
from joblake.sources import JobSource
from joblake.state import SQLiteStateStore
from joblake.storage import (
    ObjectLocator,
    RawObjectPayload,
    StoredObject,
)


class PipelineSource(JobSource):

    def extract_job_urls(
        self,
        html: str,
        listing_url: str,
    ) -> list[str]:
        return [
            "https://example.com/job/one",
            "https://example.com/job/two",
        ]


class PipelineFetcher:

    def __init__(self, phase: str, calls: list):
        self.phase = phase
        self.calls = calls

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def fetch(
        self,
        url,
        params=None,
        referer=None,
    ):
        self.calls.append({
            "phase": self.phase,
            "url": url,
            "params": params,
            "referer": referer,
        })
        html = (
            "<html><body>listing</body></html>"
            if self.phase == "discovery"
            else (
                "<html><body><h1>Backend Developer</h1>"
                "<main>Complete job description</main>"
                "</body></html>"
            )
        )

        return FetchResult(
            requested_url=url,
            final_url=url,
            status_code=200,
            content_type="text/html",
            fetched_at="2026-01-01T00:00:00+00:00",
            html=html,
        )


class InvalidDetailFetcher(PipelineFetcher):

    def fetch(self, url, params=None, referer=None):
        result = super().fetch(
            url,
            params=params,
            referer=referer,
        )

        if self.phase != "detail":
            return result

        return FetchResult(
            requested_url=result.requested_url,
            final_url=result.final_url,
            status_code=result.status_code,
            content_type=result.content_type,
            fetched_at=result.fetched_at,
            html=(
                "<html><body>"
                "Incomplete response without job title"
                "</body></html>"
            ),
        )


class MissingDiscoveryTargetFetcher(PipelineFetcher):

    def fetch(self, url, params=None, referer=None):
        if (
            self.phase == "discovery"
            and url.endswith("/others")
        ):
            raise FetchError(
                f"HTTP status 404: {url}"
            )

        return super().fetch(
            url,
            params=params,
            referer=referer,
        )


class PipelineStorage:

    def __init__(self):
        self.discovery_pages = []
        self.details = []

    def save_discovery(self, **kwargs):
        self.discovery_pages.append(kwargs)
        return None

    def prepare_detail(
        self,
        *,
        discovery_record,
        fetch_result,
    ):
        content = fetch_result.html.encode("utf-8")
        digest = hashlib.sha256(content).hexdigest()
        return RawObjectPayload(
            locator=ObjectLocator(
                provider="fake",
                bucket_name="joblake",
                object_key=(
                    f"raw/detail/{discovery_record.url.rsplit('/', 1)[-1]}"
                    ".html"
                ),
            ),
            content=content,
            content_type="text/html",
            content_sha256=digest,
        )

    def save_prepared_detail(self, payload):
        self.details.append(payload)
        return StoredObject(
            locator=payload.locator,
            content_length_bytes=(
                payload.content_length_bytes
            ),
            content_sha256=payload.content_sha256,
            stored_at="2026-01-01T00:00:01+00:00",
        )

    def stat_object(
        self,
        locator,
        *,
        expected_sha256,
    ):
        for payload in self.details:
            if payload.locator == locator:
                return StoredObject(
                    locator=locator,
                    content_length_bytes=(
                        payload.content_length_bytes
                    ),
                    content_sha256=expected_sha256,
                    stored_at=(
                        "2026-01-01T00:00:01+00:00"
                    ),
                )

        return None


class IngestionPipelineTests(unittest.TestCase):

    @patch("time.sleep")
    def test_pipeline_persists_raw_once_and_keeps_parse_table(
        self,
        sleep,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = str(
                Path(directory) / "joblake.db"
            )
            config = self._config(database_path)
            calls = []

            def fetcher_factory(fetcher_config):
                phase = (
                    "discovery"
                    if "targets" in fetcher_config
                    else "detail"
                )
                return PipelineFetcher(phase, calls)

            storage = PipelineStorage()
            state = SQLiteStateStore(database_path)
            pipeline = IngestionPipeline(
                config=config,
                source=PipelineSource(config),
                storage=storage,
                state=state,
                fetcher_factory=fetcher_factory,
            )

            pipeline.run()
            first_detail_call_count = len([
                call
                for call in calls
                if call["phase"] == "detail"
            ])

            pipeline.run()
            all_detail_calls = [
                call
                for call in calls
                if call["phase"] == "detail"
            ]

            self.assertEqual(first_detail_call_count, 2)
            self.assertEqual(len(all_detail_calls), 2)
            self.assertEqual(len(storage.details), 2)

            connection = sqlite3.connect(database_path)

            try:
                job_count = connection.execute(
                    "SELECT COUNT(*) FROM jobs"
                ).fetchone()[0]
                ready_count = connection.execute(
                    """
                    SELECT COUNT(*)
                    FROM jobs
                    WHERE raw_status = 'raw_ready'
                    """
                ).fetchone()[0]
                raw_count = connection.execute(
                    "SELECT COUNT(*) FROM raw_objects"
                ).fetchone()[0]
                parse_count = connection.execute(
                    "SELECT COUNT(*) FROM parse_attempts"
                ).fetchone()[0]
                valid_integrity_count = (
                    connection.execute(
                        """
                        SELECT COUNT(*)
                        FROM raw_objects
                        WHERE integrity_status = 'valid'
                          AND last_integrity_check_at
                              IS NOT NULL
                        """
                    ).fetchone()[0]
                )
            finally:
                connection.close()

            self.assertEqual(job_count, 2)
            self.assertEqual(ready_count, 2)
            self.assertEqual(raw_count, 2)
            self.assertEqual(parse_count, 0)
            self.assertEqual(
                valid_integrity_count,
                2,
            )
            self.assertGreaterEqual(
                sleep.call_count,
                4,
            )

    @patch("time.sleep")
    def test_invalid_html_is_not_accepted_as_raw(
        self,
        sleep,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = str(
                Path(directory) / "joblake.db"
            )
            config = self._config(database_path)
            config["detail"]["max_jobs_per_run"] = 1
            calls = []

            def fetcher_factory(fetcher_config):
                phase = (
                    "discovery"
                    if "targets" in fetcher_config
                    else "detail"
                )
                return InvalidDetailFetcher(
                    phase,
                    calls,
                )

            storage = PipelineStorage()
            pipeline = IngestionPipeline(
                config=config,
                source=PipelineSource(config),
                storage=storage,
                state=SQLiteStateStore(database_path),
                fetcher_factory=fetcher_factory,
            )

            pipeline.run()
            connection = sqlite3.connect(database_path)

            try:
                raw_count = connection.execute(
                    "SELECT COUNT(*) FROM raw_objects"
                ).fetchone()[0]
                attempt_status = connection.execute(
                    """
                    SELECT status
                    FROM fetch_attempts
                    ORDER BY id
                    LIMIT 1
                    """
                ).fetchone()[0]
                job_status = connection.execute(
                    """
                    SELECT raw_status
                    FROM jobs
                    WHERE fetch_attempt_count = 1
                    """
                ).fetchone()[0]
            finally:
                connection.close()

            self.assertEqual(raw_count, 0)
            self.assertEqual(
                attempt_status,
                "invalid_response",
            )
            self.assertEqual(
                job_status,
                "retryable_error",
            )
            self.assertEqual(storage.details, [])

    @patch("time.sleep")
    def test_discovery_and_detail_can_run_separately(
        self,
        sleep,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = str(
                Path(directory) / "joblake.db"
            )
            config = self._config(database_path)
            calls = []

            def fetcher_factory(fetcher_config):
                phase = (
                    "discovery"
                    if "targets" in fetcher_config
                    else "detail"
                )
                return PipelineFetcher(phase, calls)

            storage = PipelineStorage()
            pipeline = IngestionPipeline(
                config=config,
                source=PipelineSource(config),
                storage=storage,
                state=SQLiteStateStore(database_path),
                fetcher_factory=fetcher_factory,
            )

            pipeline.run(phase="discovery")

            self.assertEqual(
                [
                    call
                    for call in calls
                    if call["phase"] == "detail"
                ],
                [],
            )
            self.assertEqual(storage.details, [])

            pipeline.run(phase="detail")

            detail_calls = [
                call
                for call in calls
                if call["phase"] == "detail"
            ]
            self.assertEqual(len(detail_calls), 2)
            self.assertEqual(len(storage.details), 2)

    @patch("time.sleep")
    def test_full_pipeline_reaches_detail_after_target_404(
        self,
        sleep,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = str(
                Path(directory) / "joblake.db"
            )
            config = self._config(database_path)
            config["discovery"][
                "continue_on_target_error"
            ] = True
            config["discovery"]["targets"].append({
                "name": "others",
                "base_url": (
                    "https://example.com/others"
                ),
            })
            calls = []

            def fetcher_factory(fetcher_config):
                phase = (
                    "discovery"
                    if "targets" in fetcher_config
                    else "detail"
                )
                return MissingDiscoveryTargetFetcher(
                    phase,
                    calls,
                )

            storage = PipelineStorage()
            pipeline = IngestionPipeline(
                config=config,
                source=PipelineSource(config),
                storage=storage,
                state=SQLiteStateStore(database_path),
                fetcher_factory=fetcher_factory,
            )

            pipeline.run()

            detail_calls = [
                call
                for call in calls
                if call["phase"] == "detail"
            ]
            self.assertEqual(len(detail_calls), 2)
            self.assertEqual(len(storage.details), 2)

            connection = sqlite3.connect(database_path)

            try:
                run_status = connection.execute(
                    """
                    SELECT status
                    FROM crawl_runs
                    ORDER BY id DESC
                    LIMIT 1
                    """
                ).fetchone()[0]
                target_statuses = dict(
                    connection.execute(
                        """
                        SELECT target_name, status
                        FROM discovery_targets
                        ORDER BY id
                        """
                    ).fetchall()
                )
            finally:
                connection.close()

            self.assertEqual(run_status, "suspicious")
            self.assertEqual(
                target_statuses,
                {
                    "all": "completed",
                    "others": "failed",
                },
            )

    @staticmethod
    def _config(database_path: str) -> dict:
        return {
            "source": "example",
            "discovery": {
                "transport": "fake",
                "pagination": {
                    "page_param": "page",
                    "start_page": 1,
                    "total_pages": 1,
                },
                "delay": {
                    "min_seconds": 0,
                    "max_seconds": 0,
                },
                "targets": [{
                    "name": "all",
                    "base_url": (
                        "https://example.com/jobs"
                    ),
                }],
            },
            "detail": {
                "transport": "fake",
                "max_jobs_per_run": None,
                "validation": {
                    "min_html_bytes": 1,
                    "min_text_chars": 1,
                    "required_selectors": ["h1"],
                },
                "delay": {
                    "min_seconds": 0,
                    "max_seconds": 0,
                },
            },
            "state": {
                "provider": "sqlite",
                "database_path": database_path,
                "detail_max_attempts": 3,
                "detail_retry_delay_seconds": 3600,
                "integrity_check_on_start": True,
                "integrity_check_limit": 100,
            },
        }


if __name__ == "__main__":
    unittest.main()
