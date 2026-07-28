import random
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from joblake.models import (
    DiscoveryRecord,
    FetchError,
    FetchResult,
    PaginationDetectionError,
    SourceBlockedError,
)
from joblake.sources import (
    JobSource,
    ListingRequest,
    create_source,
)
from joblake.state import StateStore
from joblake.storage import (
    RawStorage,
    create_raw_storage,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class _TargetProgress:
    state_id: int | None = None
    detected_last_page: int | None = None
    fetched_page_count: int = 0
    discovered_url_count: int = 0
    new_url_count: int = 0
    duplicate_url_count: int = 0
    empty_page_count: int = 0
    invalid_page_count: int = 0


@dataclass(frozen=True, slots=True)
class _PageResult:
    fetch_result: FetchResult
    page_urls: list[str]


class DiscoveryCrawler:
    """Generic listing crawler driven by a website adapter."""

    def __init__(
        self,
        config: dict,
        source: JobSource,
        storage: RawStorage,
        fetcher_factory=None,
        state: StateStore | None = None,
        run_id: int | None = None,
    ):
        if fetcher_factory is None:
            from joblake.fetchers import create_fetcher

            fetcher_factory = create_fetcher

        if state is not None and run_id is None:
            raise ValueError(
                "run_id is required when discovery uses state"
            )

        self.config = config
        self.source = source
        self.storage = storage
        self.fetcher_factory = fetcher_factory
        self.state = state
        self.run_id = run_id
        self.new_job_count = 0
        self.has_suspicious_targets = False
        self.has_failed_targets = False
        self.target_errors: list[str] = []
        self.run_records: dict[
            str,
            DiscoveryRecord,
        ] = {}

    def run(self) -> dict[str, DiscoveryRecord]:
        discovery_config = self.config["discovery"]
        self.new_job_count = 0
        self.has_suspicious_targets = False
        self.has_failed_targets = False
        self.target_errors.clear()
        discovered_jobs: dict[
            str,
            DiscoveryRecord,
        ] = {}
        self.run_records = discovered_jobs
        continue_on_target_error = bool(
            discovery_config.get(
                "continue_on_target_error",
                False,
            )
        )

        with self.fetcher_factory(
            discovery_config
        ) as fetcher:
            for target in discovery_config["targets"]:
                if not target.get("enabled", True):
                    continue

                try:
                    self._run_target(
                        target=target,
                        discovery_config=discovery_config,
                        fetcher=fetcher,
                        discovered_jobs=discovered_jobs,
                    )
                except SourceBlockedError:
                    raise
                except (
                    FetchError,
                    PaginationDetectionError,
                ) as exc:
                    self.has_failed_targets = True
                    self.target_errors.append(
                        f"{target['name']}: {exc}"
                    )

                    if not continue_on_target_error:
                        raise

                    print(
                        "Discovery target failed; "
                        "continuing with the next target: "
                        f"{target['name']} ({exc})"
                    )

        return discovered_jobs

    def _run_target(
        self,
        *,
        target: dict,
        discovery_config: dict,
        fetcher,
        discovered_jobs: dict[str, DiscoveryRecord],
    ) -> None:
        progress = _TargetProgress()
        target_name = target["name"]
        started_at = _utc_now()

        if self.state is not None:
            progress.state_id = (
                self.state.start_discovery_target(
                    run_id=self._required_run_id(),
                    source=self.source.name,
                    target_name=target_name,
                    started_at=started_at,
                )
            )

        try:
            self._crawl_target(
                target=target,
                discovery_config=discovery_config,
                fetcher=fetcher,
                discovered_jobs=discovered_jobs,
                progress=progress,
            )
        except Exception as exc:
            status = (
                "blocked"
                if isinstance(exc, SourceBlockedError)
                else "failed"
            )
            self._finish_target(
                progress=progress,
                status=status,
                error=exc,
            )
            raise

        status = "completed"

        if (
            progress.empty_page_count > 0
            or progress.discovered_url_count == 0
        ):
            status = "suspicious"
            self.has_suspicious_targets = True

        self._finish_target(
            progress=progress,
            status=status,
        )

    def _finish_target(
        self,
        *,
        progress: _TargetProgress,
        status: str,
        error: Exception | None = None,
    ) -> None:
        if (
            self.state is None
            or progress.state_id is None
        ):
            return

        self.state.finish_discovery_target(
            progress.state_id,
            status=status,
            finished_at=_utc_now(),
            detected_last_page=(
                progress.detected_last_page
            ),
            fetched_page_count=(
                progress.fetched_page_count
            ),
            discovered_url_count=(
                progress.discovered_url_count
            ),
            new_url_count=progress.new_url_count,
            duplicate_url_count=(
                progress.duplicate_url_count
            ),
            empty_page_count=progress.empty_page_count,
            invalid_page_count=(
                progress.invalid_page_count
            ),
            error_type=(
                type(error).__name__
                if error is not None
                else None
            ),
            error_message=(
                str(error)
                if error is not None
                else None
            ),
        )

    def _crawl_target(
        self,
        *,
        target: dict,
        discovery_config: dict,
        fetcher,
        discovered_jobs: dict[str, DiscoveryRecord],
        progress: _TargetProgress,
    ) -> None:
        target_name = target["name"]
        delay = discovery_config["delay"]

        print(f"Starting target: {target_name}")

        configured_total_pages = self._configured_total_pages(
            target,
            discovery_config,
        )
        pagination = discovery_config["pagination"]
        start_page = target.get(
            "start_page",
            pagination["start_page"],
        )

        if configured_total_pages is not None:
            progress.detected_last_page = (
                start_page + configured_total_pages - 1
            )

            for request in self.source.iter_listing_requests(
                target,
                discovery_config,
            ):
                self._crawl_listing_request(
                    request=request,
                    fetcher=fetcher,
                    delay=delay,
                    discovered_jobs=discovered_jobs,
                    progress=progress,
                )

            return

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
            progress=progress,
        )
        last_page = self.source.extract_last_page_number(
            html=first_result.fetch_result.html,
            listing_url=(
                first_result.fetch_result.final_url
            ),
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

        progress.detected_last_page = last_page
        page_count = last_page - start_page + 1
        max_auto_pages = int(
            pagination.get("max_auto_pages", 200)
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
                progress=progress,
            )

    def _crawl_listing_request(
        self,
        *,
        request: ListingRequest,
        fetcher,
        delay: dict,
        discovered_jobs: dict[str, DiscoveryRecord],
        progress: _TargetProgress,
    ) -> _PageResult:
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
        discovered_at = _utc_now()
        page_records = [
            DiscoveryRecord(
                source=self.source.name,
                url=job_url,
                target_name=request.target_name,
                listing_url=fetch_result.final_url,
                listing_page=request.page_number,
                discovered_at=discovered_at,
            )
            for job_url in page_urls
        ]
        previous_count = len(discovered_jobs)

        for record in page_records:
            discovered_jobs.setdefault(
                record.url,
                record,
            )

        in_run_new_count = (
            len(discovered_jobs) - previous_count
        )
        persisted_new_count = in_run_new_count

        if self.state is not None:
            persisted_new_count = (
                self.state.upsert_discovered_jobs(
                    page_records,
                    self._required_run_id(),
                )
            )

        progress.fetched_page_count += 1
        progress.discovered_url_count += len(page_urls)
        progress.new_url_count += persisted_new_count
        progress.duplicate_url_count += (
            len(page_urls) - persisted_new_count
        )

        if not page_urls:
            progress.empty_page_count += 1

        self.new_job_count += persisted_new_count

        print(
            f"Target={request.target_name}, "
            f"page={request.page_number}, "
            f"found={len(page_urls)}, "
            f"new={persisted_new_count}, "
            f"run_unique={len(discovered_jobs)}"
        )

        time.sleep(
            random.uniform(
                delay["min_seconds"],
                delay["max_seconds"],
            )
        )

        return _PageResult(
            fetch_result=fetch_result,
            page_urls=page_urls,
        )

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

    def _required_run_id(self) -> int:
        if self.run_id is None:
            raise RuntimeError(
                "Discovery state requires a run_id"
            )

        return self.run_id


def discover_all_job_urls(
    config: dict,
) -> dict[str, DiscoveryRecord]:
    """Backward-compatible discovery-only entrypoint."""
    source = create_source(config)
    storage = create_raw_storage(config)

    return DiscoveryCrawler(
        config=config,
        source=source,
        storage=storage,
    ).run()
