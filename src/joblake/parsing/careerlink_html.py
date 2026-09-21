import re
from urllib.parse import urlsplit


JOB_PATH = re.compile(r'/tim-viec-lam/[^/]+/(\d+)/?$')


def job_id(url):
    match = JOB_PATH.fullmatch(urlsplit(url).path)
    return match[1] if match else None


def section(soup, name):
    heading = soup.select_one('#job-' + name)
    content = heading.find_next_sibling() if heading else None
    # An absent section must not consume a following heading or section.
    if content and (content.get('id', '').startswith('section-') or content.select_one('.job-section-title')):
        return None
    return content
