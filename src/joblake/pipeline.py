import random
import time

from joblake.discovery import DiscoveryCrawler
from joblake.models import (
    DiscoveryRecord,
    FetchError,
    PaginationDetectionError,
    SourceBlockedError,
)
from joblake.sources import JobSource, create_source
from joblake.state import FileStateStore, StateStore
from joblake.storage import (
    LocalRawStorage,
    RawStorage,
)


class IngestionPipeline:
    """Coordinates discovery, detail fetching, state, and storage."""

    def __init__(
        self,
        config: dict,
        source: JobSource | None = None,
        storage: RawStorage | None = None,
        state: StateStore | None = None,
        fetcher_factory=None,
    ):
        if fetcher_factory is None:
            from joblake.fetchers import create_fetcher

            fetcher_factory = create_fetcher

        self.config = config
        self.source = source or create_source(config)
        self.storage = (
            storage
            or LocalRawStorage.from_config(config)
        )
        self.state = (
            state
            or FileStateStore.from_config(config)
        )
        self.fetcher_factory = fetcher_factory

    def run(self) -> None:
        discovered_jobs = self._run_discovery()

        if discovered_jobs is None:
            return

        self.state.save_discovered_jobs(
            discovered_jobs
        )

        print(
            f"Discovery completed: "
            f"{len(discovered_jobs)} unique jobs"
        )

        self._run_details(discovered_jobs)

    def _run_discovery(
        self,
    ) -> dict[str, DiscoveryRecord] | None:
        print("========== PHASE 1: DISCOVERY ==========")

        crawler = DiscoveryCrawler(
            config=self.config,
            source=self.source,
            storage=self.storage,
            fetcher_factory=self.fetcher_factory,
        )

        try:
            return crawler.run()
        except SourceBlockedError as exc:
            print(f"Discovery stopped: {exc}")
        except FetchError as exc:
            print(f"Discovery failed: {exc}")
        except PaginationDetectionError as exc:
            print(f"Discovery pagination failed: {exc}")

        return None

    def _run_details(
        self,
        discovered_jobs: dict[str, DiscoveryRecord],
    ) -> None:
        print("========== PHASE 2: DETAIL ==========")

        crawled_urls = self.state.load_crawled_urls()
        pending_jobs = [
            record
            for url, record in discovered_jobs.items()
            if url not in crawled_urls
        ]

        print(f"Already crawled: {len(crawled_urls)}")
        print(f"Pending this run: {len(pending_jobs)}")

        detail_config = self.config["detail"]
        max_jobs = detail_config.get("max_jobs_per_run")

        if max_jobs is not None:
            pending_jobs = pending_jobs[:max_jobs]

        if not pending_jobs:
            return

        with self.fetcher_factory(
            detail_config
        ) as fetcher:
            for index, record in enumerate(
                pending_jobs,
                start=1,
            ):
                print(
                    f"Detail {index}/{len(pending_jobs)}: "
                    f"{record.url}"
                )

                if not self._crawl_detail(
                    fetcher=fetcher,
                    record=record,
                    crawled_urls=crawled_urls,
                ):
                    break

                self._sleep(detail_config["delay"])

    def _crawl_detail(
        self,
        *,
        fetcher,
        record: DiscoveryRecord,
        crawled_urls: set[str],
    ) -> bool:
        request = self.source.build_detail_request(record)

        try:
            fetch_result = fetcher.fetch(
                url=request.url,
                params=request.params,
                referer=request.referer,
            )
            html_path, metadata_path = (
                self.storage.save_detail(
                    discovery_record=record,
                    fetch_result=fetch_result,
                )
            )

            self.state.mark_crawled(record.url)
            crawled_urls.add(record.url)

            print(f"HTML: {html_path}")
            print(f"Metadata: {metadata_path}")

        except SourceBlockedError as exc:
            print(f"Detail crawling blocked: {exc}")
            return False

        except FetchError as exc:
            print(
                "Detail failed, will retry next run: "
                f"{exc}"
            )

        except Exception as exc:
            print(
                f"Unexpected error for {record.url}: "
                f"{exc}"
            )

        return True

    @staticmethod
    def _sleep(delay: dict) -> None:
        time.sleep(
            random.uniform(
                delay["min_seconds"],
                delay["max_seconds"],
            )
        )


def run_pipeline(config_path: str) -> None:
    """Backward-compatible functional entrypoint."""
    from joblake.config import load_config

    IngestionPipeline(
        load_config(config_path)
    ).run()
