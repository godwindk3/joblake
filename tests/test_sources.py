import unittest

from joblake.models import DiscoveryRecord
from joblake.sources.factory import create_source
from joblake.sources.itviec import ITviecSource
from joblake.sources.topcv import TopCVSource


class TopCVSourceTests(unittest.TestCase):

    def setUp(self) -> None:
        self.source = TopCVSource({"source": "topcv"})

    def test_extracts_direct_and_nested_urls(self) -> None:
        html = """
        <html>
          <script type="application/ld+json">
          {
            "@type": "ItemList",
            "itemListElement": [
              {"url": "/viec-lam/backend-1"},
              {"item": {"url": "/viec-lam/frontend-2"}},
              {"url": "/viec-lam/backend-1"},
              {"url": "/cong-ty/not-a-job"}
            ]
          }
          </script>
        </html>
        """

        urls = self.source.extract_job_urls(
            html,
            "https://www.topcv.vn/jobs?page=1",
        )

        self.assertEqual(
            urls,
            [
                "https://www.topcv.vn/viec-lam/backend-1",
                "https://www.topcv.vn/viec-lam/frontend-2",
            ],
        )

    def test_ignores_invalid_json_ld(self) -> None:
        html = """
        <script type="application/ld+json">not-json</script>
        """

        self.assertEqual(
            self.source.extract_job_urls(
                html,
                "https://www.topcv.vn/jobs",
            ),
            [],
        )

    def test_extracts_last_page_from_topcv_text(self) -> None:
        html = """
        <span id="job-listing-paginate-text">
          <span class="hight-light">1&nbsp;</span>/&nbsp;69 trang
        </span>
        """

        last_page = self.source.extract_last_page_number(
            html,
            "https://www.topcv.vn/jobs?page=1",
        )

        self.assertEqual(last_page, 69)

    def test_returns_none_for_missing_topcv_pagination(self) -> None:
        self.assertIsNone(
            self.source.extract_last_page_number(
                "<html></html>",
                "https://www.topcv.vn/jobs?page=1",
            )
        )

    def test_default_pagination_can_be_overridden(self) -> None:
        discovery_config = {
            "pagination": {
                "page_param": "page",
                "start_page": 1,
                "total_pages": 10,
            }
        }
        target = {
            "name": "it",
            "base_url": "https://example.com/jobs",
            "params": {"category": "it"},
            "start_page": 3,
            "total_pages": 2,
        }

        requests = list(
            self.source.iter_listing_requests(
                target,
                discovery_config,
            )
        )

        self.assertEqual(
            [request.page_number for request in requests],
            [3, 4],
        )
        self.assertEqual(
            requests[0].params,
            {"category": "it", "page": 3},
        )

    def test_detail_request_uses_listing_as_referer(self) -> None:
        record = DiscoveryRecord(
            source="topcv",
            url="https://example.com/viec-lam/1",
            target_name="it",
            listing_url="https://example.com/jobs?page=1",
            listing_page=1,
            discovered_at="2026-01-01T00:00:00+00:00",
        )

        request = self.source.build_detail_request(record)

        self.assertEqual(request.url, record.url)
        self.assertEqual(
            request.referer,
            record.listing_url,
        )

    def test_factory_loads_explicit_adapter(self) -> None:
        source = create_source({
            "source": "topcv",
            "source_adapter": (
                "joblake.sources.topcv.TopCVSource"
            ),
        })

        self.assertIsInstance(source, TopCVSource)


class ITviecSourceTests(unittest.TestCase):

    def setUp(self) -> None:
        self.source = ITviecSource({
            "source": "itviec"
        })

    def test_extracts_job_title_data_urls(self) -> None:
        html = """
        <h3
          class='imt-3 text-break'
          data-controller='utm-tracking'
          data-search--job-selection-target='jobTitle'
          data-url='https://itviec.com/it-jobs/data-engineer-5541?lab_feature=preview_jd_page'>
          Data Engineer
        </h3>
        <h3
          data-search--job-selection-target='companyName'
          data-url='https://itviec.com/companies/example'>
          Example company
        </h3>
        <a data-url='https://itviec.com/it-jobs/not-from-h3'>
          Ignore this
        </a>
        """

        urls = self.source.extract_job_urls(
            html,
            "https://itviec.com/it-jobs/ha-noi?page=1",
        )

        self.assertEqual(
            urls,
            [
                "https://itviec.com/it-jobs/"
                "data-engineer-5541"
            ],
        )

    def test_resolves_relative_urls_and_deduplicates(self) -> None:
        html = """
        <h3 data-search--job-selection-target='jobTitle'
            data-url='/it-jobs/backend-123'></h3>
        <h3 data-search--job-selection-target='jobTitle'
            data-url='/it-jobs/backend-123'></h3>
        <h3 data-search--job-selection-target='jobTitle'
            data-url='https://evil.example/it-jobs/fake'></h3>
        """

        urls = self.source.extract_job_urls(
            html,
            "https://itviec.com/it-jobs/ha-noi?page=1",
        )

        self.assertEqual(
            urls,
            ["https://itviec.com/it-jobs/backend-123"],
        )

    def test_extracts_last_page_from_itviec_links(self) -> None:
        html = """
        <div class="pagination-search-jobs"
             data-search--pagination-target="pagination">
          <nav class="ipagination">
            <div class="page current">1</div>
            <div class="page">
              <a href="/it-jobs/ho-chi-minh-hcm?page=2&amp;query=">2</a>
            </div>
            <div class="page gap">&hellip;</div>
            <div class="page">
              <a href="/it-jobs/ho-chi-minh-hcm?click_source=Navigation+menu&amp;page=29">29</a>
            </div>
          </nav>
        </div>
        """

        last_page = self.source.extract_last_page_number(
            html,
            "https://itviec.com/it-jobs/ho-chi-minh-hcm?page=1",
        )

        self.assertEqual(last_page, 29)

    def test_itviec_pagination_without_links_is_one_page(self) -> None:
        html = """
        <div data-search--pagination-target="pagination">
          <div class="page current">1</div>
        </div>
        """

        self.assertEqual(
            self.source.extract_last_page_number(
                html,
                "https://itviec.com/it-jobs/others?page=1",
            ),
            1,
        )

    def test_factory_loads_itviec_adapter(self) -> None:
        source = create_source({"source": "itviec"})

        self.assertIsInstance(source, ITviecSource)


if __name__ == "__main__":
    unittest.main()
