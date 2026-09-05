from dataclasses import dataclass, field


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


@dataclass(frozen=True, slots=True)
class ValidationResult:
    is_valid: bool
    retryable: bool
    validation_version: str
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metrics: dict[str, int | str | bool] = field(
        default_factory=dict
    )

    def as_dict(self) -> dict:
        return {
            "valid": self.is_valid,
            "retryable": self.retryable,
            "validation_version": self.validation_version,
            "errors": self.errors,
            "warnings": self.warnings,
            "metrics": self.metrics,
        }


class FetchError(Exception):
    """Không thể fetch URL nhưng có thể thử lại ở lần chạy sau."""


class HttpStatusError(FetchError):
    """HTTP response không thành công, kèm metadata để lưu state."""

    def __init__(self, fetch_result: FetchResult):
        self.fetch_result = fetch_result
        super().__init__(
            f"HTTP status {fetch_result.status_code}: "
            f"{fetch_result.final_url}"
        )

    @property
    def status_code(self) -> int | None:
        return self.fetch_result.status_code


class SourceBlockedError(FetchError):
    """Nguồn trả về Cloudflare challenge hoặc chặn crawler."""


class PaginationDetectionError(Exception):
    """Không thể xác định trang cuối khi bật auto-pagination."""


class StorageIntegrityError(Exception):
    """Stored object did not match its expected size or hash."""
