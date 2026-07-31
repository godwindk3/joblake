import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, urlunsplit

from joblake.sources.base import JobSource


class _VietnamWorksJobParser(HTMLParser):

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.urls: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if tag.lower() != "a":
            return

        attributes = {
            key.lower(): value
            for key, value in attrs
        }
        href = attributes.get("href")
        classes = set(
            (attributes.get("class") or "").split()
        )

        if (
            href
            and (
                "img_job_card" in classes
                or "-jv" in href
            )
        ):
            self.urls.append(href)


class VietnamWorksSource(JobSource):
    """VietnamWorks jobs with content-driven pagination."""

    detail_validation_version = (
        "vietnamworks-detail-v1"
    )

    def extract_job_urls(
        self,
        html: str,
        listing_url: str,
    ) -> list[str]:
        parser = _VietnamWorksJobParser()
        parser.feed(html)
        parser.close()
        urls: list[str] = []

        for href in parser.urls:
            absolute_url = urljoin(listing_url, href)

            if self._is_job_url(absolute_url):
                urls.append(
                    self.normalize_job_url(
                        absolute_url
                    )
                )

        return list(dict.fromkeys(urls))

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

        if not (
            hostname == "vietnamworks.com"
            or hostname.endswith(
                ".vietnamworks.com"
            )
        ):
            return False

        return bool(
            re.search(
                r"-\d+-jv/?$",
                parsed.path,
                flags=re.IGNORECASE,
            )
        )
