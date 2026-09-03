import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol

from joblake.parsing.base import JobParser
from joblake.parsing.models import ParseContext
from joblake.parsing.registry import create_parser
from joblake.parsing.validation import assess_parsed_job
from joblake.state import ParseClaim, StateStore
from joblake.storage import RawStorage


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ParseWriteResult(Protocol):
    output_location: str


class ParseResultRepository(Protocol):
    def save_parse_result(self, **kwargs) -> ParseWriteResult: ...


@dataclass(frozen=True, slots=True)
class ParseRunSummary:
    processed: int = 0
    accepted: int = 0
    partial: int = 0
    rejected: int = 0
    failed: int = 0
    exhausted: int = 0

    @property
    def has_failures(self) -> bool:
        return bool(
            self.rejected or self.failed or self.exhausted
        )


class ParseService:
    def __init__(
        self,
        *,
        config: dict,
        storage: RawStorage,
        state: StateStore,
        parser: JobParser | None = None,
        repository: ParseResultRepository | None = None,
    ):
        self.config = config
        self.storage = storage
        self.state = state
        self.parser = parser or create_parser(config)

        if repository is None:
            from joblake.postgres import create_postgres_repository

            repository = create_postgres_repository(config)
        self.repository = repository

    def run(self, run_id: int) -> ParseRunSummary:
        parse_config = self.config.get("parse", {})
        max_jobs = parse_config.get("max_jobs_per_run")
        max_attempts = int(parse_config.get("max_attempts", 3))
        stale_after_seconds = int(
            parse_config.get("stale_after_seconds", 3600)
        )

        if max_attempts < 1:
            raise ValueError("parse.max_attempts must be at least 1")
        if stale_after_seconds < 1:
            raise ValueError(
                "parse.stale_after_seconds must be at least 1"
            )

        now = datetime.now(timezone.utc)
        self.state.recover_stale_parses(
            self.parser.source,
            now.isoformat(),
            (now - timedelta(seconds=stale_after_seconds)).isoformat(),
        )

        processed = 0
        accepted = 0
        partial = 0
        rejected = 0
        failed = 0

        while max_jobs is None or processed < int(max_jobs):
            claim = self.state.claim_next_raw_for_parse(
                run_id=run_id,
                source=self.parser.source,
                parser_name=self.parser.name,
                parser_version=self.parser.version,
                started_at=_utc_now(),
                max_attempts=max_attempts,
            )
            if claim is None:
                break

            processed += 1
            outcome = self._process_claim(claim)

            if outcome == "accepted":
                accepted += 1
            elif outcome == "partial":
                partial += 1
            elif outcome == "rejected":
                rejected += 1
            else:
                failed += 1

        exhausted = self.state.count_exhausted_parses(
            source=self.parser.source,
            parser_name=self.parser.name,
            parser_version=self.parser.version,
            max_attempts=max_attempts,
        )
        summary = ParseRunSummary(
            processed=processed,
            accepted=accepted,
            partial=partial,
            rejected=rejected,
            failed=failed,
            exhausted=exhausted,
        )
        print(
            "Parse results: "
            f"processed={summary.processed}, "
            f"accepted={summary.accepted}, "
            f"partial={summary.partial}, "
            f"rejected={summary.rejected}, "
            f"failed={summary.failed}, "
            f"exhausted={summary.exhausted}"
        )
        return summary

    def _process_claim(self, claim: ParseClaim) -> str:
        try:
            content = self.storage.read_object(claim.locator)
        except Exception as exc:
            status = (
                "raw_missing"
                if _is_missing_object_error(exc)
                else "parse_error"
            )
            self._fail(
                claim,
                status=status,
                error=exc,
            )
            return "failed"

        if len(content) != claim.expected_size:
            self.state.fail_parse(
                claim,
                status="raw_corrupt",
                completed_at=_utc_now(),
                error_type="RawSizeMismatch",
                error_message=(
                    f"Expected {claim.expected_size} bytes, "
                    f"received {len(content)}"
                ),
                integrity_status="size_mismatch",
            )
            return "failed"

        actual_sha256 = hashlib.sha256(content).hexdigest()
        if actual_sha256 != claim.expected_sha256:
            self.state.fail_parse(
                claim,
                status="raw_corrupt",
                completed_at=_utc_now(),
                error_type="RawHashMismatch",
                error_message=(
                    f"Expected SHA-256 {claim.expected_sha256}, "
                    f"received {actual_sha256}"
                ),
                integrity_status="hash_mismatch",
            )
            return "failed"

        try:
            html = content.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            self._fail(claim, status="parse_error", error=exc)
            return "failed"

        context = ParseContext(
            source=claim.source,
            canonical_url=claim.canonical_url,
            crawler_job_id=claim.job_id,
            raw_object_id=claim.raw_object_id,
            fetched_at=claim.fetched_at,
        )

        try:
            output = self.parser.parse(html, context)
        except Exception as exc:
            self._fail(claim, status="parse_error", error=exc)
            return "failed"

        assessment = assess_parsed_job(output)
        issue_dicts = assessment.issue_dicts()

        if not assessment.is_accepted:
            self.state.fail_parse(
                claim,
                status="validation_error",
                completed_at=_utc_now(),
                error_type="ParsedJobValidationError",
                error_message=_issues_message(assessment.issues),
                missing_required_fields=list(
                    assessment.missing_required_fields
                ),
                warnings=issue_dicts,
            )
            return "rejected"

        parsed_at = _utc_now()
        try:
            stored = self.repository.save_parse_result(
                source=claim.source,
                canonical_url=claim.canonical_url,
                crawler_job_id=claim.job_id,
                first_seen_at=claim.first_seen_at,
                last_seen_at=claim.last_seen_at,
                raw_object_id=claim.raw_object_id,
                raw_provider=claim.locator.provider,
                raw_bucket=claim.locator.bucket_name,
                raw_object_key=claim.locator.object_key,
                raw_object_version=claim.locator.object_version,
                raw_sha256=claim.expected_sha256,
                fetched_at=claim.fetched_at,
                parser_name=self.parser.name,
                parser_version=self.parser.version,
                parsed_job=output.job,
                quality_status=assessment.status,
                completeness_score=assessment.completeness_score,
                missing_fields=list(
                    assessment.missing_required_fields
                    + assessment.missing_recommended_fields
                ),
                warnings=issue_dicts,
                parsed_at=parsed_at,
            )
        except Exception as exc:
            self._fail(claim, status="parse_error", error=exc)
            return "failed"

        self.state.complete_parse(
            claim,
            completed_at=_utc_now(),
            parsed_field_count=output.job.parsed_field_count(),
            missing_required_fields=list(
                assessment.missing_required_fields
            ),
            warnings=issue_dicts,
            output_location=stored.output_location,
        )
        print(
            f"Parsed {assessment.status}: {claim.canonical_url}"
        )
        return assessment.status

    def _fail(
        self,
        claim: ParseClaim,
        *,
        status: str,
        error: Exception,
    ) -> None:
        self.state.fail_parse(
            claim,
            status=status,
            completed_at=_utc_now(),
            error_type=type(error).__name__,
            error_message=str(error),
        )
        print(f"Parse failed for {claim.canonical_url}: {error}")


def _is_missing_object_error(error: Exception) -> bool:
    if isinstance(error, FileNotFoundError):
        return True
    return getattr(error, "code", None) in {
        "NoSuchKey",
        "NoSuchObject",
        "NoSuchBucket",
        "NoSuchVersion",
    }


def _issues_message(issues) -> str:
    messages = [
        issue.message
        for issue in issues
        if issue.severity == "error"
    ]
    return "; ".join(messages) or "Parsed job was rejected"
