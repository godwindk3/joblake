"""PostgreSQL crawl state. Schema changes are managed by Alembic."""
import json
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime

import psycopg
from joblake.cdc import PostgresCdcMixin

from joblake.postgres import PostgresSettings
from joblake.models import DiscoveryRecord, FetchResult, ValidationResult
from joblake.storage import ObjectLocator, RawObjectPayload, StoredObject
from joblake.state import JobClaim, PendingUpload, RawObjectCheck, ParseClaim, _require_parse_transition


def _state_row(cursor):
    names = [column.name for column in cursor.description or ()]
    def make_row(values):
        return {name: value.isoformat() if isinstance(value, datetime) else value
                for name, value in zip(names, values)}
    return make_row


class PostgresStateStore(PostgresCdcMixin):
    def __init__(self, settings):
        self.settings = replace(settings, application_name="joblake-state")
        self._run_connection = None
        self._run_source = None

    @classmethod
    def from_config(cls, config):
        return cls(PostgresSettings.from_config(config))

    def _open_connection(self):
        if self._run_connection is not None:
            self._run_connection.execute("SELECT 1")
        return psycopg.connect(**self.settings.connection_kwargs(), row_factory=_state_row,
                               options="-c timezone=UTC -c lock_timeout=10000 -c statement_timeout=60000")

    @contextmanager
    def _connect(self):
        if self._run_connection is not None:
            # If the lock session is lost, abort rather than write without ownership.
            self._run_connection.execute("SELECT 1")
        with self._open_connection() as connection:
            yield connection

    @contextmanager
    def source_run(self, source):
        # A dedicated session owns the lock for recovery and the entire phase.
        # Worker parallelism within a source requires leases and is intentionally disabled.
        if self._run_connection is not None:
            raise RuntimeError("This state store already owns a source run")
        with self._open_connection() as connection:
            connection.autocommit = True
            acquired = connection.execute(
                "SELECT pg_try_advisory_lock(hashtextextended(%s, 0)) AS acquired",
                ("joblake-state:" + source,),
            ).fetchone()["acquired"]
            if not acquired:
                raise RuntimeError(f"Another JobLake phase is running for source={source}")
            self._run_connection = connection
            self._run_source = source
            try:
                yield
            finally:
                self._run_connection = None
                self._run_source = None
                connection.execute("SELECT pg_advisory_unlock(hashtextextended(%s, 0))",
                                   ("joblake-state:" + source,))

    def start_run(
        self,
        source: str,
        started_at: str,
    ) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO crawl_state.crawl_runs (
                    source,
                    status,
                    started_at
                )
                VALUES (%s, 'running', %s)
                RETURNING id
                """,
                (source, started_at),
            )
            return int(cursor.fetchone()["id"])

    def finish_run(
        self,
        run_id: int,
        *,
        status: str,
        finished_at: str,
        discovered_url_count: int,
        new_url_count: int,
        error_type: str | None = None,
        error_message: str | None = None,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE crawl_state.crawl_runs
                SET
                    status = %s,
                    finished_at = %s,
                    discovered_url_count = %s,
                    new_url_count = %s,
                    error_type = %s,
                    error_message = %s,
                    cdc_reason = CASE WHEN cdc_status='pending' THEN 'discovery_not_finalized' ELSE cdc_reason END,
                    cdc_finished_at = CASE WHEN cdc_status='pending' THEN CURRENT_TIMESTAMP ELSE cdc_finished_at END,
                    cdc_status = CASE WHEN cdc_status='pending' THEN 'skipped' ELSE cdc_status END
                WHERE id = %s
                """,
                (
                    status,
                    finished_at,
                    discovered_url_count,
                    new_url_count,
                    error_type,
                    error_message,
                    run_id,
                ),
            )

    def start_discovery_target(
        self,
        *,
        run_id: int,
        source: str,
        target_name: str,
        started_at: str,
    ) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO crawl_state.discovery_targets (
                    run_id,
                    source,
                    target_name,
                    status,
                    started_at
                )
                VALUES (%s, %s, %s, 'running', %s)
                RETURNING id
                """,
                (
                    run_id,
                    source,
                    target_name,
                    started_at,
                ),
            )
            return int(cursor.fetchone()["id"])

    def finish_discovery_target(
        self,
        target_id: int,
        *,
        status: str,
        finished_at: str,
        detected_last_page: int | None,
        fetched_page_count: int,
        discovered_url_count: int,
        new_url_count: int,
        duplicate_url_count: int,
        empty_page_count: int,
        invalid_page_count: int = 0,
        error_type: str | None = None,
        error_message: str | None = None,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE crawl_state.discovery_targets
                SET
                    status = %s,
                    detected_last_page = %s,
                    fetched_page_count = %s,
                    discovered_url_count = %s,
                    new_url_count = %s,
                    duplicate_url_count = %s,
                    empty_page_count = %s,
                    invalid_page_count = %s,
                    finished_at = %s,
                    error_type = %s,
                    error_message = %s
                WHERE id = %s
                """,
                (
                    status,
                    detected_last_page,
                    fetched_page_count,
                    discovered_url_count,
                    new_url_count,
                    duplicate_url_count,
                    empty_page_count,
                    invalid_page_count,
                    finished_at,
                    error_type,
                    error_message,
                    target_id,
                ),
            )

    def upsert_discovered_jobs(
        self,
        records: list[DiscoveryRecord],
        run_id: int,
    ) -> int:
        new_count = 0

        with self._connect() as connection:
            for record in records:
                inserted = connection.execute(
                    """
                    INSERT INTO crawl_state.jobs
                        (source, url, first_seen_at, last_seen_at, last_seen_run_id,
                         last_target_name, last_listing_url, last_listing_page)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (source, url) DO NOTHING
                    RETURNING id
                    """,
                    (record.source, record.url, record.discovered_at, record.discovered_at,
                     run_id, record.target_name, record.listing_url, record.listing_page),
                ).fetchone()

                if inserted is not None:
                    new_count += 1
                else:
                    connection.execute(
                        """
                        UPDATE crawl_state.jobs
                        SET
                            last_seen_at = %s,
                            last_seen_run_id = %s,
                            last_target_name = %s,
                            last_listing_url = %s,
                            last_listing_page = %s,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE source = %s AND url = %s
                        """,
                        (
                            record.discovered_at,
                            run_id,
                            record.target_name,
                            record.listing_url,
                            record.listing_page,
                            record.source,
                            record.url,
                        ),
                    )

            # Any newly observed purged job needs a fresh raw generation, even
            # when discovery coverage is incomplete and CDC cannot finalize.
            connection.execute("""UPDATE crawl_state.jobs j
                SET raw_status='pending', fetch_retry_base=fetch_attempt_count,
                    next_retry_at=NULL, last_error_type=NULL, last_error_message=NULL
                FROM crawl_state.raw_objects r
                WHERE r.job_id=j.id AND r.purged_at IS NOT NULL
                  AND j.last_seen_run_id=%s AND j.raw_status='storage_missing'""", (run_id,))

        return new_count

    def claim_next_job(
        self,
        *,
        run_id: int,
        source: str,
        now: str,
        max_attempts: int,
    ) -> JobClaim | None:
        connection = self._open_connection()

        try:
            connection.execute("BEGIN")
            row = connection.execute(
                """
                SELECT *
                FROM crawl_state.jobs
                WHERE source = %s
                  AND raw_status IN (
                      'pending',
                      'retryable_error',
                      'blocked'
                  )
                  AND fetch_attempt_count - fetch_retry_base < %s
                  AND (
                      next_retry_at IS NULL
                      OR next_retry_at <= %s
                  )
                ORDER BY first_seen_at, id
                LIMIT 1
                FOR UPDATE SKIP LOCKED
                """,
                (source, max_attempts, now),
            ).fetchone()

            if row is None:
                connection.commit()
                return None

            attempt_number = (
                int(row["fetch_attempt_count"]) + 1
            )
            connection.execute(
                """
                UPDATE crawl_state.jobs
                SET
                    raw_status = 'fetching',
                    fetch_attempt_count = %s,
                    last_attempt_at = %s,
                    next_retry_at = NULL,
                    last_error_type = NULL,
                    last_error_message = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                """,
                (
                    attempt_number,
                    now,
                    row["id"],
                ),
            )
            cursor = connection.execute(
                """
                INSERT INTO crawl_state.fetch_attempts (
                    run_id,
                    job_id,
                    attempt_number,
                    status,
                    started_at,
                    requested_url
                )
                VALUES (%s, %s, %s, 'fetching', %s, %s)
                RETURNING id
                """,
                (
                    run_id,
                    row["id"],
                    attempt_number,
                    now,
                    row["url"],
                ),
            )
            connection.commit()

            return JobClaim(
                job_id=int(row["id"]),
                attempt_id=int(cursor.fetchone()["id"]),
                attempt_number=attempt_number,
                record=DiscoveryRecord(
                    source=row["source"],
                    url=row["url"],
                    target_name=(
                        row["last_target_name"] or ""
                    ),
                    listing_url=(
                        row["last_listing_url"]
                        or row["url"]
                    ),
                    listing_page=(
                        row["last_listing_page"] or 1
                    ),
                    discovered_at=row["last_seen_at"],
                ),
            )
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def mark_validating(
        self,
        claim: JobClaim,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE crawl_state.jobs
                SET
                    raw_status = 'validating',
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                """,
                (claim.job_id,),
            )

    def mark_uploading(
        self,
        *,
        claim: JobClaim,
        payload: RawObjectPayload,
        fetch_result: FetchResult,
        validation: ValidationResult,
    ) -> None:
        validation_report = json.dumps(
            validation.as_dict(),
            ensure_ascii=False,
        )

        with self._connect() as connection:
            connection.execute(
                """
                UPDATE crawl_state.fetch_attempts
                SET
                    status = 'uploading',
                    requested_url = %s,
                    final_url = %s,
                    http_status = %s,
                    content_type = %s,
                    content_length_bytes = %s,
                    content_sha256 = %s,
                    validation_version = %s,
                    validation_report = %s,
                    storage_provider = %s,
                    bucket_name = %s,
                    object_key = %s,
                    object_version = %s,
                    fetched_at = %s
                WHERE id = %s
                """,
                (
                    fetch_result.requested_url,
                    fetch_result.final_url,
                    fetch_result.status_code,
                    fetch_result.content_type,
                    payload.content_length_bytes,
                    payload.content_sha256,
                    validation.validation_version,
                    validation_report,
                    payload.locator.provider,
                    payload.locator.bucket_name,
                    payload.locator.object_key,
                    payload.locator.object_version,
                    fetch_result.fetched_at,
                    claim.attempt_id,
                ),
            )
            connection.execute(
                """
                UPDATE crawl_state.jobs
                SET
                    raw_status = 'uploading',
                    last_http_status = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                """,
                (
                    fetch_result.status_code,
                    claim.job_id,
                ),
            )

    def complete_upload(
        self,
        *,
        claim: JobClaim,
        stored: StoredObject,
        fetch_result: FetchResult,
        validation: ValidationResult,
        completed_at: str,
    ) -> None:
        report = json.dumps(
            validation.as_dict(),
            ensure_ascii=False,
        )

        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO crawl_state.raw_objects (
                    job_id,
                    storage_provider,
                    bucket_name,
                    object_key,
                    object_version,
                    requested_url,
                    final_url,
                    http_status,
                    content_type,
                    content_length_bytes,
                    content_sha256,
                    fetched_at,
                    stored_at,
                    validation_version,
                    validation_report,
                    last_integrity_check_at,
                    integrity_status
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, 'valid'
                )
                ON CONFLICT (job_id) DO UPDATE SET
                    storage_provider=EXCLUDED.storage_provider,
                    bucket_name=EXCLUDED.bucket_name,
                    object_key=EXCLUDED.object_key,
                    object_version=EXCLUDED.object_version,
                    requested_url=EXCLUDED.requested_url,
                    final_url=EXCLUDED.final_url,
                    http_status=EXCLUDED.http_status,
                    content_type=EXCLUDED.content_type,
                    content_length_bytes=EXCLUDED.content_length_bytes,
                    content_sha256=EXCLUDED.content_sha256,
                    fetched_at=EXCLUDED.fetched_at,
                    stored_at=EXCLUDED.stored_at,
                    validation_version=EXCLUDED.validation_version,
                    validation_report=EXCLUDED.validation_report,
                    last_integrity_check_at=EXCLUDED.last_integrity_check_at,
                    integrity_status=EXCLUDED.integrity_status,
                    purged_at=NULL, refreshed_at=CURRENT_TIMESTAMP
                WHERE crawl_state.raw_objects.purged_at IS NOT NULL
                   OR crawl_state.raw_objects.content_sha256 <> EXCLUDED.content_sha256
                """,
                (
                    claim.job_id,
                    stored.locator.provider,
                    stored.locator.bucket_name,
                    stored.locator.object_key,
                    stored.locator.object_version,
                    fetch_result.requested_url,
                    fetch_result.final_url,
                    fetch_result.status_code,
                    fetch_result.content_type,
                    stored.content_length_bytes,
                    stored.content_sha256,
                    fetch_result.fetched_at,
                    stored.stored_at,
                    validation.validation_version,
                    report,
                    completed_at,
                ),
            )
            connection.execute(
                """
                UPDATE crawl_state.fetch_attempts
                SET
                    status = 'success',
                    object_version = %s,
                    completed_at = %s
                WHERE id = %s
                """,
                (
                    stored.locator.object_version,
                    completed_at,
                    claim.attempt_id,
                ),
            )
            connection.execute(
                """
                UPDATE crawl_state.jobs
                SET
                    raw_status = 'raw_ready',
                    next_retry_at = NULL,
                    last_error_type = NULL,
                    last_error_message = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                """,
                (claim.job_id,),
            )

    def fail_attempt(
        self,
        *,
        claim: JobClaim,
        attempt_status: str,
        completed_at: str,
        error_type: str,
        error_message: str,
        max_attempts: int,
        next_retry_at: str | None,
        retryable: bool = True,
        fetch_result: FetchResult | None = None,
        validation: ValidationResult | None = None,
    ) -> None:
        with self._connect() as connection:
            retry_base = connection.execute(
                "SELECT fetch_retry_base FROM crawl_state.jobs WHERE id=%s", (claim.job_id,)
            ).fetchone()["fetch_retry_base"]
        if attempt_status == "blocked":
            job_status = "blocked"
        elif (
            not retryable
            or claim.attempt_number - retry_base >= max_attempts
        ):
            job_status = "permanent_error"
            next_retry_at = None
        else:
            job_status = "retryable_error"

        validation_report = (
            json.dumps(
                validation.as_dict(),
                ensure_ascii=False,
            )
            if validation is not None
            else None
        )

        with self._connect() as connection:
            connection.execute(
                """
                UPDATE crawl_state.fetch_attempts
                SET
                    status = %s,
                    completed_at = %s,
                    final_url = COALESCE(%s, final_url),
                    http_status = COALESCE(%s, http_status),
                    content_type = COALESCE(%s, content_type),
                    validation_version = COALESCE(
                        %s,
                        validation_version
                    ),
                    validation_report = COALESCE(
                        %s,
                        validation_report
                    ),
                    error_type = %s,
                    error_message = %s
                WHERE id = %s
                """,
                (
                    attempt_status,
                    completed_at,
                    (
                        fetch_result.final_url
                        if fetch_result
                        else None
                    ),
                    (
                        fetch_result.status_code
                        if fetch_result
                        else None
                    ),
                    (
                        fetch_result.content_type
                        if fetch_result
                        else None
                    ),
                    (
                        validation.validation_version
                        if validation
                        else None
                    ),
                    validation_report,
                    error_type,
                    error_message,
                    claim.attempt_id,
                ),
            )
            connection.execute(
                """
                UPDATE crawl_state.jobs
                SET
                    raw_status = %s,
                    next_retry_at = %s,
                    last_http_status = COALESCE(
                        %s,
                        last_http_status
                    ),
                    last_error_type = %s,
                    last_error_message = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                """,
                (
                    job_status,
                    next_retry_at,
                    (
                        fetch_result.status_code
                        if fetch_result
                        else None
                    ),
                    error_type,
                    error_message,
                    claim.job_id,
                ),
            )

    def load_pending_uploads(
        self,
        source: str,
    ) -> list[PendingUpload]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    a.id AS attempt_id,
                    a.job_id,
                    a.storage_provider,
                    a.bucket_name,
                    a.object_key,
                    a.object_version,
                    a.content_length_bytes,
                    a.content_sha256
                FROM crawl_state.fetch_attempts AS a
                JOIN crawl_state.jobs AS j ON j.id = a.job_id
                WHERE j.source = %s
                  AND a.status = 'uploading'
                  AND a.bucket_name IS NOT NULL
                  AND a.object_key IS NOT NULL
                """,
                (source,),
            ).fetchall()

        return [
            PendingUpload(
                job_id=int(row["job_id"]),
                attempt_id=int(row["attempt_id"]),
                locator=ObjectLocator(
                    provider=row["storage_provider"],
                    bucket_name=row["bucket_name"],
                    object_key=row["object_key"],
                    object_version=row["object_version"],
                ),
                expected_size=int(
                    row["content_length_bytes"]
                ),
                expected_sha256=row["content_sha256"],
            )
            for row in rows
        ]

    def complete_recovered_upload(
        self,
        pending: PendingUpload,
        stored: StoredObject,
        completed_at: str,
    ) -> None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM crawl_state.fetch_attempts
                WHERE id = %s
                """,
                (pending.attempt_id,),
            ).fetchone()

            if row is None:
                return

            connection.execute(
                """
                INSERT INTO crawl_state.raw_objects (
                    job_id,
                    storage_provider,
                    bucket_name,
                    object_key,
                    object_version,
                    requested_url,
                    final_url,
                    http_status,
                    content_type,
                    content_length_bytes,
                    content_sha256,
                    fetched_at,
                    stored_at,
                    validation_version,
                    validation_report,
                    last_integrity_check_at,
                    integrity_status
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, 'valid'
                )
                ON CONFLICT (job_id) DO UPDATE SET
                    storage_provider=EXCLUDED.storage_provider,
                    bucket_name=EXCLUDED.bucket_name,
                    object_key=EXCLUDED.object_key,
                    object_version=EXCLUDED.object_version,
                    requested_url=EXCLUDED.requested_url,
                    final_url=EXCLUDED.final_url,
                    http_status=EXCLUDED.http_status,
                    content_type=EXCLUDED.content_type,
                    content_length_bytes=EXCLUDED.content_length_bytes,
                    content_sha256=EXCLUDED.content_sha256,
                    fetched_at=EXCLUDED.fetched_at,
                    stored_at=EXCLUDED.stored_at,
                    validation_version=EXCLUDED.validation_version,
                    validation_report=EXCLUDED.validation_report,
                    last_integrity_check_at=EXCLUDED.last_integrity_check_at,
                    integrity_status=EXCLUDED.integrity_status,
                    purged_at=NULL, refreshed_at=CURRENT_TIMESTAMP
                WHERE crawl_state.raw_objects.purged_at IS NOT NULL
                   OR crawl_state.raw_objects.content_sha256 <> EXCLUDED.content_sha256
                """,
                (
                    pending.job_id,
                    stored.locator.provider,
                    stored.locator.bucket_name,
                    stored.locator.object_key,
                    stored.locator.object_version,
                    row["requested_url"],
                    row["final_url"],
                    row["http_status"],
                    row["content_type"],
                    stored.content_length_bytes,
                    stored.content_sha256,
                    row["fetched_at"],
                    stored.stored_at,
                    row["validation_version"],
                    row["validation_report"],
                    completed_at,
                ),
            )
            connection.execute(
                """
                UPDATE crawl_state.fetch_attempts
                SET
                    status = 'success',
                    object_version = %s,
                    completed_at = %s
                WHERE id = %s
                """,
                (
                    stored.locator.object_version,
                    completed_at,
                    pending.attempt_id,
                ),
            )
            connection.execute(
                """
                UPDATE crawl_state.jobs
                SET
                    raw_status = 'raw_ready',
                    next_retry_at = NULL,
                    last_error_type = NULL,
                    last_error_message = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                """,
                (pending.job_id,),
            )

    def fail_recovered_upload(
        self,
        pending: PendingUpload,
        *,
        completed_at: str,
        next_retry_at: str,
        error_message: str,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE crawl_state.fetch_attempts
                SET
                    status = 'storage_error',
                    completed_at = %s,
                    error_type = 'UploadRecoveryError',
                    error_message = %s
                WHERE id = %s
                """,
                (
                    completed_at,
                    error_message,
                    pending.attempt_id,
                ),
            )
            connection.execute(
                """
                UPDATE crawl_state.jobs
                SET
                    raw_status = 'retryable_error',
                    next_retry_at = %s,
                    last_error_type = 'UploadRecoveryError',
                    last_error_message = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                """,
                (
                    next_retry_at,
                    error_message,
                    pending.job_id,
                ),
            )

    def recover_stale_fetches(
        self,
        source: str,
        recovered_at: str,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE crawl_state.fetch_attempts
                SET
                    status = 'fetch_error',
                    completed_at = %s,
                    error_type = 'InterruptedRun',
                    error_message = 'Recovered unfinished fetch from a previous process'
                WHERE status = 'fetching'
                  AND job_id IN (
                      SELECT id FROM crawl_state.jobs WHERE source = %s
                  )
                """,
                (recovered_at, source),
            )
            connection.execute(
                """
                UPDATE crawl_state.jobs
                SET
                    raw_status = 'retryable_error',
                    next_retry_at = NULL,
                    last_error_type = 'InterruptedRun',
                    last_error_message = 'Recovered unfinished fetch from a previous process',
                    updated_at = CURRENT_TIMESTAMP
                WHERE source = %s
                  AND raw_status IN (
                      'fetching',
                      'validating'
                  )
                """,
                (source,),
            )

    def load_raw_objects_for_integrity(
        self,
        source: str,
        limit: int,
    ) -> list[RawObjectCheck]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    r.id AS raw_object_id,
                    r.job_id,
                    r.storage_provider,
                    r.bucket_name,
                    r.object_key,
                    r.object_version,
                    r.content_length_bytes,
                    r.content_sha256
                FROM crawl_state.raw_objects AS r
                JOIN crawl_state.jobs AS j ON j.id = r.job_id
                WHERE j.source = %s AND r.purged_at IS NULL
                ORDER BY
                    r.last_integrity_check_at IS NOT NULL,
                    r.last_integrity_check_at,
                    r.id
                LIMIT %s
                """,
                (source, limit),
            ).fetchall()

        return [
            RawObjectCheck(
                raw_object_id=int(
                    row["raw_object_id"]
                ),
                job_id=int(row["job_id"]),
                locator=ObjectLocator(
                    provider=row["storage_provider"],
                    bucket_name=row["bucket_name"],
                    object_key=row["object_key"],
                    object_version=row["object_version"],
                ),
                expected_size=int(
                    row["content_length_bytes"]
                ),
                expected_sha256=row["content_sha256"],
            )
            for row in rows
        ]

    def update_raw_integrity(
        self,
        check: RawObjectCheck,
        *,
        status: str,
        checked_at: str,
    ) -> None:
        if status == "valid":
            job_status = "raw_ready"
        elif status == "missing":
            job_status = "storage_missing"
        else:
            job_status = "storage_corrupt"

        with self._connect() as connection:
            connection.execute(
                """
                UPDATE crawl_state.raw_objects
                SET
                    integrity_status = %s,
                    last_integrity_check_at = %s
                WHERE id = %s
                """,
                (
                    status,
                    checked_at,
                    check.raw_object_id,
                ),
            )
            connection.execute(
                """
                UPDATE crawl_state.jobs
                SET
                    raw_status = %s,
                    last_error_type = %s,
                    last_error_message = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                """,
                (
                    job_status,
                    (
                        None
                        if status == "valid"
                        else "StorageIntegrityError"
                    ),
                    (
                        None
                        if status == "valid"
                        else (
                            "Raw object integrity status: "
                            f"{status}"
                        )
                    ),
                    check.job_id,
                ),
            )

    def claim_next_raw_for_parse(
        self,
        *,
        run_id: int,
        source: str,
        parser_name: str,
        parser_version: str,
        started_at: str,
        max_attempts: int,
    ) -> ParseClaim | None:
        if max_attempts < 1:
            raise ValueError("parse max_attempts must be at least 1")

        connection = self._open_connection()

        try:
            connection.execute("BEGIN")
            row = connection.execute(
                """
                SELECT
                    j.id AS job_id,
                    j.source,
                    j.url,
                    j.first_seen_at,
                    j.last_seen_at,
                    r.id AS raw_object_id,
                    r.storage_provider,
                    r.bucket_name,
                    r.object_key,
                    r.object_version,
                    r.content_length_bytes,
                    r.content_sha256,
                    r.fetched_at,
                    COALESCE(p.attempt_count, 0) AS attempt_count
                FROM crawl_state.jobs AS j
                JOIN crawl_state.raw_objects AS r ON r.job_id = j.id
                LEFT JOIN (
                    SELECT
                        raw_object_id,
                        COUNT(*) AS attempt_count,
                        MAX(CASE
                            WHEN status IN (
                                'success',
                                'validation_error',
                                'raw_missing',
                                'raw_corrupt'
                            ) THEN 1 ELSE 0
                        END) AS is_terminal,
                        MAX(CASE
                            WHEN status = 'parsing'
                            THEN 1 ELSE 0
                        END) AS is_active,
                        MAX(CASE
                            WHEN run_id = %s
                            THEN 1 ELSE 0
                        END) AS attempted_this_run
                    FROM crawl_state.parse_attempts
                    WHERE (SELECT refreshed_at IS NULL OR started_at >= refreshed_at
                           FROM crawl_state.raw_objects WHERE id=raw_object_id)
                      AND parser_name = %s
                      AND parser_version = %s
                    GROUP BY raw_object_id
                ) AS p ON p.raw_object_id = r.id
                WHERE j.source = %s
                  AND j.raw_status = 'raw_ready'
                  AND r.integrity_status = 'valid'
                  AND COALESCE(p.is_terminal, 0) = 0
                  AND COALESCE(p.is_active, 0) = 0
                  AND COALESCE(p.attempted_this_run, 0) = 0
                  AND COALESCE(p.attempt_count, 0) < %s
                ORDER BY j.first_seen_at, j.id
                LIMIT 1
                FOR UPDATE OF j SKIP LOCKED
                """,
                (
                    run_id,
                    parser_name,
                    parser_version,
                    source,
                    max_attempts,
                ),
            ).fetchone()

            if row is None:
                connection.commit()
                return None

            attempt_number = connection.execute(
                """SELECT COALESCE(MAX(attempt_number),0)+1 AS next_attempt
                   FROM crawl_state.parse_attempts
                   WHERE raw_object_id=%s AND parser_name=%s AND parser_version=%s""",
                (row["raw_object_id"], parser_name, parser_version),
            ).fetchone()["next_attempt"]
            cursor = connection.execute(
                """
                INSERT INTO crawl_state.parse_attempts (
                    run_id,
                    job_id,
                    raw_object_id,
                    parser_name,
                    parser_version,
                    attempt_number,
                    status,
                    started_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, 'parsing', %s)
                RETURNING id
                """,
                (
                    run_id,
                    row["job_id"],
                    row["raw_object_id"],
                    parser_name,
                    parser_version,
                    attempt_number,
                    started_at,
                ),
            )
            connection.commit()

            return ParseClaim(
                run_id=run_id,
                job_id=int(row["job_id"]),
                raw_object_id=int(row["raw_object_id"]),
                attempt_id=int(cursor.fetchone()["id"]),
                attempt_number=attempt_number,
                source=row["source"],
                canonical_url=row["url"],
                first_seen_at=row["first_seen_at"],
                last_seen_at=row["last_seen_at"],
                fetched_at=row["fetched_at"],
                locator=ObjectLocator(
                    provider=row["storage_provider"],
                    bucket_name=row["bucket_name"],
                    object_key=row["object_key"],
                    object_version=row["object_version"],
                ),
                expected_size=int(row["content_length_bytes"]),
                expected_sha256=row["content_sha256"],
            )
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def complete_parse(
        self,
        claim: ParseClaim,
        *,
        completed_at: str,
        parsed_field_count: int,
        missing_required_fields: list[str],
        warnings: list[dict],
        output_location: str,
    ) -> None:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE crawl_state.parse_attempts
                SET
                    status = 'success',
                    completed_at = %s,
                    parsed_field_count = %s,
                    missing_required_fields = %s,
                    warnings = %s,
                    output_location = %s,
                    error_type = NULL,
                    error_message = NULL
                WHERE id = %s
                  AND run_id = %s
                  AND status = 'parsing'
                """,
                (
                    completed_at,
                    parsed_field_count,
                    json.dumps(
                        missing_required_fields,
                        ensure_ascii=False,
                    ),
                    json.dumps(warnings, ensure_ascii=False),
                    output_location,
                    claim.attempt_id,
                    claim.run_id,
                ),
            )
            _require_parse_transition(cursor, claim)

    def fail_parse(
        self,
        claim: ParseClaim,
        *,
        status: str,
        completed_at: str,
        error_type: str,
        error_message: str,
        missing_required_fields: list[str] | None = None,
        warnings: list[dict] | None = None,
        integrity_status: str | None = None,
    ) -> None:
        allowed_statuses = {
            "parse_error",
            "validation_error",
            "raw_missing",
            "raw_corrupt",
        }
        if status not in allowed_statuses:
            raise ValueError(f"Unsupported parse failure status: {status}")

        if status == "raw_missing":
            integrity_status = "missing"
        elif status == "raw_corrupt" and integrity_status not in {
            "size_mismatch",
            "hash_mismatch",
        }:
            integrity_status = "hash_mismatch"

        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE crawl_state.parse_attempts
                SET
                    status = %s,
                    completed_at = %s,
                    missing_required_fields = %s,
                    warnings = %s,
                    error_type = %s,
                    error_message = %s
                WHERE id = %s
                  AND run_id = %s
                  AND status = 'parsing'
                """,
                (
                    status,
                    completed_at,
                    json.dumps(
                        missing_required_fields or [],
                        ensure_ascii=False,
                    ),
                    json.dumps(
                        warnings or [],
                        ensure_ascii=False,
                    ),
                    error_type,
                    error_message,
                    claim.attempt_id,
                    claim.run_id,
                ),
            )
            _require_parse_transition(cursor, claim)

            if integrity_status is not None:
                job_status = (
                    "storage_missing"
                    if integrity_status == "missing"
                    else "storage_corrupt"
                )
                connection.execute(
                    """
                    UPDATE crawl_state.raw_objects
                    SET
                        integrity_status = %s,
                        last_integrity_check_at = %s
                    WHERE id = %s
                    """,
                    (
                        integrity_status,
                        completed_at,
                        claim.raw_object_id,
                    ),
                )
                connection.execute(
                    """
                    UPDATE crawl_state.jobs
                    SET
                        raw_status = %s,
                        last_error_type = %s,
                        last_error_message = %s,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                    """,
                    (
                        job_status,
                        error_type,
                        error_message,
                        claim.job_id,
                    ),
                )

    def recover_stale_parses(
        self,
        source: str,
        recovered_at: str,
        stale_before: str,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE crawl_state.parse_attempts
                SET
                    status = 'parse_error',
                    completed_at = %s,
                    error_type = 'InterruptedRun',
                    error_message = 'Recovered unfinished parse from a previous process'
                WHERE status = 'parsing'
                  AND started_at <= %s
                  AND job_id IN (
                      SELECT id FROM crawl_state.jobs WHERE source = %s
                  )
                """,
                (recovered_at, stale_before, source),
            )

    def count_exhausted_parses(
        self,
        *,
        source: str,
        parser_name: str,
        parser_version: str,
        max_attempts: int,
    ) -> int:
        if max_attempts < 1:
            raise ValueError("parse max_attempts must be at least 1")

        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS exhausted_count
                FROM (
                    SELECT r.id
                    FROM crawl_state.jobs AS j
                    JOIN crawl_state.raw_objects AS r ON r.job_id = j.id
                    LEFT JOIN crawl_state.parse_attempts AS p
                      ON p.raw_object_id = r.id
                     AND p.parser_name = %s
                     AND p.parser_version = %s
                     AND (r.refreshed_at IS NULL OR p.started_at >= r.refreshed_at)
                    WHERE j.source = %s
                      AND j.raw_status = 'raw_ready'
                      AND r.integrity_status = 'valid'
                    GROUP BY r.id
                    HAVING MAX(CASE
                        WHEN p.status IN (
                            'success',
                            'validation_error',
                            'raw_missing',
                            'raw_corrupt'
                        ) THEN 1 ELSE 0
                    END) = 0
                    AND MAX(CASE
                        WHEN p.status = 'parsing' THEN 1 ELSE 0
                    END) = 0
                    AND COUNT(p.id) >= %s
                ) AS exhausted
                """,
                (
                    parser_name,
                    parser_version,
                    source,
                    max_attempts,
                ),
            ).fetchone()
        return int(row["exhausted_count"])

    def load_crawled_urls(self) -> set[str]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT url
                FROM crawl_state.jobs
                WHERE raw_status = 'raw_ready'
                """
            ).fetchall()

        return {row["url"] for row in rows}
