from bs4 import BeautifulSoup, Tag

from joblake.parsing.base import JobParser
from joblake.parsing.common import (
    clean_items,
    tag_text,
    text_without_leading_heading,
)
from joblake.parsing.models import ParseContext, ParsedJob, ParserOutput


class ITviecParser(JobParser):
    source = "itviec"
    version = "1.0.1"

    def parse(
        self,
        html: str,
        context: ParseContext,
    ) -> ParserOutput:
        del context
        soup = BeautifulSoup(html, "html.parser")

        description_container = _find_section(
            soup,
            "Job description",
        )
        requirements_container = _find_section(
            soup,
            "Your skills and experience",
        )
        benefits_container = _find_section(
            soup,
            "Why you'll love working here",
        )

        return ParserOutput(
            job=ParsedJob(
                title=tag_text(
                    soup.select_one("div.job-header-info h1")
                ),
                employer_name_raw=tag_text(
                    soup.select_one(
                        "div.job-header-info > div.employer-name"
                    )
                ),
                description_text=text_without_leading_heading(
                    description_container,
                    "Job description",
                ),
                requirements_text=text_without_leading_heading(
                    requirements_container,
                    "Your skills and experience",
                ),
                benefits_text=_clean_benefits_text(
                    text_without_leading_heading(
                        benefits_container,
                        "Why you'll love working here",
                    )
                ),
                domains_raw=clean_items(
                    element.get_text(" ", strip=True)
                    for element in soup.select(
                        "div.itag.bg-light-grey.itag-sm.cursor-default"
                    )
                ),
                categories_raw=_linked_values_after_label(
                    soup,
                    "Job Expertise:",
                ),
                skills_raw=_linked_values_after_label(
                    soup,
                    "Skills:",
                ),
                benefit_items=clean_items(
                    element.get_text(" ", strip=True)
                    for element in (
                        benefits_container.select("li")
                        if benefits_container
                        else ()
                    )
                ),
            )
        )


def _find_section(
    soup: BeautifulSoup,
    heading_text: str,
) -> Tag | None:
    heading = next(
        (
            element
            for element in soup.select("h2")
            if tag_text(element) == heading_text
        ),
        None,
    )
    if heading is None:
        return None

    return heading.find_parent("div", class_="imy-5 paragraph")


def _linked_values_after_label(
    soup: BeautifulSoup,
    label_text: str,
) -> tuple[str, ...]:
    label = next(
        (
            element
            for element in soup.select("div")
            if tag_text(element) == label_text
        ),
        None,
    )
    if label is None:
        return ()

    sibling = label.find_next_sibling("div")
    if sibling is None:
        return ()

    return clean_items(
        element.get_text(" ", strip=True)
        for element in sibling.select(
            'a[data-controller="utm-tracking"][href^="/it-jobs/"]'
        )
    )


def _clean_benefits_text(value: str | None) -> str | None:
    if not value:
        return None
    lines = [line for line in value.splitlines() if line.strip() != "-"]
    cleaned = "\n".join(lines).strip()
    return cleaned or None
