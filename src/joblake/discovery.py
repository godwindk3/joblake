import random
import time
from datetime import datetime, timezone

from joblake.models import (
    DiscoveryRecord,
    FetchResult,
    PaginationDetectionError,
)
from joblake.sources import (
    JobSource,
    ListingRequest,
    create_source,
)
from joblake.storage import LocalRawStorage, RawStorage


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class DiscoveryCrawler:
    """Generic listing crawler driven by a website adapter."""

    def __init__(
        self,
        config: dict,
        source: JobSource,
        storage: RawStorage,
        fetcher_factory=None,
    ):
        if fetcher_factory is None:
            from joblake.fetchers import create_fetcher

            fetcher_factory = create_fetcher

        self.config = config
        self.source = source
        self.storage = storage
        self.fetcher_factory = fetcher_factory

    def run(self) -> dict[str, DiscoveryRecord]:
        discovery_config = self.config["discovery"]
        discovered_jobs: dict[
            str,
            DiscoveryRecord,
        ] = {}

        with self.fetcher_factory(
            discovery_config
        ) as fetcher:
            for target in discovery_config["targets"]:
                if not target.get("enabled", True):
                    continue

                self._crawl_target(
                    target=target,
                    discovery_config=discovery_config,
                    fetcher=fetcher,
                    discovered_jobs=discovered_jobs,
                )

        return discovered_jobs

    def _crawl_target(
        self,
        *,
        target: dict,
        discovery_config: dict,
        fetcher,
        discovered_jobs: dict[str, DiscoveryRecord],
    ) -> None:
        target_name = target["name"]
        delay = discovery_config["delay"]

        print(f"Starting target: {target_name}")

        configured_total_pages = self._configured_total_pages(
            target,
            discovery_config,
        )

        if configured_total_pages is not None:
            listing_requests = self.source.iter_listing_requests(
                target,
                discovery_config,
            )

            for request in listing_requests:
                self._crawl_listing_request(
                    request=request,
                    fetcher=fetcher,
                    delay=delay,
                    discovered_jobs=discovered_jobs,
                )

            return

        pagination = discovery_config["pagination"]
        start_page = target.get(
            "start_page",
            pagination["start_page"],
        )
        first_request = self.source.build_listing_request(
            target,
            discovery_config,
            start_page,
        )
        first_result = self._crawl_listing_request(
            request=first_request,
            fetcher=fetcher,
            delay=delay,
            discovered_jobs=discovered_jobs,
        )
        last_page = self.source.extract_last_page_number(
            html=first_result.html,
            listing_url=first_result.final_url,
        )

        if last_page is None:
            raise PaginationDetectionError(
                "Cannot detect the last page for "
                f"source={self.source.name}, target={target_name}. "
                "Configure total_pages or implement "
                "extract_last_page_number()."
            )

        if last_page < start_page:
            raise PaginationDetectionError(
                f"Detected invalid last page {last_page} for "
                f"source={self.source.name}, target={target_name}, "
                f"start_page={start_page}."
            )

        page_count = last_page - start_page + 1
        max_auto_pages = pagination.get(
            "max_auto_pages",
            200,
        )

        if page_count > max_auto_pages:
            raise PaginationDetectionError(
                f"Detected {page_count} pages for "
                f"source={self.source.name}, target={target_name}, "
                f"above max_auto_pages={max_auto_pages}."
            )

        print(
            f"Target={target_name}, auto-pagination: "
            f"last_page={last_page}, pages={page_count}"
        )

        for page_number in range(
            start_page + 1,
            last_page + 1,
        ):
            request = self.source.build_listing_request(
                target,
                discovery_config,
                page_number,
            )
            self._crawl_listing_request(
                request=request,
                fetcher=fetcher,
                delay=delay,
                discovered_jobs=discovered_jobs,
            )

    def _crawl_listing_request(
        self,
        *,
        request: ListingRequest,
        fetcher,
        delay: dict,
        discovered_jobs: dict[str, DiscoveryRecord],
    ) -> FetchResult:
        fetch_result = fetcher.fetch(
            url=request.url,
            params=request.params,
        )

        self.storage.save_discovery(
            source=self.source.name,
            target_name=request.target_name,
            page_number=request.page_number,
            fetch_result=fetch_result,
        )

        page_urls = self.source.extract_job_urls(
            html=fetch_result.html,
            listing_url=fetch_result.final_url,
        )
        previous_count = len(discovered_jobs)

        for job_url in page_urls:
            discovered_jobs.setdefault(
                job_url,
                DiscoveryRecord(
                    source=self.source.name,
                    url=job_url,
                    target_name=request.target_name,
                    listing_url=fetch_result.final_url,
                    listing_page=request.page_number,
                    discovered_at=_utc_now(),
                ),
            )

        new_count = len(discovered_jobs) - previous_count

        print(
            f"Target={request.target_name}, "
            f"page={request.page_number}, "
            f"found={len(page_urls)}, "
            f"new={new_count}, "
            f"total={len(discovered_jobs)}"
        )

        time.sleep(
            random.uniform(
                delay["min_seconds"],
                delay["max_seconds"],
            )
        )

        return fetch_result

    @staticmethod
    def _configured_total_pages(
        target: dict,
        discovery_config: dict,
    ) -> int | None:
        if target.get("total_pages") is not None:
            return target["total_pages"]

        return discovery_config["pagination"].get(
            "total_pages"
        )


def discover_all_job_urls(
    config: dict,
) -> dict[str, DiscoveryRecord]:
    """Backward-compatible functional entrypoint."""
    source = create_source(config)
    storage = LocalRawStorage.from_config(config)

    return DiscoveryCrawler(
        config=config,
        source=source,
        storage=storage,
    ).run()
