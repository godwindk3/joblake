import sqlite3
import tempfile
import unittest
from pathlib import Path

from joblake.state import SQLiteStateStore


class ParseStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_path = str(
            Path(self.temporary_directory.name) / "joblake.db"
        )
        self.state = SQLiteStateStore(self.database_path)
        self._seed_raw_object()

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def _seed_raw_object(self) -> None:
        connection = sqlite3.connect(self.database_path)
        try:
            cursor = connection.execute(
                """
                INSERT INTO jobs (
                    source,
                    url,
                    first_seen_at,
                    last_seen_at,
                    raw_status
                )
                VALUES (?, ?, ?, ?, 'raw_ready')
                """,
                (
                    "itviec",
                    "https://itviec.com/it-jobs/backend-1",
                    "2026-01-01T00:00:00+00:00",
                    "2026-01-02T00:00:00+00:00",
                ),
            )
            job_id = int(cursor.lastrowid)
            connection.execute(
                """
                INSERT INTO raw_objects (
                    job_id,
                    storage_provider,
                    bucket_name,
                    object_key,
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
                    integrity_status
                )
                VALUES (
                    ?, 'minio', 'joblake', 'raw/detail/one.html',
                    ?, ?, 200, 'text/html', 10, ?, ?, ?, 'v1', '{}',
                    'valid'
                )
                """,
                (
                    job_id,
                    "https://itviec.com/it-jobs/backend-1",
                    "https://itviec.com/it-jobs/backend-1",
                    "a" * 64,
                    "2026-01-02T01:00:00+00:00",
                    "2026-01-02T01:00:01+00:00",
                ),
            )
            connection.commit()
        finally:
            connection.close()

    def _start_run(self) -> int:
        return self.state.start_run(
            "itviec",
            "2026-01-03T00:00:00+00:00",
        )

    def _claim(self, run_id: int, version: str = "1.0.0"):
        return self.state.claim_next_raw_for_parse(
            run_id=run_id,
            source="itviec",
            parser_name="itviec",
            parser_version=version,
            started_at="2026-01-03T00:01:00+00:00",
            max_attempts=3,
        )

    def test_success_skips_same_version_but_allows_new_version(
        self,
    ) -> None:
        run_id = self._start_run()
        claim = self._claim(run_id)
        self.assertIsNotNone(claim)
        assert claim is not None

        self.state.complete_parse(
            claim,
            completed_at="2026-01-03T00:02:00+00:00",
            parsed_field_count=8,
            missing_required_fields=[],
            warnings=[],
            output_location="postgres:core.job_parse_results/1",
        )

        self.assertIsNone(self._claim(run_id))
        new_version_claim = self._claim(run_id, version="1.1.0")
        self.assertIsNotNone(new_version_claim)
        assert new_version_claim is not None
        self.assertEqual(new_version_claim.attempt_number, 1)

    def test_parse_error_retries_on_next_run_not_same_run(self) -> None:
        first_run = self._start_run()
        claim = self._claim(first_run)
        assert claim is not None
        self.state.fail_parse(
            claim,
            status="parse_error",
            completed_at="2026-01-03T00:02:00+00:00",
            error_type="ValueError",
            error_message="temporary parser failure",
        )

        self.assertIsNone(self._claim(first_run))
        second_run = self._start_run()
        retry = self._claim(second_run)
        self.assertIsNotNone(retry)
        assert retry is not None
        self.assertEqual(retry.attempt_number, 2)

    def test_validation_error_is_terminal_for_parser_version(self) -> None:
        run_id = self._start_run()
        claim = self._claim(run_id)
        assert claim is not None
        self.state.fail_parse(
            claim,
            status="validation_error",
            completed_at="2026-01-03T00:02:00+00:00",
            error_type="ParsedJobValidationError",
            error_message="missing title",
            missing_required_fields=["title"],
        )

        self.assertIsNone(self._claim(self._start_run()))
        self.assertIsNotNone(
            self._claim(self._start_run(), version="2.0.0")
        )

    def test_recover_stale_parse_allows_future_retry(self) -> None:
        first_run = self._start_run()
        claim = self._claim(first_run)
        assert claim is not None

        self.state.recover_stale_parses(
            "itviec",
            "2026-01-04T00:00:00+00:00",
            "2026-01-03T00:02:00+00:00",
        )
        retry = self._claim(self._start_run())

        self.assertIsNotNone(retry)
        assert retry is not None
        self.assertEqual(retry.attempt_number, 2)

    def test_recent_parse_is_not_recovered_as_stale(self) -> None:
        run_id = self._start_run()
        claim = self._claim(run_id)
        assert claim is not None

        self.state.recover_stale_parses(
            "itviec",
            "2026-01-03T00:02:00+00:00",
            "2026-01-03T00:00:30+00:00",
        )

        self.state.complete_parse(
            claim,
            completed_at="2026-01-03T00:02:00+00:00",
            parsed_field_count=8,
            missing_required_fields=[],
            warnings=[],
            output_location="postgres:core.job_parse_results/1",
        )

    def test_completed_parse_must_still_be_owned_by_its_run(self) -> None:
        run_id = self._start_run()
        claim = self._claim(run_id)
        assert claim is not None
        self.state.recover_stale_parses(
            "itviec",
            "2026-01-03T00:03:00+00:00",
            "2026-01-03T00:02:00+00:00",
        )

        with self.assertRaisesRegex(RuntimeError, "no longer owned"):
            self.state.complete_parse(
                claim,
                completed_at="2026-01-03T00:03:00+00:00",
                parsed_field_count=8,
                missing_required_fields=[],
                warnings=[],
                output_location="postgres:core.job_parse_results/1",
            )

    def test_exhausted_parse_errors_are_reported(self) -> None:
        for attempt in range(3):
            claim = self._claim(self._start_run())
            assert claim is not None
            self.state.fail_parse(
                claim,
                status="parse_error",
                completed_at=(
                    f"2026-01-03T00:0{attempt + 1}:00+00:00"
                ),
                error_type="ValueError",
                error_message="parser failure",
            )

        self.assertEqual(
            self.state.count_exhausted_parses(
                source="itviec",
                parser_name="itviec",
                parser_version="1.0.0",
                max_attempts=3,
            ),
            1,
        )


if __name__ == "__main__":
    unittest.main()
