from html.parser import HTMLParser
from urllib.parse import (
    parse_qs,
    urljoin,
    urlsplit,
    urlunsplit,
)

from joblake.sources.base import JobSource


class _ITviecJobTitleParser(HTMLParser):

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.urls: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if tag.lower() != "h3":
            return

        attributes = {
            key.lower(): value
            for key, value in attrs
        }

        if (
            attributes.get(
                "data-search--job-selection-target"
            )
            != "jobTitle"
        ):
            return

        job_url = attributes.get("data-url")

        if job_url:
            self.urls.append(job_url)


class _ITviecPaginationParser(HTMLParser):

    _VOID_TAGS = {
        "area", "base", "br", "col", "embed", "hr", "img",
        "input", "link", "meta", "param", "source", "track", "wbr",
    }

    def __init__(self, listing_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.listing_url = listing_url
        self.page_numbers = [1]
        self.found = False
        self._depth = 0

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        tag = tag.lower()
        attributes = {
            key.lower(): value
            for key, value in attrs
        }

        if not self._depth:
            classes = set(
                (attributes.get("class") or "").split()
            )
            is_pagination = (
                tag == "div"
                and (
                    attributes.get(
                        "data-search--pagination-target"
                    )
                    == "pagination"
                    or "pagination-search-jobs" in classes
                )
            )

            if not is_pagination:
                return

            self.found = True
            self._depth = 1
            return

        if tag == "a":
            self._add_page_number(attributes.get("href"))

        if tag not in self._VOID_TAGS:
            self._depth += 1

    def handle_startendtag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if self._depth and tag.lower() == "a":
            attributes = {
                key.lower(): value
                for key, value in attrs
            }
            self._add_page_number(attributes.get("href"))

    def handle_endtag(self, tag: str) -> None:
        if self._depth:
            self._depth -= 1

    def _add_page_number(self, href: str | None) -> None:
        if not href:
            return

        absolute_url = urljoin(self.listing_url, href)
        query = parse_qs(urlsplit(absolute_url).query)

        for raw_page_number in query.get("page", []):
            try:
                page_number = int(raw_page_number)
            except (TypeError, ValueError):
                continue

            if page_number >= 1:
                self.page_numbers.append(page_number)


class ITviecSource(JobSource):
    """ITviec discovery based on job-title data attributes."""

    detail_validation_version = "itviec-detail-v1"
    detail_path_prefixes = ("/it-jobs/",)

    def extract_job_urls(
        self,
        html: str,
        listing_url: str,
    ) -> list[str]:
        parser = _ITviecJobTitleParser()
        parser.feed(html)
        parser.close()

        urls: list[str] = []

        for job_url in parser.urls:
            absolute_url = urljoin(
                listing_url,
                job_url,
            )

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
        parser = _ITviecPaginationParser(listing_url)
        parser.feed(html)
        parser.close()

        if not parser.found:
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
            hostname == "itviec.com"
            or hostname.endswith(".itviec.com")
        ) and parsed.path.startswith("/it-jobs/")
