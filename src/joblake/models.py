from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FetchResult:
    requested_url: str
    final_url: str
    status_code: int | None
    content_type: str | None
    fetched_at: str
    html: str


@dataclass(frozen=True, slots=True)
class DiscoveryRecord:
    source: str
    url: str
    target_name: str
    listing_url: str
    listing_page: int
    discovered_at: str


class FetchError(Exception):
    """Không thể fetch URL nhưng có thể thử lại ở lần chạy sau."""


class SourceBlockedError(FetchError):
    """Nguồn trả về Cloudflare challenge hoặc chặn crawler."""


class PaginationDetectionError(Exception):
    """Không thể xác định trang cuối khi bật auto-pagination."""
