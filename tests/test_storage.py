import tempfile
import unittest
from pathlib import Path

from joblake.models import DiscoveryRecord, FetchResult
from joblake.storage import LocalRawStorage


class LocalRawStorageTests(unittest.TestCase):

    def test_detail_key_is_stable_and_integrity_is_readable(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            storage = LocalRawStorage(directory)
            record = DiscoveryRecord(
                source="itviec",
                url="https://itviec.com/it-jobs/backend-123",
                target_name="ha_noi",
                listing_url=(
                    "https://itviec.com/it-jobs/ha-noi?page=1"
                ),
                listing_page=1,
                discovered_at="2026-01-01T00:00:00+00:00",
            )
            result = FetchResult(
                requested_url=record.url,
                final_url=record.url,
                status_code=200,
                content_type="text/html",
                fetched_at="2026-01-01T00:01:00+00:00",
                html="<html><h1>Backend</h1></html>",
            )
            first_payload = storage.prepare_detail(
                discovery_record=record,
                fetch_result=result,
            )
            second_payload = storage.prepare_detail(
                discovery_record=record,
                fetch_result=result,
            )
            stored = storage.save_prepared_detail(
                first_payload
            )
            stat = storage.stat_object(
                stored.locator,
                expected_sha256=(
                    stored.content_sha256
                ),
            )
            content = storage.read_object(
                stored.locator
            )

            self.assertEqual(
                first_payload.locator.object_key,
                second_payload.locator.object_key,
            )
            self.assertTrue(
                Path(
                    stored.locator.object_key
                ).is_file()
            )
            self.assertIsNotNone(stat)
            self.assertEqual(
                content,
                result.html.encode("utf-8"),
            )
            self.assertEqual(
                stat.content_sha256,
                stored.content_sha256,
            )


if __name__ == "__main__":
    unittest.main()
