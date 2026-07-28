import json
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterator, Protocol

from joblake.models import (
    DiscoveryRecord,
    FetchResult,
    ValidationResult,
)
from joblake.storage import (
    ObjectLocator,
    RawObjectPayload,
    StoredObject,
)


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS crawl_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN (
            'running', 'completed', 'failed',
            'blocked', 'suspicious'
        )
    ),
    started_at TEXT NOT NULL,
    finished_at TEXT,
    discovered_url_count INTEGER NOT NULL DEFAULT 0,
    new_url_count INTEGER NOT NULL DEFAULT 0,
    error_type TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS discovery_targets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    source TEXT NOT NULL,
    target_name TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN (
            'running', 'completed', 'failed',
            'blocked', 'suspicious'
        )
    ),
    detected_last_page INTEGER,
    fetched_page_count INTEGER NOT NULL DEFAULT 0,
    discovered_url_count INTEGER NOT NULL DEFAULT 0,
    new_url_count INTEGER NOT NULL DEFAULT 0,
    duplicate_url_count INTEGER NOT NULL DEFAULT 0,
    empty_page_count INTEGER NOT NULL DEFAULT 0,
    invalid_page_count INTEGER NOT NULL DEFAULT 0,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    error_type TEXT,
    error_message TEXT,
    FOREIGN KEY(run_id) REFERENCES crawl_runs(id),
    UNIQUE(run_id, target_name)
);

CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    url TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    last_seen_run_id INTEGER,
    last_target_name TEXT,
    last_listing_url TEXT,
    last_listing_page INTEGER,
    raw_status TEXT NOT NULL DEFAULT 'pending' CHECK (
        raw_status IN (
            'pending', 'fetching', 'validating',
            'uploading', 'raw_ready',
            'retryable_error', 'blocked',
            'permanent_error', 'storage_missing',
            'storage_corrupt'
        )
    ),
    fetch_attempt_count INTEGER NOT NULL DEFAULT 0,
    last_attempt_at TEXT,
    next_retry_at TEXT,
    last_http_status INTEGER,
    last_error_type TEXT,
    last_error_message TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(last_seen_run_id) REFERENCES crawl_runs(id),
    UNIQUE(source, url)
);

CREATE TABLE IF NOT EXISTS fetch_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    job_id INTEGER NOT NULL,
    attempt_number INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN (
            'fetching', 'invalid_response',
            'fetch_error', 'blocked', 'uploading',
            'storage_error', 'success'
        )
    ),
    started_at TEXT NOT NULL,
    completed_at TEXT,
    requested_url TEXT NOT NULL,
    final_url TEXT,
    http_status INTEGER,
    content_type TEXT,
    content_length_bytes INTEGER,
    content_sha256 TEXT,
    validation_version TEXT,
    validation_report TEXT,
    storage_provider TEXT,
    bucket_name TEXT,
    object_key TEXT,
    object_version TEXT,
    fetched_at TEXT,
    error_type TEXT,
    error_message TEXT,
    quarantine_bucket TEXT,
    quarantine_object_key TEXT,
    FOREIGN KEY(run_id) REFERENCES crawl_runs(id),
    FOREIGN KEY(job_id) REFERENCES jobs(id),
    UNIQUE(job_id, attempt_number)
);

CREATE TABLE IF NOT EXISTS raw_objects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL UNIQUE,
    storage_provider TEXT NOT NULL,
    bucket_name TEXT NOT NULL,
    object_key TEXT NOT NULL,
    object_version TEXT,
    requested_url TEXT NOT NULL,
    final_url TEXT,
    http_status INTEGER NOT NULL,
    content_type TEXT,
    content_length_bytes INTEGER NOT NULL,
    content_sha256 TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    stored_at TEXT NOT NULL,
    validation_version TEXT NOT NULL,
    validation_report TEXT NOT NULL,
    last_integrity_check_at TEXT,
    integrity_status TEXT NOT NULL DEFAULT 'valid' CHECK (
        integrity_status IN (
            'unchecked', 'valid', 'missing',
            'size_mismatch', 'hash_mismatch'
        )
    ),
    FOREIGN KEY(job_id) REFERENCES jobs(id),
    UNIQUE(bucket_name, object_key)
);

CREATE TABLE IF NOT EXISTS parse_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL,
    raw_object_id INTEGER NOT NULL,
    parser_name TEXT NOT NULL,
    parser_version TEXT NOT NULL,
    attempt_number INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL CHECK (
        status IN (
            'parsing', 'success', 'parse_error',
            'validation_error', 'raw_missing',
            'raw_corrupt'
        )
    ),
    started_at TEXT NOT NULL,
    completed_at TEXT,
    parsed_field_count INTEGER,
    missing_required_fields TEXT,
    warnings TEXT,
    output_location TEXT,
    error_type TEXT,
    error_message TEXT,
    FOREIGN KEY(job_id) REFERENCES jobs(id),
    FOREIGN KEY(raw_object_id) REFERENCES raw_objects(id),
    UNIQUE(
        raw_object_id,
        parser_name,
        parser_version,
        attempt_number
    )
);

CREATE INDEX IF NOT EXISTS idx_jobs_queue
ON jobs(source, raw_status, next_retry_at);

CREATE INDEX IF NOT EXISTS idx_jobs_last_seen
ON jobs(source, last_seen_at);

CREATE INDEX IF NOT EXISTS idx_fetch_attempts_job
ON fetch_attempts(job_id, attempt_number DESC);

CREATE INDEX IF NOT EXISTS idx_fetch_attempts_run
ON fetch_attempts(run_id, status);

CREATE INDEX IF NOT EXISTS idx_targets_run
ON discovery_targets(run_id, status);

CREATE INDEX IF NOT EXISTS idx_parse_pending
ON parse_attempts(raw_object_id, parser_name, parser_version, status);
"""


@dataclass(frozen=True, slots=True)
class JobClaim:
    job_id: int
    attempt_id: int
    attempt_number: int
    record: DiscoveryRecord


@dataclass(frozen=True, slots=True)
class PendingUpload:
    job_id: int
    attempt_id: int
    locator: ObjectLocator
    expected_size: int
    expected_sha256: str


@dataclass(frozen=True, slots=True)
class RawObjectCheck:
    raw_object_id: int
    job_id: int
    locator: ObjectLocator
    expected_size: int
    expected_sha256: str


class StateStore(Protocol):

    def start_run(
        self,
        source: str,
        started_at: str,
    ) -> int: ...

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
    ) -> None: ...

    def upsert_discovered_jobs(
        self,
        records: list[DiscoveryRecord],
        run_id: int,
    ) -> int: ...

    def start_discovery_target(
        self,
        *,
        run_id: int,
        source: str,
        target_name: str,
        started_at: str,
    ) -> int: ...

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
    ) -> None: ...

    def claim_next_job(
        self,
        *,
        run_id: int,
        source: str,
        now: str,
        max_attempts: int,
    ) -> JobClaim | None: ...

    def mark_validating(
        self,
        claim: JobClaim,
    ) -> None: ...

    def mark_uploading(
        self,
        *,
        claim: JobClaim,
        payload: RawObjectPayload,
        fetch_result: FetchResult,
        validation: ValidationResult,
    ) -> None: ...

    def complete_upload(
        self,
        *,
        claim: JobClaim,
        stored: StoredObject,
        fetch_result: FetchResult,
        validation: ValidationResult,
        completed_at: str,
    ) -> None: ...

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
        fetch_result: FetchResult | None = None,
        validation: ValidationResult | None = None,
    ) -> None: ...

    def load_pending_uploads(
        self,
        source: str,
    ) -> list[PendingUpload]: ...

    def complete_recovered_upload(
        self,
        pending: PendingUpload,
        stored: StoredObject,
        completed_at: str,
    ) -> None: ...

    def fail_recovered_upload(
        self,
        pending: PendingUpload,
        *,
        completed_at: str,
        next_retry_at: str,
        error_message: str,
    ) -> None: ...

    def recover_stale_fetches(
        self,
        source: str,
        recovered_at: str,
    ) -> None: ...

    def load_raw_objects_for_integrity(
        self,
        source: str,
        limit: int,
    ) -> list[RawObjectCheck]: ...

    def update_raw_integrity(
        self,
        check: RawObjectCheck,
        *,
        status: str,
        checked_at: str,
    ) -> None: ...


class SQLiteStateStore:

    def __init__(self, database_path: str):
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        self._initialize()

    @classmethod
    def from_config(cls, config: dict):
        return cls(
            config["state"].get(
                "database_path",
                "data/state/joblake.db",
            )
        )

    def _open_connection(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.database_path,
            timeout=5,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    @contextmanager
    def _connect(
        self,
    ) -> Iterator[sqlite3.Connection]:
        connection = self._open_connection()

        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(SCHEMA_SQL)

    def start_run(
        self,
        source: str,
        started_at: str,
    ) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO crawl_runs (
                    source,
                    status,
                    started_at
                )
                VALUES (?, 'running', ?)
                """,
                (source, started_at),
            )
            return int(cursor.lastrowid)

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
                UPDATE crawl_runs
                SET
                    status = ?,
                    finished_at = ?,
                    discovered_url_count = ?,
                    new_url_count = ?,
                    error_type = ?,
                    error_message = ?
                WHERE id = ?
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
                INSERT INTO discovery_targets (
                    run_id,
                    source,
                    target_name,
                    status,
                    started_at
                )
                VALUES (?, ?, ?, 'running', ?)
                """,
                (
                    run_id,
                    source,
                    target_name,
                    started_at,
                ),
            )
            return int(cursor.lastrowid)

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
                UPDATE discovery_targets
                SET
                    status = ?,
                    detected_last_page = ?,
                    fetched_page_count = ?,
                    discovered_url_count = ?,
                    new_url_count = ?,
                    duplicate_url_count = ?,
                    empty_page_count = ?,
                    invalid_page_count = ?,
                    finished_at = ?,
                    error_type = ?,
                    error_message = ?
                WHERE id = ?
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
                existing = connection.execute(
                    """
                    SELECT id
                    FROM jobs
                    WHERE source = ? AND url = ?
                    """,
                    (record.source, record.url),
                ).fetchone()

                if existing is None:
                    connection.execute(
                        """
                        INSERT INTO jobs (
                            source,
                            url,
                            first_seen_at,
                            last_seen_at,
                            last_seen_run_id,
                            last_target_name,
                            last_listing_url,
                            last_listing_page,
                            raw_status
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending')
                        """,
                        (
                            record.source,
                            record.url,
                            record.discovered_at,
                            record.discovered_at,
                            run_id,
                            record.target_name,
                            record.listing_url,
                            record.listing_page,
                        ),
                    )
                    new_count += 1
                else:
                    connection.execute(
                        """
                        UPDATE jobs
                        SET
                            last_seen_at = ?,
                            last_seen_run_id = ?,
                            last_target_name = ?,
                            last_listing_url = ?,
                            last_listing_page = ?,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                        """,
                        (
                            record.discovered_at,
                            run_id,
                            record.target_name,
                            record.listing_url,
                            record.listing_page,
                            existing["id"],
                        ),
                    )

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
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT *
                FROM jobs
                WHERE source = ?
                  AND raw_status IN (
                      'pending',
                      'retryable_error',
                      'blocked'
                  )
                  AND fetch_attempt_count < ?
                  AND (
                      next_retry_at IS NULL
                      OR next_retry_at <= ?
                  )
                ORDER BY first_seen_at, id
                LIMIT 1
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
                UPDATE jobs
                SET
                    raw_status = 'fetching',
                    fetch_attempt_count = ?,
                    last_attempt_at = ?,
                    next_retry_at = NULL,
                    last_error_type = NULL,
                    last_error_message = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    attempt_number,
                    now,
                    row["id"],
                ),
            )
            cursor = connection.execute(
                """
                INSERT INTO fetch_attempts (
                    run_id,
                    job_id,
                    attempt_number,
                    status,
                    started_at,
                    requested_url
                )
                VALUES (?, ?, ?, 'fetching', ?, ?)
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
                attempt_id=int(cursor.lastrowid),
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
                UPDATE jobs
                SET
                    raw_status = 'validating',
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
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
                UPDATE fetch_attempts
                SET
                    status = 'uploading',
                    requested_url = ?,
                    final_url = ?,
                    http_status = ?,
                    content_type = ?,
                    content_length_bytes = ?,
                    content_sha256 = ?,
                    validation_version = ?,
                    validation_report = ?,
                    storage_provider = ?,
                    bucket_name = ?,
                    object_key = ?,
                    object_version = ?,
                    fetched_at = ?
                WHERE id = ?
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
                UPDATE jobs
                SET
                    raw_status = 'uploading',
                    last_http_status = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
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
                INSERT INTO raw_objects (
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
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, 'valid'
                )
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
                UPDATE fetch_attempts
                SET
                    status = 'success',
                    object_version = ?,
                    completed_at = ?
                WHERE id = ?
                """,
                (
                    stored.locator.object_version,
                    completed_at,
                    claim.attempt_id,
                ),
            )
            connection.execute(
                """
                UPDATE jobs
                SET
                    raw_status = 'raw_ready',
                    next_retry_at = NULL,
                    last_error_type = NULL,
                    last_error_message = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
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
        fetch_result: FetchResult | None = None,
        validation: ValidationResult | None = None,
    ) -> None:
        if attempt_status == "blocked":
            job_status = "blocked"
        elif claim.attempt_number >= max_attempts:
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
                UPDATE fetch_attempts
                SET
                    status = ?,
                    completed_at = ?,
                    final_url = COALESCE(?, final_url),
                    http_status = COALESCE(?, http_status),
                    content_type = COALESCE(?, content_type),
                    validation_version = COALESCE(
                        ?,
                        validation_version
                    ),
                    validation_report = COALESCE(
                        ?,
                        validation_report
                    ),
                    error_type = ?,
                    error_message = ?
                WHERE id = ?
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
                UPDATE jobs
                SET
                    raw_status = ?,
                    next_retry_at = ?,
                    last_http_status = COALESCE(
                        ?,
                        last_http_status
                    ),
                    last_error_type = ?,
                    last_error_message = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
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
                FROM fetch_attempts AS a
                JOIN jobs AS j ON j.id = a.job_id
                WHERE j.source = ?
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
                FROM fetch_attempts
                WHERE id = ?
                """,
                (pending.attempt_id,),
            ).fetchone()

            if row is None:
                return

            connection.execute(
                """
                INSERT OR IGNORE INTO raw_objects (
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
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, 'valid'
                )
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
                UPDATE fetch_attempts
                SET
                    status = 'success',
                    object_version = ?,
                    completed_at = ?
                WHERE id = ?
                """,
                (
                    stored.locator.object_version,
                    completed_at,
                    pending.attempt_id,
                ),
            )
            connection.execute(
                """
                UPDATE jobs
                SET
                    raw_status = 'raw_ready',
                    next_retry_at = NULL,
                    last_error_type = NULL,
                    last_error_message = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
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
                UPDATE fetch_attempts
                SET
                    status = 'storage_error',
                    completed_at = ?,
                    error_type = 'UploadRecoveryError',
                    error_message = ?
                WHERE id = ?
                """,
                (
                    completed_at,
                    error_message,
                    pending.attempt_id,
                ),
            )
            connection.execute(
                """
                UPDATE jobs
                SET
                    raw_status = 'retryable_error',
                    next_retry_at = ?,
                    last_error_type = 'UploadRecoveryError',
                    last_error_message = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
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
                UPDATE fetch_attempts
                SET
                    status = 'fetch_error',
                    completed_at = ?,
                    error_type = 'InterruptedRun',
                    error_message = 'Recovered unfinished fetch from a previous process'
                WHERE status = 'fetching'
                  AND job_id IN (
                      SELECT id FROM jobs WHERE source = ?
                  )
                """,
                (recovered_at, source),
            )
            connection.execute(
                """
                UPDATE jobs
                SET
                    raw_status = 'retryable_error',
                    next_retry_at = NULL,
                    last_error_type = 'InterruptedRun',
                    last_error_message = 'Recovered unfinished fetch from a previous process',
                    updated_at = CURRENT_TIMESTAMP
                WHERE source = ?
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
                FROM raw_objects AS r
                JOIN jobs AS j ON j.id = r.job_id
                WHERE j.source = ?
                ORDER BY
                    r.last_integrity_check_at IS NOT NULL,
                    r.last_integrity_check_at,
                    r.id
                LIMIT ?
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
                UPDATE raw_objects
                SET
                    integrity_status = ?,
                    last_integrity_check_at = ?
                WHERE id = ?
                """,
                (
                    status,
                    checked_at,
                    check.raw_object_id,
                ),
            )
            connection.execute(
                """
                UPDATE jobs
                SET
                    raw_status = ?,
                    last_error_type = ?,
                    last_error_message = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
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

    def load_crawled_urls(self) -> set[str]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT url
                FROM jobs
                WHERE raw_status = 'raw_ready'
                """
            ).fetchall()

        return {row["url"] for row in rows}


class FileStateStore:
    """Legacy file state kept only for compatibility utilities."""

    def __init__(
        self,
        discovered_jobs_file: str,
        crawled_urls_file: str,
    ):
        self.discovered_jobs_file = Path(
            discovered_jobs_file
        )
        self.crawled_urls_file = Path(
            crawled_urls_file
        )

    def save_discovered_jobs(
        self,
        records: dict[str, DiscoveryRecord],
    ) -> None:
        self.discovered_jobs_file.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        with self.discovered_jobs_file.open(
            mode="w",
            encoding="utf-8",
        ) as file:
            for record in records.values():
                file.write(
                    json.dumps(
                        asdict(record),
                        ensure_ascii=False,
                    )
                    + "\n"
                )

    def load_crawled_urls(self) -> set[str]:
        if not self.crawled_urls_file.exists():
            return set()

        return {
            line.strip()
            for line in self.crawled_urls_file.read_text(
                encoding="utf-8"
            ).splitlines()
            if line.strip()
        }

    def mark_crawled(self, url: str) -> None:
        self.crawled_urls_file.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        with self.crawled_urls_file.open(
            mode="a",
            encoding="utf-8",
        ) as file:
            file.write(f"{url}\n")


def create_state_store(config: dict) -> SQLiteStateStore:
    provider = config["state"].get(
        "provider",
        "sqlite",
    )

    if provider != "sqlite":
        raise ValueError(
            "The ingestion pipeline now requires "
            "state.provider=sqlite"
        )

    return SQLiteStateStore.from_config(config)


def save_discovered_jobs(
    path: str,
    records: dict[str, DiscoveryRecord],
) -> None:
    FileStateStore(path, path).save_discovered_jobs(
        records
    )


def load_crawled_urls(path: str) -> set[str]:
    return FileStateStore(path, path).load_crawled_urls()


def append_crawled_url(
    path: str,
    url: str,
) -> None:
    FileStateStore(path, path).mark_crawled(url)
