"""Parse Devwork's public detail HTML without evaluating its Nuxt scripts."""
import re
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from joblake.parsing.base import JobParser
from joblake.parsing.common import clean_items, parse_datetime, tag_text
from joblake.parsing.models import ParseContext, ParsedJob, ParserOutput


class DevworkParser(JobParser):
    source = "devwork"
    version = "1.0.1"

    def parse(self, html: str, context: ParseContext) -> ParserOutput:
        soup = BeautifulSoup(html, "html.parser")
        sections = {}
        for heading in soup.select(".background-content-job h2.block-title"):
            content = heading.find_next_sibling()
            if content is not None and "block-desc" in content.get("class", []):
                sections[heading.get_text(strip=True)] = tag_text(content)
        overview = {}
        for item in soup.select(".job-overview .location-profile-job"):
            label = tag_text(item.select_one("strong"))
            if label:
                overview[label] = tag_text(item.select_one("span"))
        salary = None
        for heading in soup.select("h4"):
            if heading.get_text(strip=True) == "Mức lương":
                salary = tag_text(heading.parent.select_one(".salary-amount"))
                break
        identity = re.fullmatch(r"/viec-lam/(\d+)/[^/]+/?", urlsplit(context.canonical_url).path)
        benefits = sections.get("Quyền lợi ứng viên")
        return ParserOutput(job=ParsedJob(
            title=tag_text(soup.select_one(".header-details h1")),
            employer_name_raw=tag_text(soup.select_one(".header-details h5")),
            description_text=sections.get("Mô tả công việc"),
            requirements_text=sections.get("Yêu cầu công việc"),
            benefits_text=benefits,
            benefit_items=clean_items((benefits or "").splitlines()),
            skills_raw=clean_items(tag_text(node) for node in soup.select(".background-content-job .tags a")),
            locations_raw=clean_items((
                tag_text(soup.select_one(".header-details p")),
                sections.get("Địa chỉ làm việc"),
            )),
            source_external_job_id=identity[1] if identity else None,
            source_variant="public_html",
            salary_raw=salary,
            employment_type_raw=overview.get("Hình thức"),
            experience_raw=overview.get("Kinh nghiệm"),
            expires_at=parse_datetime(overview.get("Hạn nộp hồ sơ")),
            source_payload={"overview": overview, "working_time": sections.get("Thời gian làm việc")},
        ))
