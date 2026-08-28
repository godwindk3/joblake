from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Iterator

from joblake.models import (
    DiscoveryRecord,
    FetchResult,
    ValidationResult,
)
from joblake.validation import validate_detail_html


@dataclass(frozen=True, slots=True)
class ListingRequest:
    target_name: str
    page_number: int
    url: str
    params: dict | None = None


@dataclass(frozen=True, slots=True)
class DetailRequest:
    url: str
    params: dict | None = None
    referer: str | None = None


class JobSource(ABC):
    """Website-specific behavior used by the generic pipeline."""

    detail_validation_version = "generic-detail-v1"
    detail_path_prefixes: tuple[str, ...] = ()

    def __init__(self, config: dict):
        self.config = config
        self.name = config["source"]

    def build_listing_request(
        self,
        target: dict,
        discovery_config: dict,
        page_number: int,
    ) -> ListingRequest:
        """Build one listing request for a page number."""
        pagination = discovery_config["pagination"]
        page_param = pagination["page_param"]

        return ListingRequest(
            target_name=target["name"],
            page_number=page_number,
            url=target["base_url"],
            params={
                **target.get("params", {}),
                page_param: page_number,
            },
        )

    def iter_listing_requests(
        self,
        target: dict,
        discovery_config: dict,
    ) -> Iterator[ListingRequest]:
        """Build paginated listing requests.

        This iterator is used when total_pages is configured. Override
        build_listing_request() when a source uses path-based pagination
        or another listing URL scheme.
        """
        pagination = discovery_config["pagination"]
        start_page = target.get(
            "start_page",
            pagination["start_page"],
        )
        total_pages = (
            target["total_pages"]
            if "total_pages" in target
            else pagination.get("total_pages")
        )

        if total_pages is None:
            raise ValueError(
                "total_pages is required when iterating "
                "without automatic pagination detection"
            )

        if total_pages < 1:
            raise ValueError(
                "total_pages must be at least 1"
            )

        for page_number in range(
            start_page,
            start_page + total_pages,
        ):
            yield self.build_listing_request(
                target,
                discovery_config,
                page_number,
            )

    @abstractmethod
    def extract_job_urls(
        self,
        html: str,
        listing_url: str,
    ) -> list[str]:
        """Extract absolute, de-duplicated job URLs from one listing."""
        raise NotImplementedError

    def extract_last_page_number(
        self,
        html: str,
        listing_url: str,
    ) -> int | None:
        """Return the absolute last page number, or None if unknown."""
        return None

    def normalize_job_url(self, url: str) -> str:
        """Return the stable URL identity stored in SQLite."""
        return url

    def build_detail_request(
        self,
        record: DiscoveryRecord,
    ) -> DetailRequest:
        return DetailRequest(
            url=record.url,
            referer=record.listing_url,
        )

    def validate_detail_html(
        self,
        fetch_result: FetchResult,
        detail_url: str,
    ) -> ValidationResult:
        return validate_detail_html(
            fetch_result=fetch_result,
            detail_url=detail_url,
            validation_config=(
                self.config
                .get("detail", {})
                .get("validation", {})
            ),
            validation_version=(
                self.detail_validation_version
            ),
            required_path_prefixes=(
                self.detail_path_prefixes
            ),
        )
