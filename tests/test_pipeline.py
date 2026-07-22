import unittest
from unittest.mock import patch

from joblake.models import FetchResult
from joblake.pipeline import IngestionPipeline
from joblake.sources import JobSource


class PipelineSource(JobSource):

    def extract_job_urls(
        self,
        html: str,
        listing_url: str,
    ) -> list[str]:
        return [
            "https://example.com/job/already-crawled",
            "https://example.com/job/new",
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

        return FetchResult(
            requested_url=url,
            final_url=url,
            status_code=200,
            content_type="text/html",
            fetched_at="2026-01-01T00:00:00+00:00",
            html="<html></html>",
        )


class PipelineStorage:

    def __init__(self):
        self.discovery_pages = []
        self.details = []

    def save_discovery(self, **kwargs):
        self.discovery_pages.append(kwargs)
        return "page.html", "page.metadata.json"

    def save_detail(self, **kwargs):
        self.details.append(kwargs)
        return "detail.html", "detail.metadata.json"


class PipelineState:

    def __init__(self):
        self.discovered = None
        self.crawled = {
            "https://example.com/job/already-crawled"
        }
        self.marked = []

    def save_discovered_jobs(self, records):
        self.discovered = records

    def load_crawled_urls(self):
        return set(self.crawled)

    def mark_crawled(self, url):
        self.marked.append(url)
        self.crawled.add(url)


class IngestionPipelineTests(unittest.TestCase):

    @patch("time.sleep")
    def test_pipeline_uses_source_storage_and_state(
        self,
        sleep,
    ) -> None:
        config = {
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
                    "base_url": "https://example.com/jobs",
                }],
            },
            "detail": {
                "transport": "fake",
                "max_jobs_per_run": None,
                "delay": {
                    "min_seconds": 0,
                    "max_seconds": 0,
                },
            },
        }
        calls = []

        def fetcher_factory(fetcher_config):
            phase = (
                "discovery"
                if "targets" in fetcher_config
                else "detail"
            )
            return PipelineFetcher(phase, calls)

        storage = PipelineStorage()
        state = PipelineState()
        pipeline = IngestionPipeline(
            config=config,
            source=PipelineSource(config),
            storage=storage,
            state=state,
            fetcher_factory=fetcher_factory,
        )

        pipeline.run()

        self.assertEqual(len(state.discovered), 2)
        self.assertEqual(len(storage.discovery_pages), 1)
        self.assertEqual(len(storage.details), 1)
        self.assertEqual(
            state.marked,
            ["https://example.com/job/new"],
        )
        detail_call = next(
            call
            for call in calls
            if call["phase"] == "detail"
        )
        self.assertEqual(
            detail_call["referer"],
            "https://example.com/jobs",
        )
        self.assertEqual(sleep.call_count, 2)


if __name__ == "__main__":
    unittest.main()
