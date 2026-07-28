import unittest
from unittest.mock import patch

from joblake.discovery import DiscoveryCrawler
from joblake.models import (
    FetchError,
    FetchResult,
    PaginationDetectionError,
)
from joblake.sources import JobSource


class FakeSource(JobSource):

    def extract_job_urls(
        self,
        html: str,
        listing_url: str,
    ) -> list[str]:
        page_number = listing_url.rsplit("=", 1)[-1]

        return [
            "https://example.com/job/shared",
            f"https://example.com/job/{page_number}",
        ]


class AutoPaginationSource(FakeSource):

    def extract_last_page_number(
        self,
        html: str,
        listing_url: str,
    ) -> int | None:
        return 3


class FakeFetcher:

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def fetch(self, url, params=None, **_):
        page_number = params["page"]

        return FetchResult(
            requested_url=url,
            final_url=f"{url}?page={page_number}",
            status_code=200,
            content_type="text/html",
            fetched_at="2026-01-01T00:00:00+00:00",
            html="<html></html>",
        )


class MissingTargetFetcher(FakeFetcher):

    def fetch(self, url, params=None, **kwargs):
        if url.endswith("/others"):
            raise FetchError(
                f"HTTP status 404: {url}"
            )

        return super().fetch(
            url,
            params=params,
            **kwargs,
        )


class FakeStorage:

    def __init__(self):
        self.pages = []

    def save_discovery(self, **kwargs):
        self.pages.append(kwargs)

        return "page.html", "page.metadata.json"

    def save_detail(self, **kwargs):
        return "detail.html", "detail.metadata.json"


class DiscoveryCrawlerTests(unittest.TestCase):

    @patch("joblake.discovery.time.sleep")
    def test_generic_crawler_delegates_extraction(
        self,
        sleep,
    ) -> None:
        config = {
            "source": "fake",
            "discovery": {
                "pagination": {
                    "page_param": "page",
                    "start_page": 1,
                    "total_pages": 2,
                },
                "delay": {
                    "min_seconds": 0,
                    "max_seconds": 0,
                },
                "targets": [
                    {
                        "name": "engineering",
                        "base_url": (
                            "https://example.com/jobs"
                        ),
                    }
                ],
            },
        }
        source = FakeSource(config)
        storage = FakeStorage()
        crawler = DiscoveryCrawler(
            config=config,
            source=source,
            storage=storage,
            fetcher_factory=lambda _: FakeFetcher(),
        )

        records = crawler.run()

        self.assertEqual(len(storage.pages), 2)
        self.assertEqual(len(records), 3)
        self.assertIn(
            "https://example.com/job/shared",
            records,
        )
        self.assertEqual(sleep.call_count, 2)

    @patch("joblake.discovery.time.sleep")
    def test_detects_last_page_when_total_pages_is_missing(
        self,
        sleep,
    ) -> None:
        config = {
            "source": "fake",
            "discovery": {
                "pagination": {
                    "page_param": "page",
                    "start_page": 1,
                    "max_auto_pages": 10,
                },
                "delay": {
                    "min_seconds": 0,
                    "max_seconds": 0,
                },
                "targets": [{
                    "name": "engineering",
                    "base_url": "https://example.com/jobs",
                }],
            },
        }
        storage = FakeStorage()
        crawler = DiscoveryCrawler(
            config=config,
            source=AutoPaginationSource(config),
            storage=storage,
            fetcher_factory=lambda _: FakeFetcher(),
        )

        records = crawler.run()

        self.assertEqual(len(storage.pages), 3)
        self.assertEqual(
            [page["page_number"] for page in storage.pages],
            [1, 2, 3],
        )
        self.assertEqual(len(records), 4)
        self.assertEqual(sleep.call_count, 3)

    @patch("joblake.discovery.time.sleep")
    def test_fails_clearly_when_last_page_cannot_be_detected(
        self,
        sleep,
    ) -> None:
        config = {
            "source": "fake",
            "discovery": {
                "pagination": {
                    "page_param": "page",
                    "start_page": 1,
                },
                "delay": {
                    "min_seconds": 0,
                    "max_seconds": 0,
                },
                "targets": [{
                    "name": "engineering",
                    "base_url": "https://example.com/jobs",
                }],
            },
        }
        crawler = DiscoveryCrawler(
            config=config,
            source=FakeSource(config),
            storage=FakeStorage(),
            fetcher_factory=lambda _: FakeFetcher(),
        )

        with self.assertRaises(PaginationDetectionError):
            crawler.run()

        self.assertEqual(sleep.call_count, 1)

    @patch("joblake.discovery.time.sleep")
    def test_continues_after_one_target_returns_404(
        self,
        sleep,
    ) -> None:
        config = {
            "source": "fake",
            "discovery": {
                "continue_on_target_error": True,
                "pagination": {
                    "page_param": "page",
                    "start_page": 1,
                    "total_pages": 1,
                },
                "delay": {
                    "min_seconds": 0,
                    "max_seconds": 0,
                },
                "targets": [
                    {
                        "name": "engineering",
                        "base_url": (
                            "https://example.com/jobs"
                        ),
                    },
                    {
                        "name": "others",
                        "base_url": (
                            "https://example.com/others"
                        ),
                    },
                ],
            },
        }
        storage = FakeStorage()
        crawler = DiscoveryCrawler(
            config=config,
            source=FakeSource(config),
            storage=storage,
            fetcher_factory=(
                lambda _: MissingTargetFetcher()
            ),
        )

        records = crawler.run()

        self.assertEqual(len(records), 2)
        self.assertEqual(len(storage.pages), 1)
        self.assertTrue(crawler.has_failed_targets)
        self.assertEqual(len(crawler.target_errors), 1)
        self.assertIn("others", crawler.target_errors[0])
        self.assertEqual(sleep.call_count, 1)


if __name__ == "__main__":
    unittest.main()
