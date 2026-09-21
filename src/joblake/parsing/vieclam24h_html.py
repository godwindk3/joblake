"""Read public Next.js hydration data; never execute page scripts."""
import json
import re
from urllib.parse import urlsplit

from joblake.parsing.common import tag_text


JOB_PATH = re.compile(r'/[^/]+/[^/]+-c\d+p\d+id(\d+)\.html$')


def job_id(url):
    match = JOB_PATH.fullmatch(urlsplit(url).path)
    return match[1] if match else None


def api_data(soup):
    node = soup.select_one('script#__NEXT_DATA__')
    try:
        data = json.loads(node.get_text()) if node else {}
        api = data['props']['initialState']['api']
        return api if isinstance(api, dict) else {}
    except (ValueError, KeyError, TypeError):
        return {}


def response_data(api, key):
    response = api.get(key)
    if not isinstance(response, dict) or response.get('code') != 200:
        return {}
    data = response.get('data')
    return data if isinstance(data, dict) else {}


def labels(common, key, ids, identity='id'):
    if not isinstance(ids, list):
        ids = [ids]
    mapping = {str(row.get(identity)): row.get('name')
               for row in common.get(key, []) if isinstance(row, dict)}
    return [mapping[str(value)] for value in ids if str(value) in mapping and mapping[str(value)]]


def rendered_content(soup):
    for heading in soup.select('h2, h3'):
        if heading.get_text(' ', strip=True).casefold() in {'mô tả công việc', 'yêu cầu công việc'}:
            sibling = heading.find_next_sibling()
            if sibling is not None and 'text-description' in sibling.get('class', []) and tag_text(sibling):
                return True
    return False
