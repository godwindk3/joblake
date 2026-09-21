import math
import re
from dataclasses import replace
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from joblake.parsing.common import find_job_posting, tag_text
from joblake.parsing.jobsgo_html import employer_name, job_id, section
from joblake.sources.base import JobSource


class JobsGoSource(JobSource):
    detail_validation_version = 'jobsgo-detail-v1'
    detail_path_prefixes = ('/viec-lam/',)

    def normalize_job_url(self, url):
        return urlunsplit(('https', 'jobsgo.vn', urlsplit(url).path, '', ''))

    def extract_job_urls(self, html, listing_url):
        soup = BeautifulSoup(html, 'html.parser')
        urls = {}
        for link in soup.select('.job-list .job-title a[href]'):
            url = urljoin(listing_url, link['href'])
            parts = urlsplit(url)
            identity = job_id(url)
            if identity and parts.hostname in {'jobsgo.vn', 'www.jobsgo.vn'} and parts.scheme in {'http', 'https'}:
                urls.setdefault(identity, self.normalize_job_url(url))
        return list(urls.values())

    def extract_last_page_number(self, html, listing_url):
        soup = BeautifulSoup(html, 'html.parser')
        # Pagination is a sliding five-page window, not a last-page link.
        heading = tag_text(soup.select_one('h1')) or ''
        match = re.search(r'Tuyển dụng\s+([\d.,]+)\s+việc làm', heading)
        if not match or not soup.select_one('.pagination'):
            return None
        total = int(re.sub(r'\D', '', match.group(1)))
        return max(1, math.ceil(total / 50))

    def validate_detail_html(self, fetch_result, detail_url):
        result = super().validate_detail_html(fetch_result, detail_url)
        errors = list(result.errors)
        soup = BeautifulSoup(fetch_result.html, 'html.parser')
        posting = find_job_posting(soup) or {}
        requested = job_id(detail_url)
        if not requested or job_id(fetch_result.final_url) != requested:
            errors.append('unexpected_job_identity')
        canonical = soup.select_one('link[rel="canonical"]')
        if canonical and job_id(canonical.get('href', '')) != requested:
            errors.append('unexpected_canonical_job_identity')
        if not tag_text(soup.select_one('h1.job-title')):
            errors.append('missing_job_title')
        if not employer_name(soup, posting):
            errors.append('missing_employer_name')
        if not tag_text(section(soup, 'Mô tả công việc')):
            errors.append('missing_job_description')
        return replace(result, is_valid=not errors, errors=errors)

