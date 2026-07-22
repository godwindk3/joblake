import json
import re
from html.parser import HTMLParser
from typing import Iterator
from urllib.parse import urljoin

from joblake.sources.base import JobSource


class _JsonLdParser(HTMLParser):

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.documents: list[str] = []
        self._buffer: list[str] | None = None

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if tag.lower() != "script":
            return

        attributes = {
            key.lower(): value
            for key, value in attrs
        }

        content_type = attributes.get("type")

        if (
            content_type
            and content_type.lower()
            == "application/ld+json"
        ):
            self._buffer = []

    def handle_data(self, data: str) -> None:
        if self._buffer is not None:
            self._buffer.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "script":
            return

        if self._buffer is not None:
            self.documents.append(
                "".join(self._buffer)
            )
            self._buffer = None


class _TopCVPaginationParser(HTMLParser):

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.text_parts: list[str] = []
        self.found = False
        self._depth = 0

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if self._depth:
            self._depth += 1
            return

        attributes = {
            key.lower(): value
            for key, value in attrs
        }

        if (
            tag.lower() == "span"
            and attributes.get("id")
            == "job-listing-paginate-text"
        ):
            self.found = True
            self._depth = 1

    def handle_data(self, data: str) -> None:
        if self._depth:
            self.text_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self._depth:
            self._depth -= 1

    @property
    def text(self) -> str:
        return " ".join(self.text_parts)


def _walk_json(value) -> Iterator[dict]:
    if isinstance(value, dict):
        yield value

        for child in value.values():
            yield from _walk_json(child)

    elif isinstance(value, list):
        for child in value:
            yield from _walk_json(child)


class TopCVSource(JobSource):
    """TopCV discovery based on JSON-LD ItemList records."""

    def extract_job_urls(
        self,
        html: str,
        listing_url: str,
    ) -> list[str]:
        parser = _JsonLdParser()
        parser.feed(html)
        parser.close()

        urls: list[str] = []

        for raw_json in parser.documents:
            if not raw_json.strip():
                continue

            try:
                json_data = json.loads(raw_json)
            except json.JSONDecodeError:
                continue

            for item in _walk_json(json_data):
                if item.get("@type") != "ItemList":
                    continue

                for element in item.get(
                    "itemListElement",
                    [],
                ):
                    job_url = self._element_url(element)

                    if not job_url:
                        continue

                    absolute_url = urljoin(
                        listing_url,
                        job_url,
                    )

                    if self._is_job_url(absolute_url):
                        urls.append(absolute_url)

        return list(dict.fromkeys(urls))

    def extract_last_page_number(
        self,
        html: str,
        listing_url: str,
    ) -> int | None:
        del listing_url

        parser = _TopCVPaginationParser()
        parser.feed(html)
        parser.close()

        if not parser.found:
            return None

        match = re.search(
            r"/\s*(\d+)\s*trang\b",
            parser.text.replace("\xa0", " "),
            flags=re.IGNORECASE,
        )

        if match is None:
            return None

        page_number = int(match.group(1))
        return page_number if page_number >= 1 else None

    @staticmethod
    def _element_url(element) -> str | None:
        if not isinstance(element, dict):
            return None

        job_url = element.get("url")
        nested_item = element.get("item")

        if (
            not job_url
            and isinstance(nested_item, dict)
        ):
            job_url = nested_item.get("url")

        return job_url

    @staticmethod
    def _is_job_url(url: str) -> bool:
        return "/viec-lam/" in url
