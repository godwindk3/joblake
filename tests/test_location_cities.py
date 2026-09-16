import unittest
from dataclasses import asdict

from joblake.parsing.locations import location_cities
from joblake.parsing.models import ParsedJob


class CityTests(unittest.TestCase):
    def test_aliases_multi_city_and_stable_deduplication(self):
        self.assertEqual(location_cities((
            "Hà Nội: KCN Thăng Long, Xã Thiên Lộc", "Quận 1, TP.HCM",
            "Ho Chi Minh City, VN", "Hanoi", "Da Nang", "HCMC",
        )), ("Hà Nội", "Hồ Chí Minh", "Đà Nẵng"))

    def test_does_not_infer_from_street_district_or_unknown(self):
        self.assertEqual(location_cities((
            "123 đường Hà Nội, Quận 1", "Đường Hồ Chí Minh", "Huyện Đông Anh",
            "Remote", "Quốc tế", "VN", "Singapore", "Hà Nộii",
        )), ())

    def test_historical_names_are_not_silently_remapped(self):
        self.assertEqual(location_cities(("Tỉnh Bình Dương", "Bà Rịa - Vũng Tàu")),
                         ("Bình Dương", "Bà Rịa - Vũng Tàu"))

    def test_model_serializes_derived_field_without_altering_raw(self):
        raw = ("1 Main Street, Hà Nội, VN",)
        job = ParsedJob(locations_raw=raw)
        self.assertEqual(job.locations_raw, raw)
        self.assertEqual(asdict(job)["location_cities"], ("Hà Nội",))
        self.assertEqual(ParsedJob().location_cities, ())


if __name__ == "__main__":
    unittest.main()
