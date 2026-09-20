import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock

from bs4 import BeautifulSoup

from joblake.config import load_config
from joblake.discovery import DiscoveryCrawler
from joblake.models import FetchResult
from joblake.parsing.models import ParseContext
from joblake.parsing.registry import create_parser
from joblake.parsing.validation import assess_parsed_job
from joblake.sources.factory import create_source


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / 'fixtures' / 'careerlink'
BASE = 'https://www.careerlink.vn/viec-lam/cntt-phan-mem/19'


class CareerLinkTests(unittest.TestCase):
    def setUp(self):
        self.config = load_config(str(ROOT / 'configs/careerlink.yaml'))
        self.source = create_source(self.config)
        self.parser = create_parser(self.config)

    def fixture(self, name):
        return (FIXTURES / f'{name}.html').read_text(encoding='utf-8')

    def test_registry_and_first_page(self):
        self.assertEqual(type(create_source({'source': 'careerlink'})), type(self.source))
        self.assertEqual(type(create_parser({'source': 'careerlink'})), type(self.parser))
        for page in (1, 2, 3):
            req = self.source.build_listing_request(self.config['discovery']['targets'][0], self.config['discovery'], page)
            self.assertEqual(req.url, BASE)
            self.assertEqual(req.params, None if page == 1 else {'page': page})

    def test_live_listing_and_last_page(self):
        pages = []
        for page in (1, 2, 3):
            html = self.fixture(f'listing-{page}')
            urls = self.source.extract_job_urls(html, BASE)
            self.assertEqual(len(urls), 50)
            self.assertTrue(all('?' not in u for u in urls))
            self.assertEqual(self.source.extract_last_page_number(html, BASE), 9)
            pages.append(set(urls))
        self.assertNotEqual(pages[0], pages[1])
        self.assertNotEqual(pages[1], pages[2])
        self.assertIsNone(self.source.extract_last_page_number('<html>Loading</html>', BASE))

    def test_scope_tracking_and_duplicates(self):
        html = self.fixture('listing-1')
        urls = self.source.extract_job_urls(html, BASE)
        html += f'<li class="job-item"><a class="job-link" href="{urls[0]}?source=site#top">Duplicate</a></li>'
        html += '<a class="job-link" href="/tim-viec-lam/outside/123">Outside listing</a>'
        html += '<li class="job-item"><a class="job-link" href="https://evil.test/tim-viec-lam/job/123">External</a></li>'
        self.assertEqual(self.source.extract_job_urls(html, BASE), urls)

    def test_generic_crawler_first_page_once(self):
        self.config['discovery']['pagination']['total_pages'] = 3
        self.config['discovery']['delay'] = {'min_seconds': 0, 'max_seconds': 0}
        f = MagicMock()
        f.__enter__.return_value = f
        def fetch(url, params=None):
            page = (params or {}).get('page', 1)
            return FetchResult(url, url, 200, 'text/html', '', self.fixture(f'listing-{page}'))
        f.fetch.side_effect = fetch
        crawler = DiscoveryCrawler(self.config, self.source, MagicMock(), lambda _: f)
        self.assertGreater(len(crawler.run()), 100)
        self.assertEqual([c.kwargs['params'] for c in f.fetch.call_args_list], [None, {'page': 2}, {'page': 3}])
        self.assertFalse(crawler.has_suspicious_targets)

    def test_detail_fields(self):
        for identity in ('3608558', '3622072', '3622074'):
            with self.subTest(identity=identity):
                html = self.fixture(identity)
                url = f'https://www.careerlink.vn/tim-viec-lam/job/{identity}'
                result = FetchResult(url, url, 200, 'text/html', '', html)
                validation = self.source.validate_detail_html(result, url)
                self.assertTrue(validation.is_valid, validation.errors)
                output = self.parser.parse(html, ParseContext('careerlink', url, 1, 1, ''))
                job = output.job
                self.assertEqual(job.source_external_job_id, identity)
                self.assertTrue(job.title and job.employer_name_raw)
                self.assertTrue(job.description_text and job.requirements_text)
                self.assertTrue(job.salary_raw and job.experience_raw and job.employment_type_raw)
                self.assertTrue(job.categories_raw and job.locations_raw)
                self.assertNotIn('Kinh nghiệm / Kỹ năng chi tiết', job.requirements_text)
                self.assertTrue(assess_parsed_job(output).is_accepted)

    def test_wrong_job_and_incomplete_page_rejected(self):
        url = 'https://www.careerlink.vn/tim-viec-lam/full-stack-developer/3622072'
        html = self.fixture('3622072')
        result = FetchResult(url, url, 200, 'text/html', '', html)
        for invalid in (replace(result, final_url=BASE), replace(result, status_code=404),
                        replace(result, final_url=url.replace('3622072', '3622074')),
                        replace(result, html=html.replace('3622072', '3622074')),
                        replace(result, html='<html>Login</html>')):
            self.assertFalse(self.source.validate_detail_html(invalid, url).is_valid)
        soup = BeautifulSoup(html, 'html.parser')
        for name in ('description', 'skills'):
            soup.select_one('#section-job-' + name).decompose()
        self.assertFalse(self.source.validate_detail_html(replace(result, html=str(soup)), url).is_valid)


if __name__ == '__main__':
    unittest.main()
