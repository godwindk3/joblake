import os
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
prefix = "raw/detail/source=itviec/"


def get_html(key):
    data = s3.get_object(
        Bucket=bucket,
        Key=key,
    )

    html = data["Body"].read().decode("utf-8")
    return BeautifulSoup(html, "html.parser")


def parse_job(soup):
    errors = []

    # =========================
    # Title
    # =========================

    title_element = soup.select_one(
        "div.job-header-info h1"
    )

    if title_element:
        title = title_element.get_text(" ", strip=True)
    else:
        title = None
        errors.append("title")

    # =========================
    # Job domains
    # =========================

    job_domains = [
        element.get_text(" ", strip=True)
        for element in soup.select(
            "div.itag.bg-light-grey.itag-sm.cursor-default"
        )
    ]

    if not job_domains:
        errors.append("job_domains")

    # =========================
    # Job category
    # =========================

    label = soup.find(
        "div",
        string=lambda text:
            text and text.strip() == "Job Expertise:"
    )

    if label:
        sibling = label.find_next_sibling("div")

        if sibling:
            job_category = [
                a.get_text(" ", strip=True)
                for a in sibling.select(
                    'a[data-controller="utm-tracking"][href^="/it-jobs/"]'
                )
            ]
        else:
            job_category = []
    else:
        job_category = []

    if not job_category:
        errors.append("job_category")

    # =========================
    # Job description
    # =========================

    heading = soup.find(
        "h2",
        string=lambda text:
            text and text.strip() == "Job description"
    )

    if heading:
        container = heading.find_parent(
            "div",
            class_="imy-5 paragraph"
        )

        job_description = (
            container.get_text("\n", strip=True)
            if container
            else None
        )
    else:
        job_description = None

    if not job_description:
        errors.append("job_description")

    # =========================
    # Skills & experience
    # =========================

    heading = soup.find(
        "h2",
        string=lambda text:
            text and text.strip() == "Your skills and experience"
    )

    if heading:
        container = heading.find_parent(
            "div",
            class_="imy-5 paragraph"
        )

        skills_experience = (
            container.get_text("\n", strip=True)
            if container
            else None
        )
    else:
        skills_experience = None

    if not skills_experience:
        errors.append("skills_experience")

    # =========================
    # Skills
    # =========================

    label = soup.find(
        "div",
        string=lambda text:
            text and text.strip() == "Skills:"
    )

    if label:
        sibling = label.find_next_sibling("div")

        if sibling:
            skills = [
                a.get_text(" ", strip=True)
                for a in sibling.select(
                    'a[data-controller="utm-tracking"][href^="/it-jobs/"]'
                )
            ]
        else:
            skills = []
    else:
        skills = []

    if not skills:
        errors.append("skills")

    # =========================
    # Benefits
    # =========================

    heading = soup.find(
        "h2",
        string=lambda text:
            text and text.strip() == "Why you'll love working here"
    )

    if heading:
        container = heading.find_parent(
            "div",
            class_="imy-5 paragraph"
        )

        benefits = (
            container.get_text("\n", strip=True)
            if container
            else None
        )
    else:
        benefits = None

    if not benefits:
        errors.append("benefits")

    # =========================
    # Employer
    # =========================

    employer_element = soup.select_one(
        "div.job-header-info > div.employer-name"
    )

    if employer_element:
        employer = employer_element.get_text(" ", strip=True)
    else:
        employer = None
        errors.append("employer")

    return {
        "title": title,
        "employer": employer,
        "job_domains": job_domains,
        "job_category": job_category,
        "job_description": job_description,
        "skills_experience": skills_experience,
        "skills": skills,
        "benefits": benefits,
        "errors": errors,
    }


def md_list(items):
    if not items:
        return "_None_"

    return "\n".join(
        f"- {item}"
        for item in items
    )


# ============================================================
# Scan toàn bộ MinIO
# ============================================================

paginator = s3.get_paginator("list_objects_v2")

jobs = []

for page in paginator.paginate(
    Bucket=bucket,
    Prefix=prefix,
):
    for obj in page.get("Contents", []):
        key = obj["Key"]

        try:
            soup = get_html(key)
            job = parse_job(soup)

            job["key"] = key
            jobs.append(job)

        except Exception as e:
            jobs.append({
                "key": key,
                "title": None,
                "employer": None,
                "job_domains": [],
                "job_category": [],
                "job_description": None,
                "skills_experience": None,
                "skills": [],
                "benefits": None,
                "errors": [f"exception: {e}"],
            })


# ============================================================
# Generate Markdown
# ============================================================

valid_count = sum(
    1 for job in jobs
    if not job["errors"]
)

invalid_count = len(jobs) - valid_count

with open(
    "itviec_validation_report.md",
    "w",
    encoding="utf-8",
) as f:

    f.write("# ITviec Job Validation Report\n\n")

    f.write("## Summary\n\n")
    f.write(f"- Total jobs: **{len(jobs)}**\n")
    f.write(f"- Valid: **{valid_count}**\n")
    f.write(f"- Invalid: **{invalid_count}**\n\n")

    f.write("---\n\n")

    for index, job in enumerate(jobs, start=1):

        status = (
            "✅ VALID"
            if not job["errors"]
            else "❌ INVALID"
        )

        f.write(
            f"## {index}. "
            f"{job['title'] or 'UNKNOWN TITLE'}\n\n"
        )

        f.write(f"**Status:** {status}\n\n")

        f.write(f"**File:** `{job['key']}`\n\n")

        if job["errors"]:
            f.write(
                "**Missing / Errors:** "
                + ", ".join(
                    f"`{error}`"
                    for error in job["errors"]
                )
                + "\n\n"
            )

        f.write("### Employer\n\n")
        f.write(
            f"{job['employer'] or '_None_'}\n\n"
        )

        f.write("### Job Domains\n\n")
        f.write(
            md_list(job["job_domains"])
            + "\n\n"
        )

        f.write("### Job Category\n\n")
        f.write(
            md_list(job["job_category"])
            + "\n\n"
        )

        f.write("### Job Description\n\n")

        if job["job_description"]:
            f.write(
                f"> {job['job_description'].replace(chr(10), chr(10) + '> ')}\n\n"
            )
        else:
            f.write("_None_\n\n")

        f.write("### Skills & Experience\n\n")

        if job["skills_experience"]:
            f.write(
                f"> {job['skills_experience'].replace(chr(10), chr(10) + '> ')}\n\n"
            )
        else:
            f.write("_None_\n\n")

        f.write("### Skills\n\n")
        f.write(
            md_list(job["skills"])
            + "\n\n"
        )

        f.write("### Benefits\n\n")

        if job["benefits"]:
            f.write(
                f"> {job['benefits'].replace(chr(10), chr(10) + '> ')}\n\n"
            )
        else:
            f.write("_None_\n\n")

        f.write("---\n\n")


print("Report generated:")
print("itviec_validation_report.md")
print(f"Total: {len(jobs)}")
print(f"Valid: {valid_count}")
print(f"Invalid: {invalid_count}")
