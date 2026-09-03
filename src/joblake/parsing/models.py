from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class ParseContext:
    source: str
    canonical_url: str
    crawler_job_id: int
    raw_object_id: int
    fetched_at: str


@dataclass(frozen=True, slots=True)
class ParseIssue:
    field: str | None
    severity: str
    code: str
    message: str

    def __post_init__(self) -> None:
        if self.severity not in {"info", "warning", "error"}:
            raise ValueError(
                "ParseIssue severity must be info, warning, or error"
            )

    def as_dict(self) -> dict[str, str | None]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ParsedJob:
    title: str | None = None
    employer_name_raw: str | None = None
    description_text: str | None = None
    requirements_text: str | None = None
    benefits_text: str | None = None
    domains_raw: tuple[str, ...] = ()
    categories_raw: tuple[str, ...] = ()
    skills_raw: tuple[str, ...] = ()
    benefit_items: tuple[str, ...] = ()
    locations_raw: tuple[str, ...] = ()
    source_external_job_id: str | None = None
    source_variant: str | None = None
    salary_raw: str | None = None
    employment_type_raw: str | None = None
    experience_raw: str | None = None
    posted_at: datetime | None = None
    expires_at: datetime | None = None
    source_payload: dict[str, Any] = field(default_factory=dict)

    def parsed_field_count(self) -> int:
        values = (
            self.title,
            self.employer_name_raw,
            self.description_text,
            self.requirements_text,
            self.benefits_text,
            self.domains_raw,
            self.categories_raw,
            self.skills_raw,
            self.benefit_items,
            self.locations_raw,
            self.source_external_job_id,
            self.source_variant,
            self.salary_raw,
            self.employment_type_raw,
            self.experience_raw,
            self.posted_at,
            self.expires_at,
        )
        return sum(bool(value) for value in values)


@dataclass(frozen=True, slots=True)
class ParserOutput:
    job: ParsedJob
    issues: tuple[ParseIssue, ...] = ()


@dataclass(frozen=True, slots=True)
class QualityAssessment:
    status: str
    completeness_score: int
    missing_required_fields: tuple[str, ...]
    missing_recommended_fields: tuple[str, ...]
    issues: tuple[ParseIssue, ...]

    @property
    def is_accepted(self) -> bool:
        return self.status in {"accepted", "partial"}

    def issue_dicts(self) -> list[dict[str, str | None]]:
        return [issue.as_dict() for issue in self.issues]
