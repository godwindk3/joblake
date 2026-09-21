from bs4 import BeautifulSoup

from joblake.parsing.base import JobParser
from joblake.parsing.careerlink_html import job_id, section
from joblake.parsing.common import clean_items, clean_text, find_job_posting, json_ld_locations, parse_datetime, split_comma_values, tag_text
from joblake.parsing.models import ParsedJob, ParserOutput


class CareerLinkParser(JobParser):
    source = 'careerlink'
    version = '1.0.0'

    def parse(self, html, context):
        soup = BeautifulSoup(html, 'html.parser')
        posting = find_job_posting(soup) or {}
        organization = posting.get('hiringOrganization') or {}
        overview = {}
        for item in soup.select('#job-summary .job-summary-item'):
            label = item.select_one('.summary-label')
            if label:
                overview[tag_text(label)] = tag_text(label.find_next_sibling())
        benefits = section(soup, 'benefit')
        benefit_text = tag_text(benefits)
        benefit_items = clean_items(tag_text(n) for n in benefits.select('li')) if benefits else ()
        if not benefit_items:
            benefit_items = clean_items((benefit_text or '').splitlines())
        return ParserOutput(job=ParsedJob(
            title=tag_text(soup.select_one('#job-title')),
            employer_name_raw=clean_text(organization.get('name')),
            description_text=tag_text(section(soup, 'description')),
            requirements_text=tag_text(section(soup, 'skill')),
            benefits_text=benefit_text,
            benefit_items=benefit_items,
            categories_raw=split_comma_values(posting.get('industry')),
            skills_raw=split_comma_values(posting.get('skills')),
            locations_raw=json_ld_locations(posting),
            source_external_job_id=job_id(context.canonical_url),
            source_variant='public_html_json_ld',
            salary_raw=tag_text(soup.select_one('#job-salary .text-primary')),
            employment_type_raw=overview.get('Loại công việc'),
            experience_raw=overview.get('Kinh nghiệm'),
            posted_at=parse_datetime(posting.get('datePosted')),
            expires_at=parse_datetime(posting.get('validThrough')),
            source_payload={'overview': overview},
        ))
