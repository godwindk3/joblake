import re
from html.parser import HTMLParser
from urllib.parse import urlsplit

from joblake.block_detection import detect_block_reason
from joblake.models import FetchResult, ValidationResult


class _ValidationHTMLParser(HTMLParser):

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.elements: list[
            tuple[str, dict[str, str | None]]
        ] = []
        self.text_parts: list[str] = []
        self._ignored_depth = 0

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
        self.elements.append((tag, attributes))

        if tag in {"script", "style"}:
            self._ignored_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if (
            tag.lower() in {"script", "style"}
            and self._ignored_depth
        ):
            self._ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth and data.strip():
            self.text_parts.append(data.strip())

    def has_selector(self, selector: str) -> bool:
        match = re.fullmatch(
            (
                r"(?P<tag>[a-zA-Z][\w-]*)?"
                r"(?P<id>#[\w-]+)?"
                r"(?P<class>\.[\w-]+)?"
                r"(?:\[(?P<attr>[\w:-]+)"
                r"(?:=(?P<quote>['\"]?)"
                r"(?P<value>[^\]'\"]+)(?P=quote))?"
                r"\])?"
            ),
            selector.strip(),
        )

        if match is None:
            raise ValueError(
                "Unsupported validation selector: "
                f"{selector}"
            )

        expected_tag = match.group("tag")
        expected_id = (
            match.group("id")[1:]
            if match.group("id")
            else None
        )
        expected_class = (
            match.group("class")[1:]
            if match.group("class")
            else None
        )
        expected_attr = match.group("attr")
        expected_value = match.group("value")

        for tag, attrs in self.elements:
            if expected_tag and tag != expected_tag.lower():
                continue

            if expected_id and attrs.get("id") != expected_id:
                continue

            if expected_class:
                classes = set(
                    (attrs.get("class") or "").split()
                )

                if expected_class not in classes:
                    continue

            if (
                expected_attr
                and expected_attr.lower() not in attrs
            ):
                continue

            if (
                expected_attr
                and expected_value is not None
                and attrs.get(expected_attr.lower())
                != expected_value
            ):
                continue

            return True

        return False

    @property
    def visible_text(self) -> str:
        return " ".join(self.text_parts)


def validate_detail_html(
    *,
    fetch_result: FetchResult,
    detail_url: str,
    validation_config: dict,
    validation_version: str,
    required_path_prefixes: tuple[str, ...] = (),
) -> ValidationResult:
    """Validate that a response is usable raw detail HTML."""
    errors: list[str] = []
    warnings: list[str] = []
    html = fetch_result.html
    html_bytes = html.encode("utf-8")

    if fetch_result.status_code != 200:
        errors.append("unexpected_http_status")

    content_type = (
        fetch_result.content_type or ""
    ).lower()

    if content_type and "text/html" not in content_type:
        errors.append("unexpected_content_type")

    if not html.strip():
        errors.append("empty_html")

    min_html_bytes = int(
        validation_config.get("min_html_bytes", 1)
    )

    if len(html_bytes) < min_html_bytes:
        errors.append("html_too_small")

    block_reason = detect_block_reason(
        fetch_result.status_code,
        html,
    )

    if block_reason:
        errors.append(
            "blocked:"
            + block_reason.lower().replace(" ", "_")
        )

    requested = urlsplit(detail_url)
    final = urlsplit(fetch_result.final_url)
    allowed_hosts = {
        host.lower()
        for host in validation_config.get(
            "allowed_hosts",
            [requested.hostname or ""],
        )
        if host
    }
    final_host = (final.hostname or "").lower()

    if allowed_hosts and final_host not in allowed_hosts:
        errors.append("unexpected_final_host")

    configured_prefixes = tuple(
        validation_config.get(
            "required_path_prefixes",
            required_path_prefixes,
        )
    )

    if (
        configured_prefixes
        and not final.path.startswith(configured_prefixes)
    ):
        errors.append("unexpected_final_path")

    parser = _ValidationHTMLParser()
    parser.feed(html)
    parser.close()
    visible_text = parser.visible_text
    min_text_chars = int(
        validation_config.get("min_text_chars", 1)
    )

    if len(visible_text) < min_text_chars:
        errors.append("visible_text_too_short")

    required_selectors = list(
        validation_config.get(
            "required_selectors",
            [],
        )
    )

    for selector in required_selectors:
        if not parser.has_selector(selector):
            errors.append(
                f"missing_required_selector:{selector}"
            )

    optional_selectors = list(
        validation_config.get(
            "optional_selectors",
            [],
        )
    )

    for selector in optional_selectors:
        if not parser.has_selector(selector):
            warnings.append(
                f"missing_optional_selector:{selector}"
            )

    metrics: dict[str, int | str | bool] = {
        "html_bytes": len(html_bytes),
        "visible_text_chars": len(visible_text),
        "required_selector_count": len(
            required_selectors
        ),
        "final_host": final_host,
    }

    return ValidationResult(
        is_valid=not errors,
        retryable=True,
        validation_version=validation_version,
        errors=errors,
        warnings=warnings,
        metrics=metrics,
    )
