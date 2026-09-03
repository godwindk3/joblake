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


_INFERRED_CATEGORY = "IT / Phần mềm"


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


def _section_container(
    soup: BeautifulSoup,
    titles: tuple[str, ...],
) -> Tag | None:
    expected = tuple(title.casefold() for title in titles)

    for heading in soup.find_all(["span", "h2", "h3", "h4"]):
        heading_text = clean_text(heading.get_text(" ", strip=True))
        if not heading_text:
            continue
        normalized = heading_text.casefold()
        if not any(title in normalized for title in expected):
            continue

        sibling = heading.find_next_sibling(True)
        if isinstance(sibling, Tag):
            return sibling

        parent = heading.parent
        if isinstance(parent, Tag):
            sibling = parent.find_next_sibling(True)
            if isinstance(sibling, Tag):
                return sibling

    return None


def _section_text(
    soup: BeautifulSoup,
    titles: tuple[str, ...],
) -> str | None:
    return tag_text(_section_container(soup, titles))


def _structured_text(value: Any) -> str | None:
    if isinstance(value, str):
        return html_fragment_to_text(value)
    return json_string(value)


class TopDevParser(JobParser):
    source = "topdev"
    version = "1.0.1"

    def parse(
        self,
        html: str,
        context: ParseContext,
    ) -> ParserOutput:
        del context
        soup = BeautifulSoup(html, "html.parser")
        job_posting = find_job_posting(soup)

        issues: list[ParseIssue] = [
            ParseIssue(
                field="categories_raw",
                severity="info",
                code="inferred_category",
                message=(
                    "TopDev does not expose a reliable job category; "
                    f"using {_INFERRED_CATEGORY!r}."
                ),
            )
        ]

        if job_posting is None:
            issues.append(ParseIssue(
                field=None,
                severity="error",
                code="job_posting_json_ld_not_found",
                message="No JobPosting JSON-LD object was found.",
            ))
            return ParserOutput(
                job=ParsedJob(
                    title=tag_text(soup.select_one("h1")),
                    categories_raw=(_INFERRED_CATEGORY,),
                    source_variant="unknown",
                ),
                issues=tuple(issues),
            )

        organization = job_posting.get("hiringOrganization")
        employer = (
            clean_text(organization.get("name"))
            if isinstance(organization, dict)
            else clean_text(organization)
        )

        description_text = _section_text(
            soup,
            ("Your role & responsibilities",),
        ) or html_fragment_to_text(job_posting.get("description"))

        experience_raw = _structured_text(
            job_posting.get("experienceRequirements")
        )
        requirements_text = _section_text(
            soup,
            ("Your skills & qualifications",),
        ) or experience_raw

        benefits_container = _section_container(
            soup,
            ("Benefits for you", "Benefits"),
        )
        raw_benefits = job_posting.get("jobBenefits")
        benefits_text = tag_text(benefits_container)
        benefit_items = (
            clean_items(
                item.get_text(" ", strip=True)
                for item in benefits_container.select("li")
            )
            if benefits_container is not None
            else ()
        )
        if not benefits_text:
            benefits_text = html_fragment_to_text(raw_benefits)
        if not benefit_items:
            benefit_items = html_fragment_items(raw_benefits)
        if not benefit_items and benefits_text:
            benefit_items = clean_items(benefits_text.splitlines())

        job = ParsedJob(
            title=clean_text(job_posting.get("title")),
            employer_name_raw=employer,
            description_text=description_text,
            requirements_text=requirements_text,
            benefits_text=benefits_text,
            domains_raw=_named_values(job_posting.get("industry")),
            categories_raw=(_INFERRED_CATEGORY,),
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
        return ParserOutput(job=job, issues=tuple(issues))
