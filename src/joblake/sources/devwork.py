"""Devwork's server-rendered /viec-lam listings and detail pages."""
import json
import re
from dataclasses import replace
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from joblake.models import FetchResult, ValidationResult
from joblake.sources.base import JobSource


_JOB_PATH = re.compile(r"/viec-lam/(\d+)/[^/?#]+/?$")
_NUXT_STATE = re.compile(
    r"window\.__NUXT__=\(function\(([^)]*)\)\{return (.*)\}\((.*)\)\);?",
    re.DOTALL,
)


def _literal_arguments(text: str) -> list:
    """Read only JSON literals and Nuxt's undefined sentinel; never run JS."""
    decoder = json.JSONDecoder()
    values = []
    position = 0
    while position < len(text):
        while position < len(text) and text[position].isspace():
            position += 1
        if text.startswith("void 0", position):
            value, position = None, position + 6
        else:
            value, position = decoder.raw_decode(text, position)
        values.append(value)
        while position < len(text) and text[position].isspace():
            position += 1
        if position == len(text):
            break
        if text[position] != ",":
            raise ValueError("Unsupported Nuxt argument")
        position += 1
    return values


class DevworkSource(JobSource):
    detail_validation_version = "devwork-detail-v2"
    detail_path_prefixes = ("/viec-lam/",)

    def extract_job_urls(self, html: str, listing_url: str) -> list[str]:
        soup = BeautifulSoup(html, "html.parser")
        urls = []
        for link in soup.select("#list-job-container .job-list a[href]"):
            url = urljoin(listing_url, link["href"])
            parts = urlsplit(url)
            if (parts.scheme in {"http", "https"}
                    and parts.hostname in {"devwork.vn", "www.devwork.vn"}
                    and _JOB_PATH.fullmatch(parts.path)):
                urls.append(self.normalize_job_url(url))
        return list(dict.fromkeys(urls))

    def normalize_job_url(self, url: str) -> str:
        return urlunsplit(("https", "devwork.vn", urlsplit(url).path.rstrip("/"), "", ""))

    def extract_last_page_number(self, html: str, listing_url: str) -> int | None:
        # Visible pagination is a sliding window, not the last page.
        soup = BeautifulSoup(html, "html.parser")
        for script in soup.find_all("script"):
            match = _NUXT_STATE.fullmatch(script.get_text().strip())
            if match is None:
                continue
            pagination = re.search(
                r"\bpagination:\{page:[^{}]+\btotal_pages:([\w$]+)\}", match[2]
            )
            if pagination is None:
                continue
            try:
                arguments = _literal_arguments(match[3])
            except (ValueError, TypeError):
                continue
            parameters = match[1].split(",")
            if len(parameters) != len(arguments):
                continue
            token = pagination[1]
            value = int(token) if token.isdigit() else dict(zip(parameters, arguments)).get(token)
            if type(value) is int and value >= 1:
                return value
        return None

    def validate_detail_html(self, fetch_result: FetchResult, detail_url: str) -> ValidationResult:
        result = super().validate_detail_html(fetch_result, detail_url)
        errors = list(result.errors)
        requested = _JOB_PATH.fullmatch(urlsplit(detail_url).path)
        final = _JOB_PATH.fullmatch(urlsplit(fetch_result.final_url).path)
        if not requested or not final or requested[1] != final[1]:
            errors.append("unexpected_job_identity")
        soup = BeautifulSoup(fetch_result.html, "html.parser")
        # Employer is an h5, with an optional company-profile link inside.
        for selector, error in (
            (".header-details h1", "missing_job_title"),
            (".header-details h5", "missing_employer_name"),
        ):
            node = soup.select_one(selector)
            if node is None or not node.get_text(strip=True):
                errors.append(error)
        content_found = False
        for heading in soup.select(".background-content-job h2.block-title"):
            if heading.get_text(strip=True) not in {"Mô tả công việc", "Yêu cầu công việc"}:
                continue
            content = heading.find_next_sibling()
            if (content is not None and "block-desc" in content.get("class", [])
                    and content.get_text(strip=True)):
                content_found = True
        if not content_found:
            errors.append("missing_job_description")
        return replace(result, is_valid=not errors, errors=errors)
