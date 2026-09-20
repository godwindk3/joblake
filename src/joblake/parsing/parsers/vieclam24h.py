from bs4 import BeautifulSoup

from joblake.parsing.base import JobParser
from joblake.parsing.common import (
    clean_items, clean_text, find_job_posting, html_fragment_items,
    html_fragment_to_text, parse_datetime,
)
from joblake.parsing.models import ParsedJob, ParserOutput
from joblake.parsing.vieclam24h_html import api_data, labels, response_data


class Vieclam24hParser(JobParser):
    source = 'vieclam24h'
    version = '1.0.0'

    def parse(self, html, context):
        soup = BeautifulSoup(html, 'html.parser')
        api = api_data(soup)
        job = response_data(api, 'jobDetailHiddenContact')
        common = response_data(api, 'initCommon')
        posting = find_job_posting(soup) or {}
        employer = job.get('employer_info') or {}
        benefits = job.get('benefit_html') or job.get('benefit')
        locations = []
        for place in job.get('places') or []:
            if isinstance(place, dict):
                locations.append(', '.join(clean_items([
                    place.get('address'),
                    *labels(common, 'provinces', place.get('province_id')),
                ])))
        if not locations:
            locations = labels(common, 'provinces', job.get('province_ids'))
        salary = posting.get('baseSalary') or {}
        value = salary.get('value', {}) if isinstance(salary, dict) else {}
        salary_text = None
        if isinstance(value, dict):
            amounts = [str(value[k]) for k in ('minValue', 'maxValue') if value.get(k) is not None]
            if amounts and any(value.get(k) for k in ('minValue', 'maxValue')):
                salary_text = ' - '.join(amounts) + ' ' + str(salary.get('currency', ''))
        if not salary_text:
            salary_text = ', '.join(labels(common, 'job_salary_range', job.get('salary_range'), 'value')) or None
        return ParserOutput(job=ParsedJob(
            title=clean_text(job.get('title')),
            employer_name_raw=clean_text(employer.get('name')),
            description_text=html_fragment_to_text(job.get('description_html') or job.get('description')),
            requirements_text=html_fragment_to_text(job.get('other_requirement_html') or job.get('other_requirement')),
            benefits_text=html_fragment_to_text(benefits),
            benefit_items=html_fragment_items(benefits),
            categories_raw=clean_items(labels(common, 'occupation', job.get('occupation_ids_main'))),
            skills_raw=clean_items(job.get('skills_new') or []),
            locations_raw=clean_items(locations),
            source_external_job_id=str(job['id']) if job.get('id') else None,
            source_variant='next_data',
            salary_raw=salary_text,
            employment_type_raw=', '.join(labels(common, 'job_working_method', job.get('working_method'), 'value')) or None,
            experience_raw=', '.join(labels(common, 'job_experience_range', job.get('experience_range'), 'value')) or None,
            posted_at=parse_datetime(posting.get('datePosted')),
            expires_at=parse_datetime(posting.get('validThrough')),
            source_payload={'occupation_ids': job.get('occupation_ids_main'), 'field_id': job.get('field_ids_main')},
        ))
