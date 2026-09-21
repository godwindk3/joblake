import re
from urllib.parse import urlsplit

from joblake.parsing.common import clean_text, parse_datetime, tag_text


def job_id(url):
    match = re.fullmatch(r'/viec-lam/[^/]+-(\d+)\.html', urlsplit(url).path)
    return match.group(1) if match else None


def employer_name(soup, posting):
    # Recruit posts identify the actual employer inside the description card.
    actual = tag_text(soup.select_one('.job-detail-card .card-company h6'))
    organization = posting.get('hiringOrganization') or {}
    structured = clean_text(organization.get('name')) if isinstance(organization, dict) else None
    return actual or structured or tag_text(soup.select_one('.card-company h6'))


def displayed_date(value):
    match = re.search(r'(\d{2})/(\d{2})/(\d{4})', value or '')
    return parse_datetime(f'{match[3]}-{match[2]}-{match[1]}') if match else None


def section(soup, label):
    for heading in soup.select('.job-detail-card h3.section-title'):
        if (tag_text(heading) or '').rstrip(':').casefold() == label.casefold():
            body = heading.find_next_sibling()
            return body if body and body.name == 'div' else None
    return None
