import json
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
FIXTURES = Path(__file__).parent / 'fixtures' / 'careerviet'
BASE = 'https://careerviet.vn/viec-lam/cntt-phan-mem-c1-vi.html'


def metadata(total=685, limit=50, industry=1):
    payload = json.dumps({'totalJobs': total, 'params': f'page=1&industry={industry}&limit={limit}'}, separators=(',', ':'))
    return '<script>self.__next_f.push(' + json.dumps([1, payload]) + ')</script>'


class CareerVietTests(unittest.TestCase):
    def setUp(self):
        self.config = load_config(str(ROOT / 'configs/careerviet.yaml'))
        self.source = create_source(self.config)
        self.parser = create_parser(self.config)

    def test_registries_and_requests(self):
        self.assertEqual(type(create_source({'source': 'careerviet'})), type(self.source))
        self.assertEqual(type(create_parser({'source': 'careerviet'})), type(self.parser))
        for phase in ('discovery', 'detail'):
            self.assertEqual(self.config[phase]['user_agent'], 'JobLake/0.1')
        for page in (1, 2, 14):
            request = self.source.build_listing_request(self.config['discovery']['targets'][0], self.config['discovery'], page)
            self.assertEqual(request.url, BASE.replace('-vi.html', f'-trang-{page}-vi.html'))
            self.assertIsNone(request.params)

    def test_live_listing_fixtures(self):
        pages = []
        for page in (1, 2, 3):
            html = (FIXTURES / f'listing-{page}.html').read_text(encoding='utf-8')
            urls = self.source.extract_job_urls(html, BASE)
            self.assertEqual(len(urls), 50)
            pages.append(set(urls))
        self.assertNotEqual(pages[0], pages[1])
        self.assertNotEqual(pages[1], pages[2])

    def test_pagination_uses_total_and_limit(self):
        live = (FIXTURES / 'pagination.html').read_text(encoding='utf-8')
        self.assertEqual(self.source.extract_last_page_number(live, BASE), 14)
        self.assertEqual(self.source.extract_last_page_number(metadata(), BASE), 14)
        self.assertEqual(self.source.extract_last_page_number(metadata(100), BASE), 2)
        for html in ('<div class="pagination">1 2 3 4 5</div>', metadata(limit=0), metadata(industry=2)):
            self.assertIsNone(self.source.extract_last_page_number(html, BASE))

    def test_scope_and_deduplication(self):
        good = '/vi/tim-viec-lam/job.35C83B66.html'
        html = f'''<a class="job_link" href="/vi/tim-viec-lam/outside.35C83AA9.html">Outside</a>
        <div id="jobs-side-list-content"><div class="job-item">
          <a class="job_link" href="{good}?ref=x#top">One</a>
          <a class="job_link" href="https://www.careerviet.vn{good}">Duplicate</a>
          <a class="job_link" href="https://evil.test{good}">Other host</a>
          <a class="job_link" href="/vi/nha-tuyen-dung/company.35C83AA9.html">Company</a>
        </div></div>'''
        self.assertEqual(self.source.extract_job_urls(html, BASE), ['https://careerviet.vn' + good])

    def test_generic_crawler_follows_path_pages(self):
        self.config['discovery']['delay'] = {'min_seconds': 0, 'max_seconds': 0}
        fetcher = MagicMock()
        fetcher.__enter__.return_value = fetcher
        def fetch(url, params=None):
            page = int(url.split('-trang-')[1].split('-')[0])
            html = (FIXTURES / f'listing-{page}.html').read_text(encoding='utf-8') + metadata(150)
            return FetchResult(url, url, 200, 'text/html', '2026-09-18', html)
        fetcher.fetch.side_effect = fetch
        crawler = DiscoveryCrawler(self.config, self.source, MagicMock(), lambda _: fetcher)
        records = crawler.run()
        self.assertGreater(len(records), 100)
        self.assertEqual(fetcher.fetch.call_count, 3)
        self.assertFalse(crawler.has_suspicious_targets)

    def fixture(self, job_id):
        html = (FIXTURES / f'{job_id}.html').read_text(encoding='utf-8')
        soup = BeautifulSoup(html, 'html.parser')
        posting = json.loads(soup.find('script', type='application/ld+json').get_text())
        url = posting['url']
        return html, url, posting

    def test_detail_fixtures(self):
        for job_id in ('35C83B66', '35C83584', '35C83AA9', '35C8737C', '35C85462', '35C84AFE'):
            html, url, posting = self.fixture(job_id)
            with self.subTest(job_id=job_id):
                validation = self.source.validate_detail_html(FetchResult(url, url, 200, 'text/html', '', html), url)
                self.assertTrue(validation.is_valid, validation.errors)
                output = self.parser.parse(html, ParseContext('careerviet', url, 1, 1, ''))
                self.assertEqual(output.job.source_external_job_id, job_id)
                self.assertEqual(output.job.employer_name_raw, posting['hiringOrganization']['name'])
                self.assertTrue(output.job.description_text and output.job.requirements_text)
                self.assertTrue(output.job.categories_raw and output.job.location_cities)
                self.assertTrue(assess_parsed_job(output).is_accepted)
                self.assertNotIn('Yêu Cầu Công Việc', output.job.description_text)

    def test_company_need_not_be_a_link_and_dom_fallback(self):
        html, url, _ = self.fixture('35C83AA9')
        soup = BeautifulSoup(html, 'html.parser')
        soup.select_one('.job-company-name').name = 'span'
        soup.find('script', type='application/ld+json').decompose()
        html = str(soup)
        self.assertTrue(self.source.validate_detail_html(FetchResult(url, url, 200, 'text/html', '', html), url).is_valid)
        job = self.parser.parse(html, ParseContext('careerviet', url, 1, 1, '')).job
        self.assertEqual(job.employer_name_raw, 'Masan Consumer')
        self.assertEqual(job.source_external_job_id, '35C83AA9')
        self.assertIsNotNone(job.expires_at)

    def test_branded_templates_from_failed_run(self):
        for job_id in ('35C83348', '35C862A0', '35C862F6', '35C81985', '35C864C6'):
            with self.subTest(job_id=job_id):
                html, url, posting = self.fixture(job_id)
                result = FetchResult(url, url, 200, 'text/html', '', html)
                validation = self.source.validate_detail_html(result, url)
                self.assertTrue(validation.is_valid, validation.errors)
                output = self.parser.parse(html, ParseContext('careerviet', url, 1, 1, ''))
                self.assertEqual(output.job.title, posting['title'])
                self.assertTrue(output.job.description_text)
                self.assertTrue(output.job.requirements_text)
                self.assertTrue(output.job.salary_raw)
                self.assertTrue(assess_parsed_job(output).is_accepted)
                # JSON-LD alone must not make a missing rendered section valid.
                soup = BeautifulSoup(html, 'html.parser')
                for heading in soup.select('h2.detail-title,h3.detail-title'):
                    if heading.get_text(' ', strip=True).casefold() not in ('mô tả công việc', 'yêu cầu công việc'):
                        continue
                    if 'title-icon' in heading.parent.get('class', []):
                        heading.parent.find_next_sibling().decompose()
                    else:
                        sibling = heading.find_next_sibling()
                        if sibling:
                            sibling.decompose()
                self.assertFalse(self.source.validate_detail_html(replace(result, html=str(soup)), url).is_valid)

    def test_incomplete_and_wrong_job_responses_rejected(self):
        html, url, _ = self.fixture('35C83AA9')
        result = FetchResult(url, url, 200, 'text/html', '', html)
        for invalid in (
            replace(result, final_url=BASE),
            replace(result, final_url=url.replace('35C83AA9', '35C83B66')),
            replace(result, html=html.replace('35C83AA9', '35C83B66')),
            replace(result, html='<html>Login</html>'),
            replace(result, status_code=500),
        ):
            self.assertFalse(self.source.validate_detail_html(invalid, url).is_valid)
        soup = BeautifulSoup(html, 'html.parser')
        soup.select_one('.apply-now-banner').decompose()
        self.assertFalse(self.source.validate_detail_html(replace(result, html=str(soup)), url).is_valid)


if __name__ == '__main__':
    unittest.main()
