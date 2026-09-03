import json
import re
from datetime import datetime
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup, NavigableString, Tag


_SPACE_RE = re.compile(r"[\t\r\f\v ]+")
_INLINE_SPACE_RE = re.compile(r"\s+")
_SPACE_BEFORE_PUNCTUATION_RE = re.compile(r"\s+([,.;:!?%])")
_INVISIBLE_CHARACTERS_RE = re.compile(r"[\u200b\u200c\u200d\ufeff]")
_VIETNAM_TIMEZONE = ZoneInfo("Asia/Ho_Chi_Minh")

_BLOCK_TAGS = frozenset({
    "address",
    "article",
    "blockquote",
    "dd",
    "div",
    "dl",
    "dt",
    "figcaption",
    "figure",
    "footer",
    "header",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "li",
    "main",
    "ol",
    "p",
    "pre",
    "section",
    "table",
    "tbody",
    "td",
    "tfoot",
    "th",
    "thead",
    "tr",
    "ul",
})
_IGNORED_TEXT_TAGS = frozenset({
    "script",
    "style",
    "noscript",
    "template",
})


def clean_text(value: Any) -> str | None:
    if value is None:
        return None

    text = _INVISIBLE_CHARACTERS_RE.sub(
        "",
        str(value).replace("\xa0", " "),
    )
    lines: list[str] = []

    for raw_line in text.splitlines():
        line = _SPACE_RE.sub(" ", raw_line).strip()
        line = _SPACE_BEFORE_PUNCTUATION_RE.sub(r"\1", line)
        if line and (not lines or line != lines[-1]):
            lines.append(line)

    return "\n".join(lines) or None


def tag_text(tag: Tag | None) -> str | None:
    if tag is None:
        return None
    return _html_node_to_text(tag)


def text_without_leading_heading(
    container: Tag | None,
    heading: str,
) -> str | None:
    text = tag_text(container)
    cleaned_heading = clean_text(heading)

    if not text or not cleaned_heading:
        return text

    lines = text.splitlines()
    if lines and lines[0].casefold() == cleaned_heading.casefold():
        lines = lines[1:]
    return clean_text("\n".join(lines))


def clean_items(values: Iterable[Any]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()

    for value in values:
        cleaned = clean_text(value)
        if not cleaned:
            continue
        identity = cleaned.casefold()
        if identity in seen:
            continue
        seen.add(identity)
        result.append(cleaned)

    return tuple(result)


def split_comma_values(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return clean_items(value.split(","))
    if isinstance(value, list):
        return clean_items(value)
    return ()


def html_fragment_to_text(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    fragment = BeautifulSoup(value, "html.parser")
    return _html_node_to_text(fragment)


def html_fragment_items(value: Any) -> tuple[str, ...]:
    if not isinstance(value, str) or not value.strip():
        return ()
    fragment = BeautifulSoup(value, "html.parser")
    items = clean_items(
        tag_text(element)
        for element in fragment.select("li")
    )
    if items:
        return items
    text = _html_node_to_text(fragment)
    return clean_items(text.splitlines()) if text else ()


def _html_node_to_text(node: Tag | BeautifulSoup) -> str | None:
    """Render HTML as compact text while retaining meaningful block breaks.

    BeautifulSoup's ``get_text("\n")`` inserts a newline at every nested
    inline element. Job pages frequently wrap ordinary words in ``span`` or
    ``strong`` elements, which made one visual sentence appear as many sparse
    database lines. This walker joins inline text with spaces and only starts
    a new line for semantic blocks, list items, and explicit ``br`` tags.
    """
    lines: list[str] = []
    inline_parts: list[str] = []

    def flush_line() -> None:
        if not inline_parts:
            return
        line = clean_text(" ".join(inline_parts))
        inline_parts.clear()
        if line:
            lines.append(line)

    def add_text(value: str) -> None:
        compact = _INLINE_SPACE_RE.sub(
            " ",
            _INVISIBLE_CHARACTERS_RE.sub(
                "",
                value.replace("\xa0", " "),
            ),
        ).strip()
        if compact:
            inline_parts.append(compact)

    def walk(current: object) -> None:
        if isinstance(current, NavigableString):
            add_text(str(current))
            return
        if not isinstance(current, Tag):
            return

        name = (current.name or "").casefold()
        if name in _IGNORED_TEXT_TAGS:
            return
        if name == "br":
            flush_line()
            return

        is_block = name in _BLOCK_TAGS
        if is_block:
            flush_line()
        for child in current.children:
            walk(child)
        if is_block:
            flush_line()

    walk(node)
    # The requested node can itself be inline (for example, an employer
    # link). In that case no block boundary calls ``flush_line``.
    flush_line()
    return clean_text("\n".join(lines))


def json_ld_objects(soup: BeautifulSoup) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []

    for script in soup.select('script[type="application/ld+json"]'):
        raw = script.string or script.get_text()
        if not raw or not raw.strip():
            continue
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        _collect_json_ld_objects(data, objects)

    return objects


def _collect_json_ld_objects(
    value: Any,
    output: list[dict[str, Any]],
) -> None:
    if isinstance(value, list):
        for item in value:
            _collect_json_ld_objects(item, output)
        return

    if not isinstance(value, dict):
        return

    graph = value.get("@graph")
    if isinstance(graph, list):
        for item in graph:
            _collect_json_ld_objects(item, output)
        return

    output.append(value)


def find_job_posting(
    soup: BeautifulSoup,
) -> dict[str, Any] | None:
    objects = json_ld_objects(soup)

    for obj in objects:
        obj_type = obj.get("@type")
        types = obj_type if isinstance(obj_type, list) else [obj_type]
        if "JobPosting" in types:
            return obj

    for obj in objects:
        if obj.get("title") and obj.get("description"):
            return obj

    return None


def parse_datetime(value: Any) -> datetime | None:
    cleaned = clean_text(value)
    if not cleaned:
        return None
    candidate = cleaned.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=_VIETNAM_TIMEZONE)
    return parsed


def json_string(value: Any) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, str):
        return clean_text(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def json_ld_identifier(job_posting: dict[str, Any]) -> str | None:
    identifier = job_posting.get("identifier")
    if isinstance(identifier, dict):
        return clean_text(
            identifier.get("value") or identifier.get("name")
        )
    return clean_text(identifier)


def json_ld_locations(
    job_posting: dict[str, Any],
) -> tuple[str, ...]:
    raw_locations = job_posting.get("jobLocation")
    locations = (
        raw_locations
        if isinstance(raw_locations, list)
        else [raw_locations]
    )
    values: list[str] = []

    for location in locations:
        if not isinstance(location, dict):
            continue
        address = location.get("address")
        if isinstance(address, str):
            values.append(address)
            continue
        if not isinstance(address, dict):
            continue
        parts = [
            address.get("streetAddress"),
            address.get("addressLocality"),
            address.get("addressRegion"),
            address.get("addressCountry"),
        ]
        cleaned_parts = [clean_text(part) for part in parts]
        value = ", ".join(part for part in cleaned_parts if part)
        if value:
            values.append(value)

    return clean_items(values)
