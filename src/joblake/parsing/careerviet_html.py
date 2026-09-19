"""Rendered fields shared by CareerViet validation and parsing."""
from bs4 import BeautifulSoup

from joblake.parsing.common import clean_text, tag_text


def detail_title(soup: BeautifulSoup, posting: dict) -> str | None:
    title = tag_text(soup.select_one('.apply-now-banner h1.title'))
    if title:
        return title
    # Branded templates use h2 or an unclassed h1. Match visible text to
    # the structured job title, rather than accepting an unrelated heading.
    expected = clean_text(posting.get('title'))
    if expected:
        normalized = ' '.join(expected.split()).casefold()
        for heading in soup.select('h1, h2'):
            text = tag_text(heading)
            if text and ' '.join(text.split()).casefold() == normalized:
                return text
    return None


def detail_sections(soup: BeautifulSoup) -> dict[str, str]:
    sections = {}
    for heading in soup.select('h2.detail-title, h3.detail-title'):
        label = heading.get_text(' ', strip=True).casefold()
        if label not in {'mô tả công việc', 'yêu cầu công việc', 'phúc lợi', 'thông tin khác'}:
            continue
        content = heading.find_next_sibling()
        if content is None and 'title-icon' in heading.parent.get('class', []):
            content = heading.parent.find_next_sibling()
        # Never swallow the following section if this one has no body.
        if content is None or content.select_one('.detail-title') or 'detail-title' in content.get('class', []):
            continue
        text = tag_text(content)
        if text:
            sections.setdefault(label, text)
    return sections
