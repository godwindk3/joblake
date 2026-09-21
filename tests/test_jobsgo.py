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
FIXTURES = Path(__file__).parent / 'fixtures/jobsgo'
BASE = 'https://jobsgo.vn/nganh-nghe.html'


class JobsGoTests(unittest.TestCase):
    def setUp(self):
        self.config = load_config(str(ROOT / 'configs/jobsgo.yaml'))
        self.source = create_source(self.config)
        self.parser = create_parser(self.config)

    def fixture(self, name):
        return (FIXTURES / f'{name}.html').read_text(encoding='utf-8')

    def test_registry_and_pagination_request(self):
        self.assertIsInstance(create_source({'source': 'jobsgo'}), type(self.source))
        self.assertIsInstance(create_parser({'source': 'jobsgo'}), type(self.parser))
        for page in (1, 2, 30):
            request = self.source.build_listing_request(self.config['discovery']['targets'][0], self.config['discovery'], page)
            self.assertEqual(request.url, BASE)
            self.assertEqual(request.params, {'slug': 'viec-lam-cong-nghe-thong-tin', 'page': page})

    def test_listing_count_not_sliding_pagination_window(self):
        pages = []
        for name, count in (('list', 50), ('list2', 50), ('list30', 36)):
            html = self.fixture(name)
            urls = self.source.extract_job_urls(html, BASE)
            self.assertEqual(len(urls), count)
            self.assertTrue(all('?' not in u for u in urls))
            self.assertEqual(self.source.extract_last_page_number(html, BASE), 30)
            pages.append(set(urls))
        self.assertNotEqual(pages[0], pages[1])
        self.assertIsNone(self.source.extract_last_page_number('<h1>Sorry, you have been blocked</h1>', BASE))

    def test_listing_scope_tracking_and_dedup(self):
        html = self.fixture('list')
        urls = self.source.extract_job_urls(html, BASE)
        html += f'<div class="job-list"><h3 class="job-title"><a href="{urls[0]}?ref_component=other#top">Duplicate</a><a href="https://evil.test/viec-lam/job-123.html">External</a></h3></div>'
        html += '<h3 class="job-title"><a href="/viec-lam/related-123.html">Related</a></h3>'
        self.assertEqual(self.source.extract_job_urls(html, BASE), urls)

    def test_generic_crawler_preserves_slug_and_pages(self):
        self.config['discovery']['pagination']['total_pages'] = 2
        self.config['discovery']['delay'] = {'min_seconds': 0, 'max_seconds': 0}
        fetcher = MagicMock()
        fetcher.__enter__.return_value = fetcher
        def fetch(url, params=None):
            name = 'list' if params['page'] == 1 else 'list2'
            return FetchResult(url, url, 200, 'text/html', '', self.fixture(name))
        fetcher.fetch.side_effect = fetch
        crawler = DiscoveryCrawler(self.config, self.source, MagicMock(), lambda _: fetcher)
        self.assertGreater(len(crawler.run()), 50)
        self.assertEqual([c.kwargs['params']['page'] for c in fetcher.fetch.call_args_list], [1, 2])
        self.assertTrue(all(c.kwargs['params']['slug'] == 'viec-lam-cong-nghe-thong-tin' for c in fetcher.fetch.call_args_list))

    def test_detail_fields_and_validation(self):
        for name, identity in (('detail', '28555659312'), ('detail2', '28946041983'), ('detail3', '28926624013')):
            html = self.fixture(name)
            soup = BeautifulSoup(html, 'html.parser')
            url = soup.select_one('link[rel="canonical"]')['href']
            result = FetchResult(url, url, 200, 'text/html', '', html)
            self.assertTrue(self.source.validate_detail_html(result, url).is_valid)
            output = self.parser.parse(html, ParseContext('jobsgo', url, 0, 0, ''))
            job = output.job
            self.assertEqual(job.source_external_job_id, identity)
            for value in (job.title, job.employer_name_raw, job.description_text, job.requirements_text, job.benefits_text, job.salary_raw, job.experience_raw, job.locations_raw, job.categories_raw, job.posted_at):
                self.assertTrue(value)
            self.assertIn(assess_parsed_job(output).status, ('partial', 'accepted'))
            self.assertNotIn('Quyền lợi được hưởng', job.description_text)
            self.assertFalse(self.source.validate_detail_html(replace(result, final_url='https://jobsgo.vn/viec-lam/other-123.html'), url).is_valid)
            self.assertFalse(self.source.validate_detail_html(result, 'https://jobsgo.vn/viec-lam/other-123.html').is_valid)

    def test_missing_rendered_content_rejected_even_with_jsonld(self):
        soup = BeautifulSoup(self.fixture('detail'), 'html.parser')
        url = soup.select_one('link[rel="canonical"]')['href']
        soup.select_one('.job-detail-card').decompose()
        result = FetchResult(url, url, 200, 'text/html', '', str(soup))
        self.assertIn('missing_job_description', self.source.validate_detail_html(result, url).errors)
        self.assertFalse(self.source.validate_detail_html(replace(result, status_code=403, html='<h1>Sorry, you have been blocked</h1>'), url).is_valid)

    def test_recruit_post_without_jsonld_uses_actual_employer(self):
        html = self.fixture('recruit')
        soup = BeautifulSoup(html, 'html.parser')
        url = soup.select_one('link[rel="canonical"]')['href']
        result = FetchResult(url, url, 200, 'text/html', '', html)
        self.assertTrue(self.source.validate_detail_html(result, url).is_valid)
        output = self.parser.parse(html, ParseContext('jobsgo', url, 0, 0, ''))
        self.assertEqual(output.job.employer_name_raw, 'Công Ty TNHH Đầu Tư Công Nghệ Và Giáo Dục Kỷ Nguyên Số')
        self.assertEqual(output.job.source_variant, 'public_html')
        self.assertIn('Hà Nội', output.job.locations_raw)
        self.assertIn('Dữ Liệu - AI - Học Máy', output.job.categories_raw)
        self.assertTrue(output.job.posted_at)
        self.assertTrue(output.job.expires_at)
        self.assertTrue(assess_parsed_job(output).is_accepted)
        for card in soup.select('.card-company'):
            card.decompose()
        self.assertIn('missing_employer_name', self.source.validate_detail_html(replace(result, html=str(soup)), url).errors)


if __name__ == '__main__':
    unittest.main()
