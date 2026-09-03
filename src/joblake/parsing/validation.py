from joblake.parsing.models import (
    ParseIssue,
    ParserOutput,
    QualityAssessment,
)


_SCORED_FIELDS = (
    "title",
    "employer_name_raw",
    "description_text",
    "requirements_text",
    "benefits_text",
    "domains_raw",
    "categories_raw",
    "skills_raw",
)


def assess_parsed_job(
    output: ParserOutput,
) -> QualityAssessment:
    job = output.job
    issues = list(output.issues)
    missing_required: list[str] = []

    for field_name in ("title", "employer_name_raw"):
        if not getattr(job, field_name):
            missing_required.append(field_name)

    if not job.description_text and not job.requirements_text:
        missing_required.append("job_content")

    existing_error_fields = {
        issue.field
        for issue in issues
        if issue.severity == "error"
    }
    for field_name in missing_required:
        if field_name not in existing_error_fields:
            issues.append(ParseIssue(
                field=field_name,
                severity="error",
                code="missing_required_field",
                message=f"Required field is missing: {field_name}",
            ))

    recommended_fields = (
        "description_text",
        "requirements_text",
        "benefits_text",
        "domains_raw",
        "categories_raw",
        "skills_raw",
    )
    missing_recommended = [
        field_name
        for field_name in recommended_fields
        if not getattr(job, field_name)
    ]
    existing_warning_fields = {
        issue.field
        for issue in issues
        if issue.severity == "warning"
    }
    for field_name in missing_recommended:
        if field_name not in existing_warning_fields:
            issues.append(ParseIssue(
                field=field_name,
                severity="warning",
                code="missing_recommended_field",
                message=f"Recommended field is missing: {field_name}",
            ))

    present_count = sum(
        bool(getattr(job, field_name))
        for field_name in _SCORED_FIELDS
    )
    score = round(100 * present_count / len(_SCORED_FIELDS))

    if missing_required or any(
        issue.severity == "error" for issue in issues
    ):
        status = "rejected"
    elif missing_recommended or any(
        issue.severity == "warning" for issue in issues
    ):
        status = "partial"
    else:
        status = "accepted"

    return QualityAssessment(
        status=status,
        completeness_score=score,
        missing_required_fields=tuple(missing_required),
        missing_recommended_fields=tuple(missing_recommended),
        issues=tuple(issues),
    )
