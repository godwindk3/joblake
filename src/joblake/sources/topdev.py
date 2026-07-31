import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, urlunsplit

from joblake.sources.base import JobSource


class _TopDevParser(HTMLParser):

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.job_urls: list[str] = []
        self.page_numbers: list[int] = []
        self._page_link_depth = 0
        self._page_link_text: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        tag = tag.lower()

        if self._page_link_depth:
            self._page_link_depth += 1
            return

        if tag != "a":
            return

        attributes = {
            key.lower(): value
            for key, value in attrs
        }
        href = attributes.get("href")

        if href:
            self.job_urls.append(href)

        aria_label = attributes.get("aria-label") or ""
        label_match = re.search(
            r"\b(?:go\s+to\s+)?page\s+(\d+)\b",
            aria_label,
            flags=re.IGNORECASE,
        )

        if label_match:
            self.page_numbers.append(
                int(label_match.group(1))
            )

        classes = set(
            (attributes.get("class") or "").split()
        )

        if {"h-8", "w-8"}.issubset(classes):
            self._page_link_depth = 1
            self._page_link_text = []

    def handle_data(self, data: str) -> None:
        if self._page_link_depth:
            self._page_link_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if not self._page_link_depth:
            return

        self._page_link_depth -= 1

        if self._page_link_depth:
            return

        text = "".join(
            self._page_link_text
        ).strip()

        if text.isdigit():
            page_number = int(text)

            if page_number >= 1:
                self.page_numbers.append(page_number)

        self._page_link_text = []


class TopDevSource(JobSource):
    """TopDev jobs and numeric pagination controls."""

    detail_validation_version = "topdev-detail-v1"
    detail_path_prefixes = ("/detail-jobs/",)

    def extract_job_urls(
        self,
        html: str,
        listing_url: str,
    ) -> list[str]:
        parser = _TopDevParser()
        parser.feed(html)
        parser.close()
        urls: list[str] = []

        for href in parser.job_urls:
            absolute_url = urljoin(listing_url, href)

            if self._is_job_url(absolute_url):
                urls.append(
                    self.normalize_job_url(
                        absolute_url
                    )
                )

        return list(dict.fromkeys(urls))

    def extract_last_page_number(
        self,
        html: str,
        listing_url: str,
    ) -> int | None:
        del listing_url
        parser = _TopDevParser()
        parser.feed(html)
        parser.close()

        if not parser.page_numbers:
            return None

        return max(parser.page_numbers)

    def normalize_job_url(self, url: str) -> str:
        parts = urlsplit(url)
        return urlunsplit(
            (
                parts.scheme,
                parts.netloc,
                parts.path,
                "",
                "",
            )
        )

    @staticmethod
    def _is_job_url(url: str) -> bool:
        parsed = urlsplit(url)
        hostname = (parsed.hostname or "").lower()

        return (
            hostname == "topdev.vn"
            or hostname.endswith(".topdev.vn")
        ) and parsed.path.startswith("/detail-jobs/")
