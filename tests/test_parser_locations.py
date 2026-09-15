"""Location regressions, including DOM/JSON-LD shapes observed on 2026-09-15."""
import json
import unittest

from joblake.parsing.models import ParseContext
from joblake.parsing.parsers.itviec import ITviecParser
from joblake.parsing.parsers.topcv import TopCVParser
from joblake.parsing.parsers.topdev import TopDevParser
from joblake.parsing.parsers.vietnamworks import VietnamWorksParser


def parse(parser, body, locations=None):
    posting = {"@type": "JobPosting", "title": "Engineer", "jobLocation": locations}
    html = body + '<script type="application/ld+json">' + json.dumps(posting) + '</script>'
    return parser.parse(html, ParseContext(
        source=parser.source, canonical_url="https://example.test/job",
        crawler_job_id=1, raw_object_id=1, fetched_at="2026-09-15T00:00:00Z",
    )).job.locations_raw


class LocationTests(unittest.TestCase):
    def test_all_sources_support_multiple_structured_locations(self):
        for parser, marker in (
            (ITviecParser(), ""), (TopCVParser(), '<div id="job-detail"></div>'),
            (TopDevParser(), ""), (VietnamWorksParser(), ""),
        ):
            with self.subTest(source=parser.source):
                locations = [
                    {"address": {"streetAddress": "1 Main Street", "addressLocality": "Hà Nội",
                                 "addressRegion": "Hà Nội", "addressCountry": {"@type": "Country", "name": "VN"}}},
                    {"address": "Hồ Chí Minh"}, {"address": "Hồ Chí Minh"},
                    {"address": {"addressCountry": {"@type": "Country"}}},
                ]
                self.assertEqual(parse(parser, marker, locations), ("1 Main Street, Hà Nội, VN", "Hồ Chí Minh"))

    def test_itviec_visible_address_overrides_stale_json_ld(self):
        # https://itviec.com/it-jobs/business-analyst-poems-digital-trading-agile-jira-cyberquote-pte-ltd-4039
        address = "15&16th Floor, SUDICO HH3 Tower, Me Tri Street, Tu Liem, Ha Noi"
        html = f'''<div class="job-show-info"><div class="d-inline-block text-dark-grey">
        <span class="normal-text text-rich-grey">{address}</span>
        <a href="https://www.google.com/maps?q=address"></a></div>
        <span class="normal-text">At office</span></div>
        <div><span class="normal-text">Company HQ</span><a href="https://www.google.com/maps?q=hq"></a></div>'''
        self.assertEqual(parse(ITviecParser(), html, {"address": "Quận Cầu Giấy, Hà Nội"}), (address,))

    def test_topcv_current_address_and_time_layout(self):
        # https://www.topcv.vn/viec-lam/nhan-vien-it-it-helpdesk-it-in-house/2301249.html
        address = "Hà Nội: RF20, Lô P4, KCN Thăng Long, Xã Thiên Lộc (huyện Đông Anh cũ)"
        html = f'''<div id="job-detail"></div>
        <h2>Địa điểm và thời gian</h2>
        <div class="box-job-information-address-and-time-list__item">
          <h3 class="box-job-information-address-and-time-list__item--title">Địa điểm làm việc</h3>
          <div class="box-job-information-address-and-time-list__item--content">
            <ul><li>{address}</li><li>Đà Nẵng: 2 Main Street</li><li>{address}</li></ul>
          </div></div>
        <div class="box-job-information-address-and-time-list__item">
          <h3 class="box-job-information-address-and-time-list__item--title">Thời gian làm việc</h3>
          <div class="box-job-information-address-and-time-list__item--content"><ul><li>Thứ 2 - Thứ 6</li></ul></div>
        </div><span>Địa điểm: Company HQ</span>'''
        self.assertEqual(parse(TopCVParser(), html), (address, "Đà Nẵng: 2 Main Street"))

    def test_observed_topdev_and_vietnamworks_structured_shapes(self):
        cases = (
            (TopDevParser(), {"addressCountry": "VN", "addressLocality": "Thành phố Hồ Chí Minh",
                              "addressRegion": "Hồ Chí Minh", "postalCode": "700000",
                              "streetAddress": "Lô 14-16-18-20, Đường số 36, Phường Bình Phú, Thành phố Hồ Chí Minh"},
             "Lô 14-16-18-20, Đường số 36, Phường Bình Phú, Thành phố Hồ Chí Minh, Thành phố Hồ Chí Minh, Hồ Chí Minh, VN"),
            (VietnamWorksParser(), {"addressCountry": "VN", "addressLocality": "Quốc tế",
                                    "addressRegion": "Quốc tế", "postalCode": 1,
                                    "streetAddress": "office name - Quốc tế - 1234 ABC Daycare LLC"},
             "office name - Quốc tế - 1234 ABC Daycare LLC, Quốc tế, VN"),
        )
        for parser, address, expected in cases:
            with self.subTest(source=parser.source):
                self.assertEqual(parse(parser, "", {"@type": "Place", "address": address}), (expected,))

    def test_missing_location_stays_empty_for_every_source(self):
        for parser, marker in (
            (ITviecParser(), ""), (TopCVParser(), '<div id="job-detail"></div>'),
            (TopDevParser(), ""), (VietnamWorksParser(), ""),
        ):
            with self.subTest(source=parser.source):
                self.assertEqual(parse(parser, marker), ())


if __name__ == "__main__":
    unittest.main()
