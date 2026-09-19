"""CareerViet canonical fields from public detail sections and JSON-LD."""
import re
from datetime import datetime
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from joblake.parsing.base import JobParser
from joblake.parsing.careerviet_html import detail_sections, detail_title
from joblake.parsing.common import (
    clean_items, clean_text, find_job_posting, json_ld_identifier,
    json_ld_locations, parse_datetime, split_comma_values, tag_text,
)
from joblake.parsing.models import ParseContext, ParsedJob, ParserOutput


class CareerVietParser(JobParser):
    source = 'careerviet'
    version = '1.0.1'

    def parse(self, html: str, context: ParseContext) -> ParserOutput:
        soup = BeautifulSoup(html, 'html.parser')
        posting = find_job_posting(soup) or {}
        sections = detail_sections(soup)
        overview = {}
        categories = []
        for item in soup.select('.job-detail-content .detail-box li'):
            label = tag_text(item.select_one('strong'))
            if label:
                overview[label] = tag_text(item.select_one('p'))
                if label == 'Ngành nghề':
                    categories.extend(tag_text(a) for a in item.select('p a'))
        organization = posting.get('hiringOrganization')
        employer = organization.get('name') if isinstance(organization, dict) else None
        benefits = clean_items(tag_text(n) for n in soup.select('.welfare-list li')) or split_comma_values(posting.get('jobBenefits'))
        salary = posting.get('baseSalary') or {}
        value = salary.get('value', {}) if isinstance(salary, dict) else {}
        salary_fallback = None
        if isinstance(value, dict):
            salary_fallback = clean_text(value.get('value'))
            if not salary_fallback:
                amounts = [str(value[k]) for k in ('minValue', 'maxValue') if value.get(k) is not None]
                if amounts:
                    salary_fallback = ' - '.join(amounts) + ' ' + str(salary.get('currency', ''))
        experience = posting.get('experienceRequirements')
        experience_fallback = experience.get('description') if isinstance(experience, dict) else experience
        employment = posting.get('employmentType')
        employment_fallback = ', '.join(str(v).strip('"') for v in employment) if isinstance(employment, list) else employment
        url_id = re.search(r'\.([0-9a-fA-F]{8})\.html$', urlsplit(context.canonical_url).path)
        expires_at = parse_datetime(posting.get('validThrough'))
        if expires_at is None and overview.get('Hết hạn nộp'):
            try:
                date = datetime.strptime(overview['Hết hạn nộp'], '%d/%m/%Y')
                expires_at = parse_datetime(date.isoformat())
            except ValueError:
                pass
        # Do not treat the site's update date as the original publication date.
        return ParserOutput(job=ParsedJob(
            title=detail_title(soup, posting),
            employer_name_raw=tag_text(soup.select_one('.apply-now-banner .job-company-name')) or clean_text(employer),
            description_text=sections.get('mô tả công việc'),
            requirements_text=sections.get('yêu cầu công việc'),
            benefits_text='\n'.join(benefits) or sections.get('phúc lợi'),
            benefit_items=benefits,
            categories_raw=clean_items(categories) or split_comma_values(posting.get('industry')),
            skills_raw=split_comma_values(posting.get('skills')),
            locations_raw=clean_items(tag_text(n) for n in soup.select('.info-place-detail .place-name')) or json_ld_locations(posting),
            source_external_job_id=json_ld_identifier(posting) or (url_id[1].upper() if url_id else None),
            source_variant='public_html_json_ld',
            salary_raw=overview.get('Lương') or salary_fallback,
            employment_type_raw=overview.get('Hình thức') or clean_text(employment_fallback),
            experience_raw=overview.get('Kinh nghiệm') or clean_text(experience_fallback),
            posted_at=parse_datetime(posting.get('datePosted')),
            expires_at=expires_at,
            source_payload={'overview': overview, 'other_information': sections.get('thông tin khác')},
        ))
