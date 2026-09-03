from bs4 import BeautifulSoup, Tag

from joblake.parsing.base import JobParser
from joblake.parsing.common import (
    clean_items,
    clean_text,
    split_comma_values,
    tag_text,
    text_without_leading_heading,
)
from joblake.parsing.models import (
    ParseContext,
    ParseIssue,
    ParsedJob,
    ParserOutput,
)


class TopCVParser(JobParser):
    source = "topcv"
    version = "1.0.2"

    def parse(
        self,
        html: str,
        context: ParseContext,
    ) -> ParserOutput:
        del context
        soup = BeautifulSoup(html, "html.parser")
        variant = _detect_variant(soup)

        if variant == "normal":
            return ParserOutput(job=_parse_normal(soup))
        if variant == "premium":
            return ParserOutput(job=_parse_premium(soup))

        return ParserOutput(
            job=ParsedJob(source_variant="unknown"),
            issues=(
                ParseIssue(
                    field=None,
                    severity="error",
                    code="unknown_layout",
                    message="TopCV page layout could not be identified",
                ),
            ),
        )


def _detect_variant(soup: BeautifulSoup) -> str:
    if soup.select_one("div#job-detail") is not None:
        return "normal"
    if soup.select_one(
        "h2.premium-job-basic-information__content--title"
    ) is not None:
        return "premium"
    return "unknown"


def _parse_normal(soup: BeautifulSoup) -> ParsedJob:
    detail = soup.select_one("div#job-detail")
    title = clean_text(detail.get("data-job-title")) if detail else None

    breadcrumb_values = clean_items(
        element.get_text(" ", strip=True)
        for element in soup.select("div.ctn-breadcrumb-detail a")
    )
    domains = (
        breadcrumb_values[1:-1]
        if len(breadcrumb_values) >= 3
        else ()
    )
    sections = _normal_sections(soup)

    return ParsedJob(
        title=title,
        employer_name_raw=tag_text(
            soup.select_one("div.box-company-info__detail a.name")
        ),
        description_text=sections.get("Mô tả công việc"),
        requirements_text=sections.get("Yêu cầu ứng viên"),
        benefits_text=sections.get("Quyền lợi ứng viên"),
        domains_raw=domains,
        categories_raw=_job_categories(soup),
        source_variant="normal",
    )


def _parse_premium(soup: BeautifulSoup) -> ParsedJob:
    title_element = soup.select_one(
        "h2.premium-job-basic-information__content--title"
    )
    if title_element is not None:
        verified_icon = title_element.select_one(".icon-verified-employer")
        if verified_icon is not None:
            verified_icon.decompose()

    keywords = soup.select_one('meta[name="keywords"]')
    keyword_content = keywords.get("content") if keywords else None
    sections = _premium_sections(soup)

    return ParsedJob(
        title=tag_text(title_element),
        employer_name_raw=tag_text(
            soup.select_one("a.company-content__name h1.title")
        ),
        description_text=sections.get("Mô tả công việc"),
        requirements_text=sections.get("Yêu cầu ứng viên"),
        benefits_text=sections.get("Quyền lợi ứng viên"),
        domains_raw=split_comma_values(keyword_content),
        categories_raw=_job_categories(soup),
        source_variant="premium",
    )


def _job_categories(soup: BeautifulSoup) -> tuple[str, ...]:
    for group in soup.select("div.job-tags__group"):
        group_name = tag_text(group.select_one(".job-tags__group-name"))
        if group_name and "Chuyên môn:" in group_name:
            return clean_items(
                element.get_text(" ", strip=True)
                for element in group.select("a.item")
            )
    return ()


def _normal_sections(soup: BeautifulSoup) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in soup.select("div.box-job-information-detail-item"):
        heading = item.select_one(
            "h2.box-job-information-detail-item__title--title"
        )
        content = item.select_one(
            "div.box-job-information-detail-item__text"
        )
        _add_section(result, heading, content)
    return result


def _premium_sections(soup: BeautifulSoup) -> dict[str, str]:
    result: dict[str, str] = {}
    for box in soup.select("div.premium-job-description__box"):
        heading = box.select_one(
            "h2.premium-job-description__box--title"
        )
        content = box.select_one(
            "div.premium-job-description__box--content"
        )
        _add_section(result, heading, content)
    return result


def _add_section(
    result: dict[str, str],
    heading: Tag | None,
    content: Tag | None,
) -> None:
    heading_text = tag_text(heading)
    if not heading_text or content is None:
        return
    section_text = text_without_leading_heading(content, heading_text)
    if section_text:
        result[heading_text] = section_text
