import unittest
from bs4 import BeautifulSoup
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock

from joblake.config import load_config
from joblake.discovery import DiscoveryCrawler
from joblake.models import FetchResult
from joblake.parsing.models import ParseContext
from joblake.parsing.registry import create_parser
from joblake.parsing.validation import assess_parsed_job
from joblake.sources.factory import create_source


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures" / "devwork"
LISTING = "https://devwork.vn/viec-lam"


def listing(page=1, last=7):
    return f'''<div id="list-job-container"><section class="job-list">
      <a href="/viec-lam/{page}/job-{page}">Job</a>
    </section></div><nav class="pagination"><a href="?page=5">5</a></nav>
    <script>window.__NUXT__=(function(a,b,c,d){{return {{pagination:{{page:a,limit:20,total:c,total_pages:b}}}}}}({page},{last},139,void 0));</script>'''


class DevworkTests(unittest.TestCase):
    def setUp(self):
        self.config = load_config(str(ROOT / "configs/devwork.yaml"))
        self.source = create_source(self.config)
        self.parser = create_parser(self.config)

    def test_default_registry(self):
        self.assertEqual(type(create_source({"source": "devwork"})), type(self.source))
        self.assertEqual(type(create_parser({"source": "devwork"})), type(self.parser))

    def test_url_scope_and_deduplication(self):
        html = '''<a href="/viec-lam/999/recommended">Outside results</a>
        <div id="list-job-container"><section class="job-list">
          <a href="/viec-lam/14244/ai-developer?ref=listing#top">Job</a>
          <a href="https://www.devwork.vn/viec-lam/14244/ai-developer/">Duplicate</a>
          <a href="/viec-lam/python">Skill</a>
          <a href="/cong-ty/12/company">Company</a>
          <a href="https://evil.devwork.vn/viec-lam/99/job">Other host</a>
          <a href="https://devwork.vn.evil.test/viec-lam/99/job">Other host</a>
          <a href="/viec-lam?page=2">Pagination</a>
        </section></div>'''
        self.assertEqual(self.source.extract_job_urls(html, LISTING),
                         [LISTING + "/14244/ai-developer"])

    def test_metadata_not_sliding_pagination_window(self):
        self.assertEqual(self.source.extract_last_page_number(listing(), LISTING), 7)

    def test_missing_or_changed_metadata_fails_closed(self):
        for html in ('<a href="?page=5">5</a>', listing().replace('139,void 0', 'evil(),void 0'),
                     listing(last=0), listing().replace('total_pages:b', 'unknown:b')):
            with self.subTest(html=html):
                self.assertIsNone(self.source.extract_last_page_number(html, LISTING))

    def test_generic_crawler_visits_all_pages(self):
        self.config['discovery']['delay'] = {'min_seconds': 0, 'max_seconds': 0}
        fetcher = MagicMock()
        fetcher.__enter__.return_value = fetcher
        def fetch(url, params=None):
            p = params['page']
            return FetchResult(url, f'{url}?page={p}', 200, 'text/html', '2026-09-18', listing(p))
        fetcher.fetch.side_effect = fetch
        crawler = DiscoveryCrawler(self.config, self.source, MagicMock(), lambda _: fetcher)
        records = crawler.run()
        self.assertEqual(len(records), 7)
        self.assertEqual([call.kwargs['params']['page'] for call in fetcher.fetch.call_args_list], list(range(1, 8)))
        self.assertFalse(crawler.has_suspicious_targets)

    def test_live_detail_fixtures(self):
        samples = (
            ('14244', 'ai-developer', 'AI Developer', ('Python', 'AI'), 'Hồ Chí Minh'),
            ('14252', 'project-manager', 'Project Manager', ('.NET', 'Oracle', 'PM'), 'Hà Nội'),
            ('13181', 'business-developmentsales-jp', 'Business Development/Sales JP', ('Sale Excutive',), 'Hà Nội'),
        )
        for job_id, slug, title, skills, city in samples:
            with self.subTest(job_id=job_id):
                html = (FIXTURES / f'{job_id}.html').read_text(encoding='utf-8')
                url = f'{LISTING}/{job_id}/{slug}'
                result = FetchResult(url, url, 200, 'text/html', '2026-09-18', html)
                self.assertTrue(self.source.validate_detail_html(result, url).is_valid)
                output = self.parser.parse(html, ParseContext('devwork', url, 1, 1, '2026-09-18'))
                job = output.job
                self.assertEqual(job.title, title)
                self.assertEqual(job.source_external_job_id, job_id)
                self.assertEqual(job.skills_raw, skills)
                self.assertEqual(job.location_cities, (city,))
                self.assertEqual(job.salary_raw, '15-25 triệu')
                self.assertEqual(job.employment_type_raw, 'Full-time')
                self.assertIsNotNone(job.expires_at)
                self.assertTrue(job.description_text and job.requirements_text and job.benefits_text)
                self.assertNotIn('Việc làm cùng kỹ năng', job.description_text)
                self.assertIsNone(job.posted_at)
                quality = assess_parsed_job(output)
                self.assertTrue(quality.is_accepted)
                self.assertEqual(quality.missing_recommended_fields, ('domains_raw', 'categories_raw'))

    def test_detail_rejects_redirects_and_missing_content(self):
        url = LISTING + '/14244/ai-developer'
        html = (FIXTURES / '14244.html').read_text(encoding='utf-8')
        result = FetchResult(url, url, 200, 'text/html', '2026-09-18', html)
        for changed in (
            replace(result, final_url=LISTING),
            replace(result, final_url=LISTING + '/14252/project-manager'),
            replace(result, html='<html><h1>Login</h1></html>'),
            replace(result, html=html.replace('block-desc', 'missing-content')),
            replace(result, status_code=404),
        ):
            with self.subTest(final_url=changed.final_url):
                self.assertFalse(self.source.validate_detail_html(changed, url).is_valid)

    def test_employer_without_company_link(self):
        for job_id, slug in (
            ('14018', 'project-manager-team-lead-onsite-tokyo'),
            ('14294', 'tester-onsite-hoang-cau'),
        ):
            with self.subTest(job_id=job_id):
                html = (FIXTURES / f'{job_id}.html').read_text(encoding='utf-8')
                url = f'{LISTING}/{job_id}/{slug}'
                result = FetchResult(url, url, 200, 'text/html', '2026-09-18', html)
                self.assertTrue(self.source.validate_detail_html(result, url).is_valid)
                output = self.parser.parse(html, ParseContext('devwork', url, 1, 1, '2026-09-18'))
                self.assertEqual(output.job.employer_name_raw, 'Công ty cổ phần phầm mềm Devwork')
                self.assertTrue(assess_parsed_job(output).is_accepted)
                soup = BeautifulSoup(html, 'html.parser')
                soup.select_one('.header-details h5').clear()
                invalid = self.source.validate_detail_html(replace(result, html=str(soup)), url)
                self.assertFalse(invalid.is_valid)
                self.assertIn('missing_employer_name', invalid.errors)


if __name__ == '__main__':
    unittest.main()
