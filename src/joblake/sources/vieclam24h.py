from dataclasses import replace
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from joblake.parsing.common import html_fragment_to_text, tag_text
from joblake.parsing.vieclam24h_html import api_data, job_id, rendered_content, response_data
from joblake.sources.base import JobSource


class Vieclam24hSource(JobSource):
    detail_validation_version = 'vieclam24h-detail-v1'

    def normalize_job_url(self, url):
        return urlunsplit(('https', 'vieclam24h.vn', urlsplit(url).path, '', ''))

    def extract_job_urls(self, html, listing_url):
        soup = BeautifulSoup(html, 'html.parser')
        data = response_data(api_data(soup), 'getJobList')
        # Restrict links to actual result IDs, excluding promoted/recommended
        # jobs elsewhere on the page without excluding cross-category results.
        ids = {str(item.get('id')) for item in data.get('items', []) if isinstance(item, dict)}
        urls = {}
        for link in soup.select('a[href]'):
            url = urljoin(listing_url, link['href'])
            parts = urlsplit(url)
            identity = job_id(url)
            if (identity in ids and parts.hostname in {'vieclam24h.vn', 'www.vieclam24h.vn'}
                    and parts.scheme in {'http', 'https'}):
                urls.setdefault(identity, self.normalize_job_url(url))
        return list(urls.values())

    def extract_last_page_number(self, html, listing_url):
        data = response_data(api_data(BeautifulSoup(html, 'html.parser')), 'getJobList')
        last = data.get('total_pages')
        return last if type(last) is int and last >= 1 else None

    def validate_detail_html(self, fetch_result, detail_url):
        result = super().validate_detail_html(fetch_result, detail_url)
        errors = list(result.errors)
        soup = BeautifulSoup(fetch_result.html, 'html.parser')
        job = response_data(api_data(soup), 'jobDetailHiddenContact')
        requested = job_id(detail_url)
        if not requested or job_id(fetch_result.final_url) != requested or str(job.get('id')) != requested:
            errors.append('unexpected_job_identity')
        if job.get('canonical') and job_id(job['canonical']) != requested:
            errors.append('unexpected_canonical_job_identity')
        title = tag_text(soup.select_one('h1'))
        if not title or ' '.join(title.split()).casefold() != ' '.join(str(job.get('title') or '').split()).casefold():
            errors.append('missing_or_mismatched_job_title')
        employer = job.get('employer_info') or {}
        if not isinstance(employer, dict) or not str(employer.get('name') or '').strip():
            errors.append('missing_employer_name')
        if not rendered_content(soup) or not any(html_fragment_to_text(job.get(k)) for k in ('description', 'description_html', 'other_requirement', 'other_requirement_html')):
            errors.append('missing_job_description')
        return replace(result, is_valid=not errors, errors=errors)
