from bs4 import BeautifulSoup

from joblake.parsing.base import JobParser
from joblake.parsing.common import clean_items, find_job_posting, json_ld_locations, parse_datetime, split_comma_values, tag_text
from joblake.parsing.jobsgo_html import displayed_date, employer_name, job_id, section
from joblake.parsing.models import ParsedJob, ParserOutput


class JobsGoParser(JobParser):
    source = 'jobsgo'
    version = '1.0.0'

    def parse(self, html, context):
        soup = BeautifulSoup(html, 'html.parser')
        posting = find_job_posting(soup) or {}
        overview = {}
        for label in soup.select('.job-info-list .text-muted, .job-card .text-muted.flex-grow-1'):
            value = label.find_next_sibling('strong')
            if value:
                overview[(tag_text(label) or '').rstrip(':')] = tag_text(value)
        benefits = section(soup, 'Quyền lợi được hưởng')
        benefit_text = tag_text(benefits)
        categories = split_comma_values(posting.get('industry'))
        if not categories:
            for label in soup.select('.job-detail-card .text-muted'):
                if tag_text(label) == 'Ngành nghề:':
                    content = label.find_next_sibling('strong')
                    if content:
                        categories = clean_items(tag_text(n) for n in content.select('a'))
        locations = json_ld_locations(posting) or clean_items(
            tag_text(n) for n in soup.select('#places .list-place > strong')
        )
        deadline = None
        for label in soup.select('.card-body p > .text-muted'):
            if tag_text(label) == 'Hạn nộp hồ sơ:':
                deadline = displayed_date(tag_text(label.find_next_sibling('strong')))
        return ParserOutput(job=ParsedJob(
            title=tag_text(soup.select_one('h1.job-title')),
            employer_name_raw=employer_name(soup, posting),
            description_text=tag_text(section(soup, 'Mô tả công việc')),
            requirements_text=tag_text(section(soup, 'Yêu cầu công việc')),
            benefits_text=benefit_text,
            benefit_items=clean_items(tag_text(n) for n in benefits.select('li')) if benefits else (),
            categories_raw=categories,
            skills_raw=split_comma_values(posting.get('skills')),
            locations_raw=locations,
            source_external_job_id=job_id(context.canonical_url),
            source_variant='public_html_json_ld' if posting else 'public_html',
            salary_raw=overview.get('Mức lương'),
            employment_type_raw=overview.get('Loại hình'),
            experience_raw=overview.get('Kinh nghiệm'),
            posted_at=parse_datetime(posting.get('datePosted')) or displayed_date(overview.get('Ngày đăng tuyển')),
            expires_at=parse_datetime(posting.get('validThrough')) or deadline,
            source_payload={'overview': overview},
        ))
