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
prefix = "raw/detail/source=topcv/"


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
# Detect job type
# =============================================================

def detect_job_type(soup):

    if soup.select_one("div#job-detail"):
        return "normal"

    if soup.select_one(
        "h2.premium-job-basic-information__content--title"
    ):
        return "premium"

    return "unknown"


# =============================================================
# Common
# =============================================================

def get_job_category(soup):

    for group in soup.select(
        "div.job-tags__group"
    ):
        group_name = group.select_one(
            ".job-tags__group-name"
        )

        if not group_name:
            continue

        group_name_text = group_name.get_text(
            " ",
            strip=True
        )

        if "Chuyên môn:" in group_name_text:

            return [
                item.get_text(
                    " ",
                    strip=True
                )
                for item in group.select(
                    "a.item"
                )
                if item.get_text(
                    " ",
                    strip=True
                )
            ]

    return []


# =============================================================
# Normal TopCV
# =============================================================

def parse_normal_job(soup):

    errors = []

    # ---------------------------------------------------------
    # Title
    # ---------------------------------------------------------

    title_element = soup.select_one(
        "div#job-detail"
    )

    if title_element and title_element.get(
        "data-job-title"
    ):
        title = title_element[
            "data-job-title"
        ].strip()

    else:
        title = None
        errors.append("title")

    # ---------------------------------------------------------
    # Employer
    # ---------------------------------------------------------

    employer_element = soup.select_one(
        "div.box-company-info__detail a.name"
    )

    if employer_element:
        employer = employer_element.get_text(
            " ",
            strip=True
        )

    else:
        employer = None
        errors.append("employer")

    # ---------------------------------------------------------
    # Job domains
    # ---------------------------------------------------------

    breadcrumb_links = soup.select(
        "div.ctn-breadcrumb-detail a"
    )

    breadcrumb_texts = [
        a.get_text(
            " ",
            strip=True
        )
        for a in breadcrumb_links
        if a.get_text(
            " ",
            strip=True
        )
    ]

    if len(breadcrumb_texts) >= 3:
        job_domains = breadcrumb_texts[1:-1]

    else:
        job_domains = []
        errors.append("job_domains")

    # ---------------------------------------------------------
    # Job category
    # ---------------------------------------------------------

    job_category = get_job_category(
        soup
    )

    if not job_category:
        errors.append("job_category")

    # ---------------------------------------------------------
    # Information sections
    # ---------------------------------------------------------

    job_description = None
    skills_experience = None
    benefits = None

    information_items = soup.select(
        "div.box-job-information-detail-item"
    )

    for item in information_items:

        heading = item.select_one(
            "h2.box-job-information-detail-item__title--title"
        )

        if not heading:
            continue

        heading_text = heading.get_text(
            " ",
            strip=True
        )

        content = item.select_one(
            "div.box-job-information-detail-item__text"
        )

        if not content:
            continue

        text = content.get_text(
            "\n",
            strip=True
        )

        if heading_text == "Mô tả công việc":
            job_description = text

        elif heading_text == "Yêu cầu ứng viên":
            skills_experience = text

        elif heading_text == "Quyền lợi ứng viên":
            benefits = text

    if not job_description:
        errors.append("job_description")

    if not skills_experience:
        errors.append("skills_experience")

    if not benefits:
        errors.append("benefits")

    return {
        "job_type": "normal",
        "title": title,
        "employer": employer,
        "job_domains": job_domains,
        "job_category": job_category,
        "job_description": job_description,
        "skills_experience": skills_experience,
        "benefits": benefits,
        "errors": errors,
    }


# =============================================================
# Premium TopCV
# =============================================================

def parse_premium_job(soup):

    errors = []

    # ---------------------------------------------------------
    # Title
    # ---------------------------------------------------------

    title_element = soup.select_one(
        "h2.premium-job-basic-information__content--title"
    )

    if title_element:

        # Remove verified icon
        icon = title_element.select_one(
            ".icon-verified-employer"
        )

        if icon:
            icon.decompose()

        title = title_element.get_text(
            " ",
            strip=True
        )

    else:
        title = None
        errors.append("title")

    # ---------------------------------------------------------
    # Employer
    # ---------------------------------------------------------

    employer_element = soup.select_one(
        "a.company-content__name h1.title"
    )

    if employer_element:
        employer = employer_element.get_text(
            " ",
            strip=True
        )

    else:
        employer = None
        errors.append("employer")

    # ---------------------------------------------------------
    # Job domains
    # ---------------------------------------------------------

    meta_keywords = soup.select_one(
        'meta[name="keywords"]'
    )

    if meta_keywords:
        job_domains = meta_keywords.get(
            "content",
            ""
        ).strip()

    else:
        job_domains = None
        errors.append("job_domains")

    # ---------------------------------------------------------
    # Job category
    # ---------------------------------------------------------

    job_category = get_job_category(
        soup
    )

    if not job_category:
        errors.append("job_category")

    # ---------------------------------------------------------
    # Information sections
    # ---------------------------------------------------------

    job_description = None
    skills_experience = None
    benefits = None

    information_boxes = soup.select(
        "div.premium-job-description__box"
    )

    for box in information_boxes:

        heading = box.select_one(
            "h2.premium-job-description__box--title"
        )

        content = box.select_one(
            "div.premium-job-description__box--content"
        )

        if not heading or not content:
            continue

        heading_text = heading.get_text(
            " ",
            strip=True
        )

        text = content.get_text(
            "\n",
            strip=True
        )

        if heading_text == "Mô tả công việc":
            job_description = text

        elif heading_text == "Yêu cầu ứng viên":
            skills_experience = text

        elif heading_text == "Quyền lợi ứng viên":
            benefits = text

    if not job_description:
        errors.append("job_description")

    if not skills_experience:
        errors.append("skills_experience")

    if not benefits:
        errors.append("benefits")

    return {
        "job_type": "premium",
        "title": title,
        "employer": employer,
        "job_domains": job_domains,
        "job_category": job_category,
        "job_description": job_description,
        "skills_experience": skills_experience,
        "benefits": benefits,
        "errors": errors,
    }


# =============================================================
# Main parser
# =============================================================

def parse_job(soup):

    job_type = detect_job_type(
        soup
    )

    if job_type == "normal":
        return parse_normal_job(
            soup
        )

    elif job_type == "premium":
        return parse_premium_job(
            soup
        )

    else:
        return {
            "job_type": "unknown",
            "title": None,
            "employer": None,
            "job_domains": [],
            "job_category": [],
            "job_description": None,
            "skills_experience": None,
            "benefits": None,
            "errors": ["unknown_job_type"],
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
                "job_domains": [],
                "job_category": [],
                "job_description": None,
                "skills_experience": None,
                "benefits": None,
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

normal_count = sum(
    1
    for job in jobs
    if job["job_type"] == "normal"
)

premium_count = sum(
    1
    for job in jobs
    if job["job_type"] == "premium"
)

unknown_count = sum(
    1
    for job in jobs
    if job["job_type"] == "unknown"
)


# =============================================================
# Generate Markdown
# =============================================================

with open(
    "topcv_validation_report.md",
    "w",
    encoding="utf-8",
) as f:

    f.write(
        "# TopCV Job Validation Report\n\n"
    )

    f.write(
        "## Summary\n\n"
    )

    f.write(
        f"- Total jobs: **{len(jobs)}**\n"
    )

    f.write(
        f"- Normal jobs: **{normal_count}**\n"
    )

    f.write(
        f"- Premium jobs: **{premium_count}**\n"
    )

    f.write(
        f"- Unknown jobs: **{unknown_count}**\n"
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
            f"**Type:** `{job['job_type']}`\n\n"
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

        # Domains

        f.write(
            "### Job Domains\n\n"
        )

        f.write(
            md_list(
                job["job_domains"]
            )
            + "\n\n"
        )

        # Category

        f.write(
            "### Job Category\n\n"
        )

        f.write(
            md_list(
                job["job_category"]
            )
            + "\n\n"
        )

        # Description

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

        # Skills & Experience

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
    "topcv_validation_report.md"
)

print(
    f"Total:   {len(jobs)}"
)

print(
    f"Normal:  {normal_count}"
)

print(
    f"Premium: {premium_count}"
)

print(
    f"Unknown: {unknown_count}"
)

print(
    f"Valid:   {valid_count}"
)

print(
    f"Invalid: {invalid_count}"
)