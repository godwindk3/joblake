import hashlib
import unittest
from dataclasses import dataclass

from joblake.parsing.base import JobParser
from joblake.parsing.models import (
    ParseContext,
    ParsedJob,
    ParserOutput,
)
from joblake.parsing.service import ParseService
from joblake.state import ParseClaim
from joblake.storage import ObjectLocator


_HTML = b"<html><body>job</body></html>"


class FakeStorage:
    def __init__(self, content: bytes = _HTML):
        self.content = content

    def read_object(self, locator):
        return self.content


class FakeState:
    def __init__(self, claim: ParseClaim):
        self.claim = claim
        self.claimed = False
        self.completed = []
        self.failed = []
        self.recovered = []

    def recover_stale_parses(
        self,
        source,
        recovered_at,
        stale_before,
    ):
        self.recovered.append(
            (source, recovered_at, stale_before)
        )

    def count_exhausted_parses(self, **kwargs):
        return 0

    def claim_next_raw_for_parse(self, **kwargs):
        if self.claimed:
            return None
        self.claimed = True
        return self.claim

    def complete_parse(self, claim, **kwargs):
        self.completed.append((claim, kwargs))

    def fail_parse(self, claim, **kwargs):
        self.failed.append((claim, kwargs))


class FakeParser(JobParser):
    source = "itviec"
    version = "1.0.0"

    def __init__(self, job: ParsedJob):
        self.job = job

    def parse(
        self,
        html: str,
        context: ParseContext,
    ) -> ParserOutput:
        return ParserOutput(job=self.job)


@dataclass
class FakeWriteResult:
    output_location: str


class FakeRepository:
    def __init__(self, error: Exception | None = None):
        self.error = error
        self.calls = []

    def save_parse_result(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return FakeWriteResult(
            "postgres:core.job_parse_results/7"
        )


def _complete_job() -> ParsedJob:
    return ParsedJob(
        title="Data Engineer",
        employer_name_raw="Example Co",
        description_text="Build pipelines",
        requirements_text="Know Python",
        benefits_text="Insurance",
        domains_raw=("Data",),
        categories_raw=("Engineering",),
        skills_raw=("Python",),
    )


def _claim(
    *,
    size: int = len(_HTML),
    sha256: str = hashlib.sha256(_HTML).hexdigest(),
) -> ParseClaim:
    return ParseClaim(
        run_id=1,
        job_id=2,
        raw_object_id=3,
        attempt_id=4,
        attempt_number=1,
        source="itviec",
        canonical_url="https://itviec.com/it-jobs/data-1",
        first_seen_at="2026-01-01T00:00:00+00:00",
        last_seen_at="2026-01-02T00:00:00+00:00",
        fetched_at="2026-01-02T01:00:00+00:00",
        locator=ObjectLocator(
            provider="minio",
            bucket_name="joblake",
            object_key="raw/detail/data-1.html",
        ),
        expected_size=size,
        expected_sha256=sha256,
    )


class ParseServiceTests(unittest.TestCase):
    def _service(
        self,
        *,
        claim: ParseClaim | None = None,
        job: ParsedJob | None = None,
        storage: FakeStorage | None = None,
        repository: FakeRepository | None = None,
    ):
        state = FakeState(claim or _claim())
        repository = repository or FakeRepository()
        service = ParseService(
            config={
                "source": "itviec",
                "parse": {
                    "max_attempts": 3,
                    "max_jobs_per_run": None,
                },
            },
            storage=storage or FakeStorage(),
            state=state,
            parser=FakeParser(job or _complete_job()),
            repository=repository,
        )
        return service, state, repository

    def test_accepted_result_is_written_then_completed(self) -> None:
        service, state, repository = self._service()

        summary = service.run(run_id=1)

        self.assertEqual(summary.accepted, 1)
        self.assertEqual(len(repository.calls), 1)
        self.assertEqual(len(state.completed), 1)
        self.assertEqual(state.failed, [])
        self.assertEqual(
            state.completed[0][1]["output_location"],
            "postgres:core.job_parse_results/7",
        )
        self.assertEqual(
            repository.calls[0]["canonical_url"],
            "https://itviec.com/it-jobs/data-1",
        )

    def test_rejected_result_never_reaches_postgres(self) -> None:
        service, state, repository = self._service(
            job=ParsedJob(title="Missing everything else")
        )

        summary = service.run(run_id=1)

        self.assertEqual(summary.rejected, 1)
        self.assertEqual(repository.calls, [])
        self.assertEqual(
            state.failed[0][1]["status"],
            "validation_error",
        )

    def test_size_mismatch_marks_raw_corrupt(self) -> None:
        service, state, repository = self._service(
            claim=_claim(size=999)
        )

        summary = service.run(run_id=1)

        self.assertEqual(summary.failed, 1)
        self.assertEqual(repository.calls, [])
        self.assertEqual(
            state.failed[0][1]["integrity_status"],
            "size_mismatch",
        )

    def test_postgres_failure_remains_retryable(self) -> None:
        service, state, _ = self._service(
            repository=FakeRepository(RuntimeError("database offline"))
        )

        summary = service.run(run_id=1)

        self.assertEqual(summary.failed, 1)
        self.assertEqual(
            state.failed[0][1]["status"],
            "parse_error",
        )


if __name__ == "__main__":
    unittest.main()
