import re
from typing import Any

from bs4 import BeautifulSoup, Tag

from joblake.parsing.base import JobParser
from joblake.parsing.common import (
    clean_items,
    clean_text,
    find_job_posting,
    html_fragment_items,
    html_fragment_to_text,
    json_ld_identifier,
    json_ld_locations,
    json_string,
    parse_datetime,
    split_comma_values,
    tag_text,
)
from joblake.parsing.models import (
    ParseContext,
    ParseIssue,
    ParsedJob,
    ParserOutput,
)


_BENEFIT_HEADING_RE = re.compile(
    r"(?im)^\s*(?:"
    r"quyền\s+lợi(?:\s+và\s+chế\s+độ)?|"
    r"phúc\s+lợi|"
    r"chế\s+độ\s+đãi\s+ngộ|"
    r"benefits?|"
    r"what\s+we\s+offer|"
    r"why\s+you(?:'|’)?ll\s+love\s+working\s+here|"
    r"vì\s+sao\s+nên\s+cân\s+nhắc\s+cơ\s+hội\s+này|"
    r"vì\s+sao\s+đây\s+là\s+cơ\s+hội\s+đáng\s+cân\s+nhắc"
    r")\s*(?:[:.!?\-]|$)"
)


def _named_values(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return split_comma_values(value)
    if not isinstance(value, list):
        return ()

    values: list[Any] = []
    for item in value:
        if isinstance(item, dict):
            values.append(
                item.get("skillName")
                or item.get("name")
                or item.get("value")
            )
        else:
            values.append(item)
    return clean_items(values)


def _job_domains(soup: BeautifulSoup) -> tuple[str, ...]:
    values: list[str] = []

    for label in soup.find_all("label"):
        label_text = clean_text(label.get_text(" ", strip=True))
        if not label_text or label_text.casefold() != "ngành nghề":
            continue

        sibling = label.find_next_sibling(True)
        if isinstance(sibling, Tag):
            value = clean_text(sibling.get_text(" ", strip=True))
            if value:
                values.append(value)
                continue

        parent = label.parent
        if isinstance(parent, Tag):
            sibling = parent.find_next_sibling(True)
            if isinstance(sibling, Tag):
                value = clean_text(sibling.get_text(" ", strip=True))
                if value:
                    values.append(value)

    return clean_items(values)


def _has_title_banner(tag: Tag) -> bool:
    candidates = [tag, *tag.find_all(True)]
    return any(
        any(
            "title-banner" in css_class
            for css_class in element.get("class", [])
        )
        for element in candidates
    )


def _heading(
    soup: BeautifulSoup,
    titles: tuple[str, ...],
) -> Tag | None:
    expected = {title.casefold() for title in titles}
    for candidate in soup.find_all(["h2", "h3", "h4"]):
        text = clean_text(candidate.get_text(" ", strip=True))
        if text and text.casefold() in expected:
            return candidate
    return None


def _content_after_heading(heading: Tag | None) -> Tag | None:
    if heading is None:
        return None

    for sibling in heading.find_next_siblings():
        if not isinstance(sibling, Tag):
            continue
        if sibling.name in {"h2", "h3", "h4"}:
            break
        if _has_title_banner(sibling):
            continue
        return sibling
    return None


def _section_text(container: Tag | None) -> str | None:
    if container is None:
        return None

    paragraphs = container.find_all("p")
    if paragraphs:
        return clean_text("\n".join(
            text
            for paragraph in paragraphs
            if (text := clean_text(
                paragraph.get_text(" ", strip=True)
            ))
        ))
    return tag_text(container)


def _truncate_before_benefits(value: str | None) -> str | None:
    if not value:
        return None
    match = _BENEFIT_HEADING_RE.search(value)
    if match:
        return clean_text(value[:match.start()])
    return clean_text(value)


def _benefit_items(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return html_fragment_items(value)
    if not isinstance(value, list):
        return ()

    items: list[Any] = []
    for item in value:
        if isinstance(item, dict):
            items.append(
                item.get("benefitNameVI")
                or item.get("benefitName")
                or item.get("benefitValue")
                or item.get("name")
            )
        else:
            items.append(item)
    return clean_items(items)


def _benefits_text(value: Any) -> str | None:
    if isinstance(value, str):
        return html_fragment_to_text(value)
    items = _benefit_items(value)
    return clean_text("\n".join(items)) if items else None


def _structured_text(value: Any) -> str | None:
    if isinstance(value, str):
        return html_fragment_to_text(value)
    return json_string(value)


class VietnamWorksParser(JobParser):
    source = "vietnamworks"
    version = "1.0.1"

    def parse(
        self,
        html: str,
        context: ParseContext,
    ) -> ParserOutput:
        del context
        soup = BeautifulSoup(html, "html.parser")
        job_posting = find_job_posting(soup)

        if job_posting is None:
            return ParserOutput(
                job=ParsedJob(
                    title=tag_text(soup.select_one("h1")),
                    source_variant="unknown",
                ),
                issues=(ParseIssue(
                    field=None,
                    severity="error",
                    code="job_posting_json_ld_not_found",
                    message="No JobPosting JSON-LD object was found.",
                ),),
            )

        organization = job_posting.get("hiringOrganization")
        employer = (
            clean_text(organization.get("name"))
            if isinstance(organization, dict)
            else clean_text(organization)
        )

        requirements_container = _content_after_heading(_heading(
            soup,
            ("Yêu cầu công việc",),
        ))
        requirements_text = _truncate_before_benefits(
            _section_text(requirements_container)
        )
        experience_raw = _structured_text(
            job_posting.get("experienceRequirements")
        )
        if not requirements_text:
            requirements_text = experience_raw

        raw_benefits = job_posting.get("jobBenefits")
        benefit_items = _benefit_items(raw_benefits)
        benefits_text = _benefits_text(raw_benefits)
        if not benefits_text:
            benefits_container = _content_after_heading(_heading(
                soup,
                (
                    "Quyền lợi",
                    "Quyền lợi và chế độ",
                    "Phúc lợi",
                    "Benefits",
                ),
            ))
            benefits_text = _section_text(benefits_container)
            if benefits_container is not None:
                benefit_items = clean_items(
                    item.get_text(" ", strip=True)
                    for item in benefits_container.select("li")
                )
        if not benefit_items and benefits_text:
            benefit_items = clean_items(benefits_text.splitlines())

        job = ParsedJob(
            title=clean_text(job_posting.get("title")),
            employer_name_raw=employer,
            description_text=html_fragment_to_text(
                job_posting.get("description")
            ),
            requirements_text=requirements_text,
            benefits_text=benefits_text,
            domains_raw=_job_domains(soup),
            categories_raw=_named_values(job_posting.get("industry")),
            skills_raw=_named_values(job_posting.get("skills")),
            benefit_items=benefit_items,
            locations_raw=json_ld_locations(job_posting),
            source_external_job_id=json_ld_identifier(job_posting),
            source_variant="normal",
            salary_raw=json_string(job_posting.get("baseSalary")),
            employment_type_raw=json_string(
                job_posting.get("employmentType")
            ),
            experience_raw=experience_raw,
            posted_at=parse_datetime(job_posting.get("datePosted")),
            expires_at=parse_datetime(job_posting.get("validThrough")),
            source_payload={"job_posting_json_ld": job_posting},
        )
        return ParserOutput(job=job)
