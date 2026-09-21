"""CareerViet software-category listings; public server-rendered HTML."""
import json
import re
from dataclasses import replace
from urllib.parse import parse_qs, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from joblake.models import FetchResult, ValidationResult
from joblake.parsing.common import find_job_posting, json_ld_identifier, tag_text
from joblake.parsing.careerviet_html import detail_sections, detail_title
from joblake.sources.base import JobSource, ListingRequest


JOB_PATH = re.compile(r"/vi/tim-viec-lam/[^/]+\.([0-9a-fA-F]{8})\.html$")


class CareerVietSource(JobSource):
    detail_validation_version = "careerviet-detail-v2"
    detail_path_prefixes = ("/vi/tim-viec-lam/",)

    def build_listing_request(self, target, discovery_config, page_number):
        base = target['base_url']
        path = re.sub(r"(?:-trang-\d+)?-vi\.html$", f"-trang-{page_number}-vi.html", base)
        return ListingRequest(target['name'], page_number, path)

    def normalize_job_url(self, url):
        return urlunsplit(('https', 'careerviet.vn', urlsplit(url).path, '', ''))

    def extract_job_urls(self, html, listing_url):
        soup = BeautifulSoup(html, 'html.parser')
        urls = []
        for link in soup.select('#jobs-side-list-content .job-item a.job_link[href]'):
            url = urljoin(listing_url, link['href'])
            parts = urlsplit(url)
            if (parts.scheme in {'http', 'https'}
                    and parts.hostname in {'careerviet.vn', 'www.careerviet.vn'}
                    and JOB_PATH.fullmatch(parts.path)):
                urls.append(self.normalize_job_url(url))
        return list(dict.fromkeys(urls))

    def extract_last_page_number(self, html, listing_url):
        # React Flight carries result count and page size. Never execute scripts
        # or mistake the five visible pagination buttons for the final page.
        soup = BeautifulSoup(html, 'html.parser')
        chunks = []
        for script in soup.find_all('script'):
            match = re.fullmatch(r'self\.__next_f\.push\((.*)\);?', script.get_text().strip(), re.S)
            if not match:
                continue
            try:
                payload = json.loads(match[1])
            except ValueError:
                continue
            if (isinstance(payload, list) and len(payload) == 2
                    and payload[0] == 1 and isinstance(payload[1], str)):
                chunks.append(payload[1])
        match = re.search(r'"totalJobs":(\d+),"params":"([^"\n]+)"', ''.join(chunks))
        if not match:
            return None
        params = parse_qs(match[2])
        limit = params.get('limit', [''])[0]
        if params.get('industry') != ['1'] or not limit.isdigit() or int(limit) < 1:
            return None
        total = int(match[1])
        return max(1, (total + int(limit) - 1) // int(limit))

    def validate_detail_html(self, fetch_result: FetchResult, detail_url: str) -> ValidationResult:
        result = super().validate_detail_html(fetch_result, detail_url)
        errors = list(result.errors)
        requested = JOB_PATH.fullmatch(urlsplit(detail_url).path)
        final = JOB_PATH.fullmatch(urlsplit(fetch_result.final_url).path)
        if not requested or not final or requested[1].upper() != final[1].upper():
            errors.append('unexpected_job_identity')
        soup = BeautifulSoup(fetch_result.html, 'html.parser')
        posting = find_job_posting(soup) or {}
        identity = json_ld_identifier(posting)
        if identity and requested and identity.upper() != requested[1].upper():
            errors.append('unexpected_structured_job_identity')
        # Require actual rendered title/content: a JSON-LD-only shell is incomplete.
        if not detail_title(soup, posting):
            errors.append('missing_job_title')
        organization = posting.get('hiringOrganization')
        employer = organization.get('name') if isinstance(organization, dict) else None
        if not (tag_text(soup.select_one('.apply-now-banner .job-company-name'))
                or (isinstance(employer, str) and employer.strip())):
            errors.append('missing_employer_name')
        sections = detail_sections(soup)
        if not (sections.get('mô tả công việc') or sections.get('yêu cầu công việc')):
            errors.append('missing_job_description')
        return replace(result, is_valid=not errors, errors=errors)
