from dataclasses import replace
from urllib.parse import parse_qs, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from joblake.parsing.careerlink_html import job_id, section
from joblake.parsing.common import find_job_posting, json_ld_identifier, tag_text
from joblake.sources.base import JobSource, ListingRequest


class CareerLinkSource(JobSource):
    detail_validation_version = 'careerlink-detail-v1'
    detail_path_prefixes = ('/tim-viec-lam/',)

    def build_listing_request(self, target, discovery_config, page_number):
        if page_number == 1:
            return ListingRequest(target['name'], page_number, target['base_url'], target.get('params'))
        return super().build_listing_request(target, discovery_config, page_number)

    def normalize_job_url(self, url):
        return urlunsplit(('https', 'www.careerlink.vn', urlsplit(url).path.rstrip('/'), '', ''))

    def extract_job_urls(self, html, listing_url):
        soup = BeautifulSoup(html, 'html.parser')
        urls = {}
        for link in soup.select('li.job-item a.job-link[href]'):
            url = urljoin(listing_url, link['href'])
            parts = urlsplit(url)
            identity = job_id(url)
            if identity and parts.hostname in {'careerlink.vn', 'www.careerlink.vn'} and parts.scheme in {'http', 'https'}:
                urls.setdefault(identity, self.normalize_job_url(url))
        return list(urls.values())

    def extract_last_page_number(self, html, listing_url):
        soup = BeautifulSoup(html, 'html.parser')
        pagination = soup.select_one('.pagination')
        if pagination is None:
            return None
        pages = []
        for link in pagination.select('a[href]'):
            parts = urlsplit(urljoin(listing_url, link['href']))
            if parts.hostname not in {'careerlink.vn', 'www.careerlink.vn'} or parts.path != urlsplit(listing_url).path:
                continue
            page = parse_qs(parts.query).get('page', [''])[0]
            if page.isdigit() and int(page) >= 1:
                pages.append(int(page))
        if pages:
            return max(pages)
        active = pagination.select_one('.active')
        return 1 if active and active.get_text(strip=True) == '1' else None

    def validate_detail_html(self, fetch_result, detail_url):
        result = super().validate_detail_html(fetch_result, detail_url)
        errors = list(result.errors)
        soup = BeautifulSoup(fetch_result.html, 'html.parser')
        posting = find_job_posting(soup) or {}
        requested = job_id(detail_url)
        if not requested or job_id(fetch_result.final_url) != requested:
            errors.append('unexpected_job_identity')
        identifier = json_ld_identifier(posting)
        if identifier and identifier != requested:
            errors.append('unexpected_structured_job_identity')
        if not tag_text(soup.select_one('#job-title')):
            errors.append('missing_job_title')
        organization = posting.get('hiringOrganization') or {}
        if not isinstance(organization, dict) or not str(organization.get('name') or '').strip():
            errors.append('missing_employer_name')
        if not (tag_text(section(soup, 'description')) or tag_text(section(soup, 'skill'))):
            errors.append('missing_job_description')
        return replace(result, is_valid=not errors, errors=errors)
