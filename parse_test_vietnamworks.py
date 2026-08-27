import os
import json
import re

from dotenv import load_dotenv
from bs4 import BeautifulSoup
import boto3


# ============================================================
# CONFIG
# ============================================================

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
prefix = "raw/detail/source=vietnamworks/"


# ============================================================
# MINIO
# ============================================================

def get_html(key):
    data = s3.get_object(
        Bucket=bucket,
        Key=key,
    )

    html = data["Body"].read().decode("utf-8")

    return BeautifulSoup(
        html,
        "html.parser",
    )


# ============================================================
# HELPERS
# ============================================================

def clean_text(text):
    """
    Normalize whitespace nhưng vẫn giữ nội dung.
    """

    if not text:
        return None

    text = text.replace("\xa0", " ")

    # Chuẩn hóa khoảng trắng
    text = re.sub(r"[ \t]+", " ", text)

    # Chuẩn hóa nhiều newline
    text = re.sub(r"\n\s*\n+", "\n\n", text)

    return text.strip()


def html_to_text(html):
    """
    Convert HTML string -> plain text.

    Giữ paragraph/list thành từng dòng.
    """

    if not html:
        return None

    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    # <br> -> newline
    for br in soup.find_all("br"):
        br.replace_with("\n")

    # <li> -> text riêng
    for li in soup.find_all("li"):
        li.insert_before("\n")
        li.insert_after("\n")

    # paragraph -> newline
    for tag in soup.find_all(
        ["p", "div"]
    ):
        tag.insert_after("\n")

    text = soup.get_text(
        " ",
        strip=True,
    )

    # Chuẩn hóa lại
    text = re.sub(
        r"\s*\n\s*",
        "\n",
        text,
    )

    text = re.sub(
        r"[ \t]+",
        " ",
        text,
    )

    return text.strip() or None


def md_list(items):
    """
    Convert list -> Markdown list.
    """

    if not items:
        return "_None_"

    if isinstance(items, str):
        return f"- {items}"

    return "\n".join(
        f"- {item}"
        for item in items
        if item
    )


# ============================================================
# JSON-LD
# ============================================================

def get_json_ld_objects(soup):
    """
    Lấy toàn bộ JSON-LD trong HTML.

    Trả về list các object JSON.
    """

    objects = []

    scripts = soup.find_all(
        "script",
        type="application/ld+json",
    )

    for script in scripts:

        raw = script.string or script.get_text()

        if not raw:
            continue

        raw = raw.strip()

        try:

            data = json.loads(raw)

        except json.JSONDecodeError:

            continue

        if isinstance(data, list):

            for item in data:

                if isinstance(item, dict):
                    objects.append(item)

        elif isinstance(data, dict):

            # Một số JSON-LD dùng @graph
            graph = data.get("@graph")

            if isinstance(graph, list):

                for item in graph:

                    if isinstance(item, dict):
                        objects.append(item)

            else:

                objects.append(data)

    return objects


def get_job_json_ld(soup):
    """
    Tìm JSON-LD JobPosting.

    Ưu tiên object có:
        @type = JobPosting
    """

    objects = get_json_ld_objects(soup)

    for obj in objects:

        obj_type = obj.get("@type")

        if isinstance(obj_type, list):

            if "JobPosting" in obj_type:
                return obj

        elif obj_type == "JobPosting":

            return obj

    # Fallback:
    # Nếu không có @type JobPosting,
    # tìm object có title + description.
    for obj in objects:

        if (
            obj.get("title")
            and obj.get("description")
        ):
            return obj

    return None


# ============================================================
# TITLE
# ============================================================

def get_title(soup, job_json):

    if not job_json:
        return None

    title = job_json.get("title")

    return clean_text(title)


# ============================================================
# EMPLOYER
# ============================================================

def get_employer(soup, job_json):

    if not job_json:
        return None

    organization = job_json.get(
        "hiringOrganization"
    )

    if isinstance(
        organization,
        dict,
    ):

        return clean_text(
            organization.get("name")
        )

    return None


# ============================================================
# JOB DOMAINS
# ============================================================

def get_job_domains(soup):

    job_domains = []

    for label in soup.find_all("label"):

        label_text = clean_text(
            label.get_text(
                " ",
                strip=True,
            )
        )

        if not label_text:
            continue

        if label_text.lower() != "ngành nghề":
            continue

        # ----------------------------------------------------
        # HTML thường có:
        #
        # <label>Ngành nghề</label>
        # <p>
        #     <span>UX/UI Design</span>
        # </p>
        # ----------------------------------------------------

        # Tìm sibling trực tiếp
        sibling = label.find_next_sibling()

        if sibling:

            value = clean_text(
                sibling.get_text(
                    " ",
                    strip=True,
                )
            )

            if value:
                job_domains.append(value)

                continue

        # ----------------------------------------------------
        # Fallback:
        # tìm element kế tiếp có nội dung
        # ----------------------------------------------------

        next_element = label.find_next()

        while next_element:

            if next_element == label:
                next_element = next_element.find_next()
                continue

            text = clean_text(
                next_element.get_text(
                    " ",
                    strip=True,
                )
            )

            if text:

                # Không lấy lại label
                if text.lower() != "ngành nghề":
                    job_domains.append(text)

                break

            next_element = next_element.find_next()

    # Remove duplicate
    return list(
        dict.fromkeys(job_domains)
    )


# ============================================================
# JOB CATEGORY
# ============================================================

def get_job_category(soup, job_json):

    """
    VietnamWorks không có field job_category
    trong JSON-LD.

    Mapping:
        job_category <- industry

    Ví dụ:
        industry = "Ngân hàng"
    """

    if not job_json:
        return []

    industry = job_json.get(
        "industry"
    )

    if not industry:
        return []

    if isinstance(
        industry,
        list,
    ):

        return [
            clean_text(x)
            for x in industry
            if clean_text(x)
        ]

    return [
        clean_text(industry)
    ]


# ============================================================
# JOB DESCRIPTION
# ============================================================

def get_job_description(soup, job_json):

    if not job_json:
        return None

    description = job_json.get(
        "description"
    )

    if not description:
        return None

    # description trong JSON-LD là HTML
    return html_to_text(
        description
    )


# ============================================================
# SKILLS & EXPERIENCE
# ============================================================

def get_skills_experience(soup):
    """
    Lấy phần "Yêu cầu công việc" từ HTML.

    Banner ("Mức độ phù hợp...") và nội dung thật
    là 2 sibling div ĐỘC LẬP của <h2>, không lồng
    vào nhau — nên phải duyệt qua tất cả sibling
    và loại bỏ div nào chứa class chứa "title-banner"
    (thực tế trên trang là "title-banner-c").
    """

    heading = None

    for h2 in soup.find_all("h2"):

        text = clean_text(
            h2.get_text(" ", strip=True)
        )

        if text == "Yêu cầu công việc":
            heading = h2
            break

    if not heading:
        return None

    def has_title_banner(tag):
        for el in tag.find_all(True):
            classes = el.get("class") or []
            if any("title-banner" in cls for cls in classes):
                return True
        return False

    content = None

    for sibling in heading.find_next_siblings("div"):

        if has_title_banner(sibling):
            continue

        content = sibling
        break

    if not content:
        return None

    parts = []

    paragraphs = content.find_all("p")

    if paragraphs:
        for p in paragraphs:
            text = clean_text(p.get_text(" ", strip=True))
            if text:
                parts.append(text)
    else:
        text = clean_text(content.get_text("\n", strip=True))
        if text:
            parts.append(text)

    cleaned_parts = []

    for text in parts:
        if not text:
            continue
        if not cleaned_parts or text != cleaned_parts[-1]:
            cleaned_parts.append(text)

    if not cleaned_parts:
        return None

    return "\n\n".join(cleaned_parts)

# ============================================================
# SKILLS
# ============================================================

def get_skills(soup, job_json):

    if not job_json:
        return []

    skills = job_json.get(
        "skills"
    )

    if not skills:
        return []

    # --------------------------------------------------------
    # JSON-LD thường:
    #
    # "Qualitative Research, Usability Testing,
    #  Customer Journey Map, Ux Research, Customer Insight"
    # --------------------------------------------------------

    if isinstance(
        skills,
        str,
    ):

        return [
            skill.strip()
            for skill in skills.split(",")
            if skill.strip()
        ]

    # --------------------------------------------------------
    # Fallback nếu skills đã là list
    # --------------------------------------------------------

    if isinstance(
        skills,
        list,
    ):

        result = []

        for skill in skills:

            if isinstance(
                skill,
                str,
            ):

                value = clean_text(skill)

                if value:
                    result.append(value)

            elif isinstance(
                skill,
                dict,
            ):

                value = (
                    skill.get("skillName")
                    or skill.get("name")
                )

                if value:
                    result.append(
                        clean_text(value)
                    )

        return result

    return []


# ============================================================
# BENEFITS
# ============================================================

def get_benefits(soup, job_json):

    if not job_json:
        return []

    benefits = job_json.get(
        "jobBenefits"
    )

    if not benefits:
        return []

    # --------------------------------------------------------
    # JSON-LD:
    #
    # "jobBenefits":
    # "<ul><li>...</li><li>...</li></ul>"
    # --------------------------------------------------------

    if isinstance(
        benefits,
        str,
    ):

        benefit_soup = BeautifulSoup(
            benefits,
            "html.parser",
        )

        result = []

        # Ưu tiên <li>
        for li in benefit_soup.find_all("li"):

            text = clean_text(
                li.get_text(
                    " ",
                    strip=True,
                )
            )

            if text:
                result.append(text)

        if result:
            return result

        # Fallback nếu không có <li>
        text = clean_text(
            benefit_soup.get_text(
                "\n",
                strip=True,
            )
        )

        if text:
            return [
                line.strip()
                for line in text.split("\n")
                if line.strip()
            ]

    # --------------------------------------------------------
    # Fallback nếu jobBenefits là list
    # --------------------------------------------------------

    if isinstance(
        benefits,
        list,
    ):

        result = []

        for benefit in benefits:

            if isinstance(
                benefit,
                str,
            ):

                value = clean_text(
                    benefit
                )

                if value:
                    result.append(value)

            elif isinstance(
                benefit,
                dict,
            ):

                value = (
                    benefit.get("benefitNameVI")
                    or benefit.get("benefitName")
                    or benefit.get("benefitValue")
                )

                if value:
                    result.append(
                        clean_text(value)
                    )

        return result

    return []


# ============================================================
# PARSE ONE JOB
# ============================================================

def parse_job(soup):

    # --------------------------------------------------------
    # Get JSON-LD JobPosting once
    # --------------------------------------------------------

    job_json = get_job_json_ld(
        soup
    )

    # --------------------------------------------------------
    # Extract fields
    # --------------------------------------------------------

    return {

        "title": get_title(
            soup,
            job_json,
        ),

        "employer": get_employer(
            soup,
            job_json,
        ),

        "job_domains": get_job_domains(
            soup,
        ),

        "job_category": get_job_category(
            soup,
            job_json,
        ),

        "job_description": get_job_description(
            soup,
            job_json,
        ),

        "skills_experience": get_skills_experience(
            soup,
        ),

        "skills": get_skills(
            soup,
            job_json,
        ),

        "benefits": get_benefits(
            soup,
            job_json,
        ),
    }


# ============================================================
# LIST ALL OBJECTS
# ============================================================

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
        [],
    ):

        key = obj["Key"]

        try:

            soup = get_html(key)

            job = parse_job(
                soup
            )

            job["key"] = key

            jobs.append(job)

        except Exception as e:

            jobs.append({
                "key": key,
                "error": str(e),
            })


# ============================================================
# VALIDATION
# ============================================================

required_fields = [
    "title",
    "employer",
    "job_domains",
    "job_category",
    "job_description",
    "skills_experience",
    "benefits",
]


invalid_jobs = []

for job in jobs:

    if "error" in job:

        invalid_jobs.append(job)
        continue

    missing = []

    for field in required_fields:

        value = job.get(field)

        if not value:

            missing.append(field)

    if missing:

        job["missing"] = missing

        invalid_jobs.append(job)


# ============================================================
# MARKDOWN EXPORT
# ============================================================

output_path = (
    "vietnamworks_parsed_jobs.md"
)

with open(
    output_path,
    "w",
    encoding="utf-8",
) as f:

    # --------------------------------------------------------
    # HEADER
    # --------------------------------------------------------

    f.write(
        "# VietnamWorks Parsed Jobs\n\n"
    )

    # --------------------------------------------------------
    # SUMMARY
    # --------------------------------------------------------

    f.write(
        "## Summary\n\n"
    )

    f.write(
        f"- Total jobs: **{len(jobs)}**\n"
    )

    f.write(
        f"- Valid jobs: "
        f"**{len(jobs) - len(invalid_jobs)}**\n"
    )

    f.write(
        f"- Invalid jobs: "
        f"**{len(invalid_jobs)}**\n\n"
    )

    f.write(
        "---\n\n"
    )

    # --------------------------------------------------------
    # PARSED JOBS
    # --------------------------------------------------------

    f.write(
        "# Parsed Jobs\n\n"
    )

    for index, job in enumerate(
        jobs,
        start=1,
    ):

        f.write(
            f"## {index}. "
            f"{job.get('title') or 'UNKNOWN'}\n\n"
        )

        f.write(
            f"**File:** `{job.get('key')}`\n\n"
        )

        # ----------------------------------------------------
        # ERROR
        # ----------------------------------------------------

        if "error" in job:

            f.write(
                f"**Error:** `{job['error']}`\n\n"
            )

            f.write(
                "---\n\n"
            )

            continue

        # ----------------------------------------------------
        # VALIDATION STATUS
        # ----------------------------------------------------

        if job.get("missing"):

            f.write(
                "**Status:** ❌ Invalid\n\n"
            )

            f.write(
                "**Missing:** "
                + ", ".join(
                    f"`{field}`"
                    for field in job["missing"]
                )
                + "\n\n"
            )

        else:

            f.write(
                "**Status:** ✅ Valid\n\n"
            )

        # ----------------------------------------------------
        # EMPLOYER
        # ----------------------------------------------------

        f.write(
            "### Employer\n\n"
        )

        f.write(
            job.get("employer")
            or "_None_"
        )

        f.write(
            "\n\n"
        )

        # ----------------------------------------------------
        # JOB DOMAINS
        # ----------------------------------------------------

        f.write(
            "### Job Domains\n\n"
        )

        f.write(
            md_list(
                job.get("job_domains")
            )
            + "\n\n"
        )

        # ----------------------------------------------------
        # JOB CATEGORY
        # ----------------------------------------------------

        f.write(
            "### Job Category\n\n"
        )

        f.write(
            md_list(
                job.get("job_category")
            )
            + "\n\n"
        )

        # ----------------------------------------------------
        # JOB DESCRIPTION
        # ----------------------------------------------------

        f.write(
            "### Job Description\n\n"
        )

        f.write(
            job.get("job_description")
            or "_None_"
        )

        f.write(
            "\n\n"
        )

        # ----------------------------------------------------
        # SKILLS & EXPERIENCE
        # ----------------------------------------------------

        f.write(
            "### Skills & Experience\n\n"
        )

        f.write(
            job.get("skills_experience")
            or "_None_"
        )

        f.write(
            "\n\n"
        )

        # ----------------------------------------------------
        # SKILLS
        # ----------------------------------------------------

        f.write(
            "### Skills\n\n"
        )

        f.write(
            md_list(
                job.get("skills")
            )
            + "\n\n"
        )

        # ----------------------------------------------------
        # BENEFITS
        # ----------------------------------------------------

        f.write(
            "### Benefits\n\n"
        )

        f.write(
            md_list(
                job.get("benefits")
            )
            + "\n\n"
        )

        # ----------------------------------------------------
        # SEPARATOR
        # ----------------------------------------------------

        f.write(
            "---\n\n"
        )


# ============================================================
# CONSOLE
# ============================================================

print(
    "\nVietnamWorks parsing completed."
)

print(
    f"Total jobs:   {len(jobs)}"
)

print(
    f"Valid jobs:   {len(jobs) - len(invalid_jobs)}"
)

print(
    f"Invalid jobs: {len(invalid_jobs)}"
)

print(
    f"Output:       {output_path}"
)