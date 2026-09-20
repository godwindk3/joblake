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
from joblake.parsing.vieclam24h_html import api_data, response_data
from joblake.sources.factory import create_source


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / 'fixtures' / 'vieclam24h'
BASE = 'https://vieclam24h.vn/viec-lam-it-phan-mem-o8.html'


class Vieclam24hTests(unittest.TestCase):
    def setUp(self):
        self.config = load_config(str(ROOT / 'configs/vieclam24h.yaml'))
        self.source = create_source(self.config)
        self.parser = create_parser(self.config)

    def fixture(self, name):
        return (FIXTURES / f'{name}.html').read_text(encoding='utf-8')

    def detail(self, identity='200905319'):
        html = self.fixture(identity)
        data = response_data(api_data(BeautifulSoup(html, 'html.parser')), 'jobDetailHiddenContact')
        url = 'https://vieclam24h.vn' + data['canonical']
        return html, url, data

    def test_registries_and_query_pagination(self):
        self.assertEqual(type(create_source({'source': 'vieclam24h'})), type(self.source))
        self.assertEqual(type(create_parser({'source': 'vieclam24h'})), type(self.parser))
        for page in (1, 2, 14):
            request = self.source.build_listing_request(self.config['discovery']['targets'][0], self.config['discovery'], page)
            self.assertEqual(request.url, BASE)
            self.assertEqual(request.params, {'page': page, 'sort_q': 'priority_max,desc'})

    def test_live_pagination_and_listing(self):
        pages = []
        for page in (1, 2, 3):
            html = self.fixture(f'listing-{page}')
            urls = self.source.extract_job_urls(html, BASE)
            self.assertEqual(len(urls), 20)
            self.assertEqual(self.source.extract_last_page_number(html, BASE), 14)
            self.assertTrue(all('?' not in u for u in urls))
            pages.append(set(urls))
        self.assertNotEqual(pages[0], pages[1])
        self.assertNotEqual(pages[1], pages[2])
        self.assertIsNone(self.source.extract_last_page_number('<html>Loading</html>', BASE))
        self.assertIsNone(self.source.extract_last_page_number('<script id="__NEXT_DATA__">bad</script>', BASE))

    def test_scope_and_tracking_deduplication(self):
        html = self.fixture('listing-1')
        urls = self.source.extract_job_urls(html, BASE)
        html += f'<a href="{urls[0]}?open_from=x&search_id=secret#top">duplicate</a>'
        html += '<a href="/it-phan-mem/unrelated-c8p73id999.html">Recommendation</a>'
        html += '<a href="https://evil.test/it-phan-mem/job-c8p73id999.html">External</a>'
        self.assertEqual(self.source.extract_job_urls(html, BASE), urls)

    def test_generic_discovery_keeps_sort_and_visits_pages(self):
        self.config['discovery']['pagination']['total_pages'] = 3
        self.config['discovery']['delay'] = {'min_seconds': 0, 'max_seconds': 0}
        fetcher = MagicMock()
        fetcher.__enter__.return_value = fetcher
        def fetch(url, params=None):
            return FetchResult(url, url, 200, 'text/html', '', self.fixture(f"listing-{params['page']}"))
        fetcher.fetch.side_effect = fetch
        crawler = DiscoveryCrawler(self.config, self.source, MagicMock(), lambda _: fetcher)
        self.assertEqual(len(crawler.run()), 60)
        self.assertFalse(crawler.has_suspicious_targets)
        self.assertEqual([c.kwargs['params']['page'] for c in fetcher.fetch.call_args_list], [1, 2, 3])

    def test_detail_ids_and_fields_across_categories(self):
        for identity in ('200905319', '200775200', '200893183'):
            with self.subTest(identity=identity):
                html, url, data = self.detail(identity)
                result = FetchResult(url, url, 200, 'text/html', '', html)
                self.assertTrue(self.source.validate_detail_html(result, url).is_valid)
                output = self.parser.parse(html, ParseContext('vieclam24h', url, 1, 1, ''))
                job = output.job
                self.assertEqual(job.source_external_job_id, identity)
                self.assertEqual(job.title, data['title'])
                self.assertEqual(job.employer_name_raw, data['employer_info']['name'])
                self.assertTrue(job.description_text and job.requirements_text and job.benefits_text)
                self.assertIn('IT Phần mềm', job.categories_raw)
                self.assertTrue(job.location_cities and job.salary_raw and job.employment_type_raw)
                self.assertTrue(assess_parsed_job(output).is_accepted)
                # JSON-LD identifier is employer ID, not job ID on this site.
                self.assertNotEqual(identity, '12888303')

    def test_rejects_wrong_identity_and_incomplete_html(self):
        html, url, _ = self.detail()
        result = FetchResult(url, url, 200, 'text/html', '', html)
        for invalid in (replace(result, final_url=BASE), replace(result, status_code=404),
                        replace(result, html=html.replace('200905319', '200905320')),
                        replace(result, html='<html>Login</html>')):
            self.assertFalse(self.source.validate_detail_html(invalid, url).is_valid)
        soup = BeautifulSoup(html, 'html.parser')
        for content in soup.select('.text-description'):
            content.decompose()
        self.assertFalse(self.source.validate_detail_html(replace(result, html=str(soup)), url).is_valid)

    def test_missing_employer_and_job_state_are_rejected(self):
        html, url, _ = self.detail()
        soup = BeautifulSoup(html, 'html.parser')
        node = soup.select_one('#__NEXT_DATA__')
        state = json.loads(node.get_text())
        state['props']['initialState']['api']['jobDetailHiddenContact']['data']['employer_info'] = {}
        node.string = json.dumps(state)
        result = FetchResult(url, url, 200, 'text/html', '', str(soup))
        self.assertIn('missing_employer_name', self.source.validate_detail_html(result, url).errors)
        node.decompose()
        self.assertFalse(self.source.validate_detail_html(replace(result, html=str(soup)), url).is_valid)


if __name__ == '__main__':
    unittest.main()
