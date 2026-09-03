import random
import time
from datetime import datetime, timedelta, timezone

from joblake.discovery import DiscoveryCrawler
from joblake.models import (
    FetchError,
    PaginationDetectionError,
    SourceBlockedError,
    StorageIntegrityError,
)
from joblake.sources import JobSource, create_source
from joblake.state import (
    JobClaim,
    StateStore,
    create_state_store,
)
from joblake.storage import (
    RawStorage,
    create_raw_storage,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class IngestionPipeline:
    """Coordinates discovery, detail fetching, state, and storage."""

    def __init__(
        self,
        config: dict,
        source: JobSource | None = None,
        storage: RawStorage | None = None,
        state: StateStore | None = None,
        fetcher_factory=None,
        parse_service_factory=None,
    ):
        if fetcher_factory is None:
            from joblake.fetchers import create_fetcher

            fetcher_factory = create_fetcher

        self.config = config
        self.source = source or create_source(config)
        self.storage = storage or create_raw_storage(config)
        self.state = state or create_state_store(config)
        self.fetcher_factory = fetcher_factory
        self.parse_service_factory = parse_service_factory

    def run(self, phase: str = "full") -> None:
        if phase not in {
            "full",
            "discovery",
            "detail",
            "parse",
        }:
            raise ValueError(
                "phase must be one of: "
                "full, discovery, detail, parse"
            )

        run_id = self.state.start_run(
            self.source.name,
            _utc_now(),
        )
        crawler: DiscoveryCrawler | None = None
        discovered_url_count = 0
        new_url_count = 0

        if phase != "parse":
            try:
                self._recover_interrupted_work()
            except Exception as exc:
                self._finish_failed_run(
                    run_id,
                    status="failed",
                    error=exc,
                    discovered_url_count=0,
                    new_url_count=0,
                )
                raise

        if phase == "parse":
            self._run_parse_phase(run_id)
            return

        if phase in {"full", "discovery"}:
            crawler = self._create_discovery_crawler(
                run_id
            )

            try:
                print(
                    "========== PHASE 1: DISCOVERY =========="
                )
                crawler.run()
                discovered_url_count = len(
                    crawler.run_records
                )
                new_url_count = crawler.new_job_count
            except SourceBlockedError as exc:
                discovered_url_count = len(
                    crawler.run_records
                )
                new_url_count = crawler.new_job_count
                self._finish_failed_run(
                    run_id,
                    status="blocked",
                    error=exc,
                    discovered_url_count=(
                        discovered_url_count
                    ),
                    new_url_count=new_url_count,
                )
                print(f"Discovery stopped: {exc}")
                return
            except (
                FetchError,
                PaginationDetectionError,
            ) as exc:
                discovered_url_count = len(
                    crawler.run_records
                )
                new_url_count = crawler.new_job_count
                self._finish_failed_run(
                    run_id,
                    status="failed",
                    error=exc,
                    discovered_url_count=(
                        discovered_url_count
                    ),
                    new_url_count=new_url_count,
                )
                print(f"Discovery failed: {exc}")
                return
            except Exception as exc:
                discovered_url_count = len(
                    crawler.run_records
                )
                new_url_count = crawler.new_job_count
                self._finish_failed_run(
                    run_id,
                    status="failed",
                    error=exc,
                    discovered_url_count=(
                        discovered_url_count
                    ),
                    new_url_count=new_url_count,
                )
                raise

            discovery_result = (
                "completed with target errors"
                if crawler.has_failed_targets
                else "completed"
            )
            print(
                f"Discovery {discovery_result}: "
                f"{discovered_url_count} unique jobs, "
                f"{new_url_count} new"
            )

            if phase == "discovery":
                run_status = (
                    "suspicious"
                    if (
                        crawler.has_suspicious_targets
                        or crawler.has_failed_targets
                    )
                    else "completed"
                )
                self.state.finish_run(
                    run_id,
                    status=run_status,
                    finished_at=_utc_now(),
                    discovered_url_count=(
                        discovered_url_count
                    ),
                    new_url_count=new_url_count,
                )
                return

        try:
            detail_status = self._run_details(run_id)
        except Exception as exc:
            self._finish_failed_run(
                run_id,
                status="failed",
                error=exc,
                discovered_url_count=(
                    discovered_url_count
                ),
                new_url_count=new_url_count,
            )
            raise

        run_status = detail_status

        if (
            run_status == "completed"
            and crawler is not None
            and (
                crawler.has_suspicious_targets
                or crawler.has_failed_targets
            )
        ):
            run_status = "suspicious"

        self.state.finish_run(
            run_id,
            status=run_status,
            finished_at=_utc_now(),
            discovered_url_count=discovered_url_count,
            new_url_count=new_url_count,
        )

    def _run_parse_phase(self, run_id: int) -> None:
        print("========== PHASE 3: PARSE ==========")

        try:
            if self.parse_service_factory is None:
                from joblake.parsing.service import ParseService

                service = ParseService(
                    config=self.config,
                    storage=self.storage,
                    state=self.state,
                )
            else:
                service = self.parse_service_factory(
                    config=self.config,
                    storage=self.storage,
                    state=self.state,
                )
            summary = service.run(run_id)
        except Exception as exc:
            self._finish_failed_run(
                run_id,
                status="failed",
                error=exc,
                discovered_url_count=0,
                new_url_count=0,
            )
            raise

        self.state.finish_run(
            run_id,
            status=(
                "suspicious"
                if summary.has_failures
                else "completed"
            ),
            finished_at=_utc_now(),
            discovered_url_count=0,
            new_url_count=0,
        )

    def _create_discovery_crawler(
        self,
        run_id: int,
    ) -> DiscoveryCrawler:
        return DiscoveryCrawler(
            config=self.config,
            source=self.source,
            storage=self.storage,
            fetcher_factory=self.fetcher_factory,
            state=self.state,
            run_id=run_id,
        )

    def _run_details(self, run_id: int) -> str:
        print("========== PHASE 2: DETAIL ==========")
        detail_config = self.config["detail"]
        state_config = self.config["state"]
        max_jobs = detail_config.get("max_jobs_per_run")
        max_attempts = int(
            state_config.get(
                "detail_max_attempts",
                3,
            )
        )

        if max_attempts < 1:
            raise ValueError(
                "state.detail_max_attempts must be at least 1"
            )

        processed = 0

        with self.fetcher_factory(
            detail_config
        ) as fetcher:
            while (
                max_jobs is None
                or processed < int(max_jobs)
            ):
                claim = self.state.claim_next_job(
                    run_id=run_id,
                    source=self.source.name,
                    now=_utc_now(),
                    max_attempts=max_attempts,
                )

                if claim is None:
                    break

                processed += 1
                print(
                    f"Detail {processed}"
                    + (
                        f"/{max_jobs}"
                        if max_jobs is not None
                        else ""
                    )
                    + f": {claim.record.url}"
                )

                if not self._crawl_detail(
                    fetcher=fetcher,
                    claim=claim,
                    max_attempts=max_attempts,
                ):
                    return "blocked"

                self._sleep(detail_config["delay"])

        print(f"Detail attempts this run: {processed}")
        return "completed"

    def _crawl_detail(
        self,
        *,
        fetcher,
        claim: JobClaim,
        max_attempts: int,
    ) -> bool:
        request = self.source.build_detail_request(
            claim.record
        )
        fetch_result = None
        validation = None

        try:
            fetch_result = fetcher.fetch(
                url=request.url,
                params=request.params,
                referer=request.referer,
            )
            self.state.mark_validating(claim)
            validation = self.source.validate_detail_html(
                fetch_result,
                claim.record.url,
            )

            if not validation.is_valid:
                self.state.fail_attempt(
                    claim=claim,
                    attempt_status="invalid_response",
                    completed_at=_utc_now(),
                    error_type="RawValidationError",
                    error_message=", ".join(
                        validation.errors
                    ),
                    max_attempts=max_attempts,
                    next_retry_at=self._next_retry_at(),
                    fetch_result=fetch_result,
                    validation=validation,
                )
                print(
                    "Detail raw validation failed: "
                    + ", ".join(validation.errors)
                )
                return True

            payload = self.storage.prepare_detail(
                discovery_record=claim.record,
                fetch_result=fetch_result,
            )
            self.state.mark_uploading(
                claim=claim,
                payload=payload,
                fetch_result=fetch_result,
                validation=validation,
            )
            stored = self.storage.save_prepared_detail(
                payload
            )

            if (
                stored.content_length_bytes
                != payload.content_length_bytes
                or stored.content_sha256
                != payload.content_sha256
            ):
                raise StorageIntegrityError(
                    "Stored object does not match payload"
                )

            self.state.complete_upload(
                claim=claim,
                stored=stored,
                fetch_result=fetch_result,
                validation=validation,
                completed_at=_utc_now(),
            )

            print(
                "Raw detail ready: "
                f"{stored.locator.bucket_name}/"
                f"{stored.locator.object_key}"
            )

        except SourceBlockedError as exc:
            self.state.fail_attempt(
                claim=claim,
                attempt_status="blocked",
                completed_at=_utc_now(),
                error_type=type(exc).__name__,
                error_message=str(exc),
                max_attempts=max_attempts,
                next_retry_at=self._next_retry_at(),
            )
            print(f"Detail crawling blocked: {exc}")
            return False

        except FetchError as exc:
            self.state.fail_attempt(
                claim=claim,
                attempt_status="fetch_error",
                completed_at=_utc_now(),
                error_type=type(exc).__name__,
                error_message=str(exc),
                max_attempts=max_attempts,
                next_retry_at=self._next_retry_at(),
            )
            print(
                "Detail failed, will retry according "
                f"to state policy: {exc}"
            )

        except Exception as exc:
            self.state.fail_attempt(
                claim=claim,
                attempt_status="storage_error",
                completed_at=_utc_now(),
                error_type=type(exc).__name__,
                error_message=str(exc),
                max_attempts=max_attempts,
                next_retry_at=self._next_retry_at(),
                fetch_result=fetch_result,
                validation=validation,
            )
            print(
                "Detail processing failed, will retry "
                f"according to state policy: {exc}"
            )

        return True

    def _recover_interrupted_work(self) -> None:
        now = _utc_now()

        for pending in self.state.load_pending_uploads(
            self.source.name
        ):
            stored = self.storage.stat_object(
                pending.locator,
                expected_sha256=(
                    pending.expected_sha256
                ),
            )

            if (
                stored is not None
                and stored.content_length_bytes
                == pending.expected_size
            ):
                self.state.complete_recovered_upload(
                    pending,
                    stored,
                    now,
                )
                print(
                    "Recovered completed upload: "
                    f"{pending.locator.object_key}"
                )
            else:
                self.state.fail_recovered_upload(
                    pending,
                    completed_at=now,
                    next_retry_at=self._next_retry_at(),
                    error_message=(
                        "Object missing or size mismatch "
                        "during upload recovery"
                    ),
                )

        self.state.recover_stale_fetches(
            self.source.name,
            now,
        )
        self._audit_raw_objects(now)

    def _audit_raw_objects(
        self,
        checked_at: str,
    ) -> None:
        state_config = self.config["state"]

        if not state_config.get(
            "integrity_check_on_start",
            False,
        ):
            return

        limit = int(
            state_config.get(
                "integrity_check_limit",
                100,
            )
        )

        if limit < 1:
            return

        checks = (
            self.state.load_raw_objects_for_integrity(
                self.source.name,
                limit,
            )
        )
        failed_count = 0

        for check in checks:
            stored = self.storage.stat_object(
                check.locator,
                expected_sha256=(
                    check.expected_sha256
                ),
            )

            if stored is None:
                status = "missing"
            elif (
                stored.content_length_bytes
                != check.expected_size
            ):
                status = "size_mismatch"
            else:
                status = "valid"

            if status != "valid":
                failed_count += 1

            self.state.update_raw_integrity(
                check,
                status=status,
                checked_at=checked_at,
            )

        if checks:
            print(
                "Raw integrity audit: "
                f"checked={len(checks)}, "
                f"failed={failed_count}"
            )

    def _next_retry_at(self) -> str:
        retry_delay_seconds = int(
            self.config["state"].get(
                "detail_retry_delay_seconds",
                3600,
            )
        )
        return (
            datetime.now(timezone.utc)
            + timedelta(seconds=retry_delay_seconds)
        ).isoformat()

    def _finish_failed_run(
        self,
        run_id: int,
        *,
        status: str,
        error: Exception,
        discovered_url_count: int,
        new_url_count: int,
    ) -> None:
        self.state.finish_run(
            run_id,
            status=status,
            finished_at=_utc_now(),
            discovered_url_count=(
                discovered_url_count
            ),
            new_url_count=new_url_count,
            error_type=type(error).__name__,
            error_message=str(error),
        )

    @staticmethod
    def _sleep(delay: dict) -> None:
        time.sleep(
            random.uniform(
                delay["min_seconds"],
                delay["max_seconds"],
            )
        )


def run_pipeline(
    config_path: str,
    phase: str = "full",
) -> None:
    from joblake.config import load_config

    IngestionPipeline(
        load_config(config_path)
    ).run(phase=phase)
