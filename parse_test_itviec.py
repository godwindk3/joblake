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

response = s3.list_objects_v2(
    Bucket=bucket,
    Prefix=prefix,
)


def get_html(key):
    data = s3.get_object(
        Bucket=bucket,
        Key=key,
    )

    html = data["Body"].read().decode("utf-8")
    return BeautifulSoup(html, "html.parser")


key = response["Contents"][0]["Key"]

soup = get_html(key)

# print("KEY:", key)
# print(soup.get_text(" ", strip=True))
# print(soup)

# Title
title = soup.select_one("div.job-header-info h1").get_text(strip=True)

# Job domains
job_domains = [
    element.get_text(strip=True)
    for element in soup.select("div.itag.bg-light-grey.itag-sm.cursor-default")
]

# Job category
label = soup.find(
    "div",
    string=lambda text: text and text.strip() == "Job Expertise:"
)

job_category = [
    a.get_text(" ", strip=True)
    for a in label.find_next_sibling("div").select(
        'a[data-controller="utm-tracking"][href^="/it-jobs/"]'
    )
]

# Job description
job_description_heading = soup.find(
    "h2",
    string=lambda text: text and text.strip() == "Job description"
)

job_description_container = job_description_heading.find_parent(
    "div",
    class_="imy-5 paragraph"
)

job_description = (
    job_description_container.get_text("\n", strip=True)
    if job_description_container
    else None
)


# Skills and experience
skills_heading = soup.find(
    "h2",
    string=lambda text: text and text.strip() == "Your skills and experience"
)

skills_container = skills_heading.find_parent(
    "div",
    class_="imy-5 paragraph"
)

skills_experience = (
    skills_container.get_text("\n", strip=True)
    if skills_container
    else None
)

# Skills
skills_label = soup.find(
    "div",
    string=lambda text: text and text.strip() == "Skills:"
)

skills = [
    a.get_text(" ", strip=True)
    for a in skills_label.find_next_sibling("div").select(
        'a[data-controller="utm-tracking"][href^="/it-jobs/"]'
    )
]

print(skills)



