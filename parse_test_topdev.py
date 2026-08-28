import os
import json
from dotenv import load_dotenv
from bs4 import BeautifulSoup
import boto3

load_dotenv()

MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY")

s3 = boto3.client(
    "s3",
    endpoint_url="http://localhost:9000",
    aws_access_key_id=MINIO_ACCESS_KEY,
    aws_secret_access_key=MINIO_SECRET_KEY,
)

bucket = "joblake"
prefix = "raw/detail/source=topdev/"


# =============================================================
# MinIO
# =============================================================

def get_html(key):
    data = s3.get_object(
        Bucket=bucket,
        Key=key,
    )

    html = data["Body"].read().decode("utf-8")

    return BeautifulSoup(
        html,
        "html.parser"
    )


# =============================================================
# JSON-LD
# =============================================================

def get_job_posting_jsonld(soup):
    """
    Tìm script JSON-LD có @type = JobPosting
    """

    scripts = soup.select(
        'script[type="application/ld+json"]'
    )

    for script in scripts:

        try:
            data = json.loads(
                script.string or script.get_text()
            )

        except (json.JSONDecodeError, TypeError):
            continue

        # JSON-LD có thể là object
        if isinstance(data, dict):

            if data.get("@type") == "JobPosting":
                return data

        # Hoặc đôi khi là list
        elif isinstance(data, list):

            for item in data:

                if (
                    isinstance(item, dict)
                    and item.get("@type") == "JobPosting"
                ):
                    return item

    return None


# =============================================================
# Extract JSON-LD fields
# =============================================================

def parse_jsonld(job_posting, errors):

    # ---------------------------------------------------------
    # Title
    # ---------------------------------------------------------

    title = job_posting.get("title")

    if isinstance(title, str):
        title = title.strip()

    if not title:
        errors.append("title")

    # ---------------------------------------------------------
    # Employer
    # ---------------------------------------------------------

    hiring_organization = job_posting.get(
        "hiringOrganization"
    )

    employer = None

    if isinstance(
        hiring_organization,
        dict
    ):
        employer = hiring_organization.get(
            "name"
        )

    if isinstance(employer, str):
        employer = employer.strip()

    if not employer:
        errors.append("employer")

    # ---------------------------------------------------------
    # Job domains
    # ---------------------------------------------------------

    job_domains = job_posting.get(
        "industry"
    )

    if isinstance(job_domains, str):
        job_domains = job_domains.strip()

    if not job_domains:
        errors.append("job_domains")

    # ---------------------------------------------------------
    # Skills
    # ---------------------------------------------------------

    skills_raw = job_posting.get(
        "skills"
    )

    if isinstance(skills_raw, str):

        skills = [
            skill.strip()
            for skill in skills_raw.split(",")
            if skill.strip()
        ]

    elif isinstance(skills_raw, list):

        skills = [
            str(skill).strip()
            for skill in skills_raw
            if str(skill).strip()
        ]

    else:
        skills = []

    if not skills:
        errors.append("skills")

    return {
        "title": title,
        "employer": employer,
        "job_domains": job_domains,
        "skills": skills,
    }


# =============================================================
# HTML sections
# =============================================================

def get_section_content(
    soup,
    section_titles
):
    """
    Tìm span title và lấy div ngay sau nó.
    """

    spans = soup.select(
        "span.text-\\[\\#3659B3\\].font-semibold"
    )

    for span in spans:

        text = span.get_text(
            " ",
            strip=True
        )

        for section_title in section_titles:

            if section_title in text:

                # next sibling
                sibling = span.find_next_sibling()

                if sibling:

                    return sibling.get_text(
                        "\n",
                        strip=True
                    )

    return None


# =============================================================
# Parse HTML sections
# =============================================================

def parse_html_sections(
    soup,
    errors
):

    # ---------------------------------------------------------
    # Job description
    # ---------------------------------------------------------

    job_description = get_section_content(
        soup,
        [
            "Your role & responsibilities"
        ]
    )

    if not job_description:
        errors.append(
            "job_description"
        )

    # ---------------------------------------------------------
    # Skills & experience
    # ---------------------------------------------------------

    skills_experience = get_section_content(
        soup,
        [
            "Your skills & qualifications"
        ]
    )

    if not skills_experience:
        errors.append(
            "skills_experience"
        )

    # ---------------------------------------------------------
    # Benefits
    # ---------------------------------------------------------

    benefits = get_section_content(
        soup,
        [
            "Benefits for you",
            "Benefits",
        ]
    )

    if not benefits:
        errors.append(
            "benefits"
        )

    return {
        "job_description": job_description,
        "skills_experience": skills_experience,
        "benefits": benefits,
    }


# =============================================================
# Main parser
# =============================================================

def parse_job(soup):

    errors = []

    # ---------------------------------------------------------
    # JobPosting JSON-LD
    # ---------------------------------------------------------

    job_posting = get_job_posting_jsonld(
        soup
    )

    if not job_posting:

        return {
            "job_type": "unknown",
            "title": None,
            "employer": None,
            "job_domains": None,
            "job_category": "IT / Phần mềm",
            "job_description": None,
            "skills_experience": None,
            "benefits": None,
            "skills": [],
            "errors": [
                "JobPosting JSON-LD not found"
            ],
        }

    # ---------------------------------------------------------
    # JSON-LD fields
    # ---------------------------------------------------------

    jsonld_data = parse_jsonld(
        job_posting,
        errors
    )

    # ---------------------------------------------------------
    # HTML fields
    # ---------------------------------------------------------

    html_data = parse_html_sections(
        soup,
        errors
    )

    # ---------------------------------------------------------
    # Job category
    # ---------------------------------------------------------
    # TopDev doesn't have a reliable category field.
    # Temporarily use default value.
    # Do NOT treat this as an error.

    job_category = "IT / Phần mềm"

    # ---------------------------------------------------------
    # Result
    # ---------------------------------------------------------

    return {
        "job_type": "normal",
        "title": jsonld_data["title"],
        "employer": jsonld_data["employer"],
        "job_domains": jsonld_data["job_domains"],
        "job_category": job_category,
        "job_description": html_data[
            "job_description"
        ],
        "skills_experience": html_data[
            "skills_experience"
        ],
        "benefits": html_data[
            "benefits"
        ],
        "skills": jsonld_data["skills"],
        "errors": errors,
    }


# =============================================================
# Markdown helper
# =============================================================

def md_list(items):

    if not items:
        return "_None_"

    if isinstance(items, str):
        return f"- {items}"

    return "\n".join(
        f"- {item}"
        for item in items
    )


# =============================================================
# Scan MinIO
# =============================================================

paginator = s3.get_paginator(
    "list_objects_v2"
)

jobs = []

for page in paginator.paginate(
    Bucket=bucket,
    Prefix=prefix,
):

    for obj in page.get(
        "Contents",
        []
    ):

        key = obj["Key"]

        try:

            soup = get_html(
                key
            )

            job = parse_job(
                soup
            )

            job["key"] = key

            jobs.append(
                job
            )

        except Exception as e:

            jobs.append({
                "key": key,
                "job_type": "unknown",
                "title": None,
                "employer": None,
                "job_domains": None,
                "job_category": "IT / Phần mềm",
                "job_description": None,
                "skills_experience": None,
                "benefits": None,
                "skills": [],
                "errors": [
                    f"exception: {e}"
                ],
            })


# =============================================================
# Statistics
# =============================================================

valid_count = sum(
    1
    for job in jobs
    if not job["errors"]
)

invalid_count = (
    len(jobs)
    - valid_count
)


# =============================================================
# Generate Markdown report
# =============================================================

with open(
    "topdev_validation_report.md",
    "w",
    encoding="utf-8",
) as f:

    f.write(
        "# TopDev Job Validation Report\n\n"
    )

    f.write(
        "## Summary\n\n"
    )

    f.write(
        f"- Total jobs: **{len(jobs)}**\n"
    )

    f.write(
        f"- Valid: **{valid_count}**\n"
    )

    f.write(
        f"- Invalid: **{invalid_count}**\n\n"
    )

    f.write(
        "---\n\n"
    )

    # ---------------------------------------------------------
    # Individual jobs
    # ---------------------------------------------------------

    for index, job in enumerate(
        jobs,
        start=1
    ):

        status = (
            "✅ VALID"
            if not job["errors"]
            else "❌ INVALID"
        )

        f.write(
            f"## {index}. "
            f"{job['title'] or 'UNKNOWN TITLE'}\n\n"
        )

        f.write(
            f"**Status:** {status}\n\n"
        )

        f.write(
            f"**File:** `{job['key']}`\n\n"
        )

        if job["errors"]:

            f.write(
                "**Missing / Errors:** "
                + ", ".join(
                    f"`{error}`"
                    for error in job["errors"]
                )
                + "\n\n"
            )

        # Employer

        f.write(
            "### Employer\n\n"
        )

        f.write(
            f"{job['employer'] or '_None_'}\n\n"
        )

        # Job domains

        f.write(
            "### Job Domains\n\n"
        )

        f.write(
            md_list(
                job["job_domains"]
            )
            + "\n\n"
        )

        # Job category

        f.write(
            "### Job Category\n\n"
        )

        f.write(
            md_list(
                job["job_category"]
            )
            + "\n\n"
        )

        # Job description

        f.write(
            "### Job Description\n\n"
        )

        if job["job_description"]:

            text = job[
                "job_description"
            ]

            f.write(
                "> "
                + text.replace(
                    "\n",
                    "\n> "
                )
                + "\n\n"
            )

        else:

            f.write(
                "_None_\n\n"
            )

        # Skills & experience

        f.write(
            "### Skills & Experience\n\n"
        )

        if job["skills_experience"]:

            text = job[
                "skills_experience"
            ]

            f.write(
                "> "
                + text.replace(
                    "\n",
                    "\n> "
                )
                + "\n\n"
            )

        else:

            f.write(
                "_None_\n\n"
            )

        # Skills

        f.write(
            "### Skills\n\n"
        )

        f.write(
            md_list(
                job["skills"]
            )
            + "\n\n"
        )

        # Benefits

        f.write(
            "### Benefits\n\n"
        )

        if job["benefits"]:

            text = job[
                "benefits"
            ]

            f.write(
                "> "
                + text.replace(
                    "\n",
                    "\n> "
                )
                + "\n\n"
            )

        else:

            f.write(
                "_None_\n\n"
            )

        f.write(
            "---\n\n"
        )


# =============================================================
# Console
# =============================================================

print(
    "Report generated:"
)

print(
    "topdev_validation_report.md"
)

print(
    f"Total:   {len(jobs)}"
)

print(
    f"Valid:   {valid_count}"
)

print(
    f"Invalid: {invalid_count}"
)