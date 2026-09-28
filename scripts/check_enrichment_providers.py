"""Explicit synthetic smoke test: at most one API call per configured provider.

No stored job is read or enriched. No key/response body is printed.
"""
import logging
from pathlib import Path
from dotenv import load_dotenv
from joblake.enrichment.service import load_config
from joblake.enrichment.providers import ProviderError, extract
from joblake.enrichment.schema import validate
from joblake.logging import configure_logging
import os
import time


def main():
    load_dotenv(Path(__file__).resolve().parents[1] / '.env')
    configure_logging()
    payload = {'title': 'Backend Engineer', 'requirements_text':
               'Required: Python and SQL. At least 2 years of professional experience. '
               'Docker is a plus.', 'description_text': 'Full-time position. Work remotely.'}
    failed = False
    for provider in load_config('configs/enrichment.yaml')['providers']:
        if not provider.get('enabled', True):
            logging.info('%s disabled; skipping', provider['name'])
            continue
        if not os.getenv(provider['key_env']):
            logging.warning('%s key missing', provider['name'])
            failed = True
            continue
        started = time.monotonic()
        try:
            response = extract(provider, payload, max_output=provider.get('max_output_tokens', 2048))
            result = validate(response.data, payload)
            correct = (result['experience_min_years'] == 2 and result['experience_max_years'] is None
                       and result['work_mode'] == 'remote' and result['employment_type'] == 'full_time'
                       and {s.lower() for s in result['skills_required'] or []} == {'python', 'sql'}
                       and {s.lower() for s in result['skills_preferred'] or []} == {'docker'})
            logging.info('%s schema=PASS extraction=%s tokens=%s seconds=%.1f',
                         provider['name'], 'PASS' if correct else 'FAIL', response.tokens, time.monotonic()-started)
            failed |= not correct
        except (ProviderError, ValueError) as exc:
            logging.error('%s failed code=%s', provider['name'], str(exc))
            failed = True
    return int(failed)


if __name__ == '__main__':
    raise SystemExit(main())
