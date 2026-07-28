import sqlite3
import tempfile
import unittest
from pathlib import Path

from joblake.models import DiscoveryRecord
from joblake.state import SQLiteStateStore


class SQLiteStateStoreTests(unittest.TestCase):

    def test_creates_all_state_and_future_parse_tables(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = str(
                Path(directory) / "joblake.db"
            )
            SQLiteStateStore(database_path)
            connection = sqlite3.connect(database_path)

            try:
                tables = {
                    row[0]
                    for row in connection.execute(
                        """
                        SELECT name
                        FROM sqlite_master
                        WHERE type = 'table'
                        """
                    )
                }
            finally:
                connection.close()

            self.assertTrue({
                "crawl_runs",
                "discovery_targets",
                "jobs",
                "fetch_attempts",
                "raw_objects",
                "parse_attempts",
            }.issubset(tables))

    def test_upsert_checkpoints_jobs_without_duplicates(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = str(
                Path(directory) / "joblake.db"
            )
            state = SQLiteStateStore(database_path)
            run_one = state.start_run(
                "itviec",
                "2026-01-01T00:00:00+00:00",
            )
            first_record = DiscoveryRecord(
                source="itviec",
                url="https://itviec.com/it-jobs/backend-123",
                target_name="ha_noi",
                listing_url=(
                    "https://itviec.com/it-jobs/ha-noi?page=1"
                ),
                listing_page=1,
                discovered_at="2026-01-01T00:01:00+00:00",
            )

            first_new_count = (
                state.upsert_discovered_jobs(
                    [first_record],
                    run_one,
                )
            )
            run_two = state.start_run(
                "itviec",
                "2026-01-02T00:00:00+00:00",
            )
            second_record = DiscoveryRecord(
                source=first_record.source,
                url=first_record.url,
                target_name="ho_chi_minh",
                listing_url=(
                    "https://itviec.com/it-jobs/"
                    "ho-chi-minh-hcm?page=2"
                ),
                listing_page=2,
                discovered_at="2026-01-02T00:01:00+00:00",
            )
            second_new_count = (
                state.upsert_discovered_jobs(
                    [second_record],
                    run_two,
                )
            )
            connection = sqlite3.connect(database_path)

            try:
                row = connection.execute(
                    """
                    SELECT
                        COUNT(*),
                        last_seen_at,
                        last_target_name,
                        raw_status
                    FROM jobs
                    """
                ).fetchone()
            finally:
                connection.close()

            self.assertEqual(first_new_count, 1)
            self.assertEqual(second_new_count, 0)
            self.assertEqual(row[0], 1)
            self.assertEqual(
                row[1],
                "2026-01-02T00:01:00+00:00",
            )
            self.assertEqual(row[2], "ho_chi_minh")
            self.assertEqual(row[3], "pending")


if __name__ == "__main__":
    unittest.main()
