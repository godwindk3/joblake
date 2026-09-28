"""Independent enrichment phase; never calls Supabase or ingestion."""
import json
import logging
import math
import os
import time
from datetime import datetime
from pathlib import Path

import psycopg
import yaml

from joblake.enrichment.providers import ProviderError, extract
from joblake.enrichment.schema import PROMPT, SCHEMA, input_text, validate
from joblake.enrichment.store import Store

LOGGER = logging.getLogger(__name__)


def load_config(path):
    config = yaml.safe_load(Path(path).read_text(encoding='utf-8'))
    cutoff = datetime.fromisoformat(config['eligible_from'])
    if cutoff.tzinfo is None:
        raise ValueError('eligible_from needs a timezone')
    for field in ('max_jobs_per_run', 'max_run_seconds', 'max_attempts', 'max_output_tokens', 'request_timeout_seconds'):
        if type(config[field]) is not int or config[field] < 1:
            raise ValueError(f'Invalid {field}')
    if config['request_timeout_seconds'] > 120 or config['max_attempts'] > 10:
        raise ValueError('Request timeout/attempts exceeds safety bound')
    seen = set()
    for p in config['providers']:
        if p['name'] not in ('gemini', 'groq', 'openrouter') or p['name'] in seen:
            raise ValueError('Unknown or duplicate provider')
        seen.add(p['name'])
        if type(p.get('enabled', True)) is not bool:
            raise ValueError('Invalid provider enabled flag')
        if not isinstance(p['model'], str) or not p['model'] or not isinstance(p['key_env'], str):
            raise ValueError('Invalid provider model/key_env')
        for field in ('requests_per_minute', 'tokens_per_minute', 'requests_per_day', 'tokens_per_day'):
            if type(p[field]) is not int or p[field] < 1:
                raise ValueError(f'Invalid provider {field}')
        if p['name'] == 'openrouter' and not p['model'].endswith(':free'):
            raise ValueError('OpenRouter must use a :free model')
        if p.get('output_format', 'json_object') not in ('json_object', 'json_schema'):
            raise ValueError('Invalid output_format')
        if 'reasoning_enabled' in p and type(p['reasoning_enabled']) is not bool:
            raise ValueError('reasoning_enabled must be boolean')
        if 'max_output_tokens' in p and (type(p['max_output_tokens']) is not int or p['max_output_tokens'] < 1):
            raise ValueError('Provider max_output_tokens must be positive')
    if not seen:
        raise ValueError('At least one provider is required')
    return config


def estimate_tokens(payload, output):
    # Conservative estimate, not a tokenizer. Actual usage reconciles the ledger.
    # Include schema/system overhead and the whole completion (including reasoning).
    size = len((input_text(payload) + PROMPT + json.dumps(SCHEMA)).encode('utf-8'))
    return math.ceil(size / 2) + output


def process(store, config, *, call=extract, clock=time.monotonic, sleep=time.sleep):
    providers = [p for p in config['providers'] if p.get('enabled', True) and os.getenv(p['key_env'])]
    if not providers:
        LOGGER.error('No enrichment API keys configured; queue retained, sync remains independent')
        return 2
    for p in config['providers']:
        LOGGER.info('Provider %s model=%s configured=%s enabled=%s budget_rpd=%s budget_tpd=%s',
                    p['name'], p['model'], bool(os.getenv(p['key_env'])), p.get('enabled', True),
                    p['requests_per_day'], p['tokens_per_day'])
    deadline = clock() + config['max_run_seconds']
    attempted = succeeded = errors = 0
    last_wait_log = 0
    while attempted < config['max_jobs_per_run'] and clock() < deadline:
        job = store.next_job(config['max_attempts'])
        if job is None:
            break
        estimates = {p['name']: estimate_tokens(job['input_payload'],
                     p.get('max_output_tokens', config['max_output_tokens'])) for p in providers}
        # Oversized inputs remain visible for manual review; never silently truncate JD.
        if all(estimates[p['name']] > min(p['tokens_per_minute'], p['tokens_per_day']) for p in providers):
            store.c.execute("""UPDATE core.job_enrichments SET status='failed',
                error_code='input_exceeds_budget',updated_at=now() WHERE id=%s""", (job['id'],))
            errors += 1
            LOGGER.warning('Enrich id=%s skipped=input_exceeds_budget estimates=%s', job['id'], estimates)
            continue
        selected = None
        for provider in providers:
            tokens = estimates[provider['name']]
            attempt = store.reserve(job, provider, tokens)
            if attempt is not None:
                selected = provider
                break
        if selected is None:
            if not any(store.can_retry_soon([p], estimates[p['name']]) for p in providers):
                LOGGER.info('All usable providers exhausted/cooling down; leaving jobs queued for a later DAG run')
                break
            if clock() - last_wait_log >= 30:
                LOGGER.info('Enrichment waiting: provider quota/cooldown; queue=%s', store.summary())
                last_wait_log = clock()
            sleep(min(5, max(0, deadline - clock())))
            continue
        attempted += 1
        started = clock()
        actual = None
        LOGGER.info('Enrich start id=%s posting=%s provider=%s model=%s attempt=%s estimated_tokens=%s',
                    job['id'], job['source_posting_id'], selected['name'], selected['model'],
                    job['attempts'] + 1, tokens)
        try:
            response = call(selected, job['input_payload'], max_output=selected.get('max_output_tokens', config['max_output_tokens']),
                            timeout=config['request_timeout_seconds'])
            actual = response.tokens
            result = validate(response.data, job['input_payload'])
        except ProviderError as exc:
            store.block(selected['name'], exc.code, exc.cooldown)
            store.finish(job, attempt, error=exc.code, max_attempts=config['max_attempts'])
            LOGGER.warning('Enrich id=%s provider=%s error=%s cooldown_seconds=%s',
                           job['id'], selected['name'], exc.code, exc.cooldown)
            errors += 1
        except ValueError as exc:
            # Validator errors are fixed local codes, never provider text.
            store.finish(job, attempt, error=str(exc), tokens=actual, max_attempts=config['max_attempts'])
            LOGGER.warning('Enrich id=%s provider=%s validation=%s field=%s',
                           job['id'], selected['name'], str(exc), getattr(exc, 'field', None))
            errors += 1
        else:
            store.finish(job, attempt, result=result, tokens=actual)
            succeeded += 1
            LOGGER.info('Enrich success id=%s provider=%s tokens=%s elapsed_seconds=%.1f',
                        job['id'], selected['name'], actual, clock() - started)
    LOGGER.info('Enrichment complete attempted=%s succeeded=%s errors=%s queue=%s',
                attempted, succeeded, errors, store.summary())
    outcome = 'failed' if errors and not succeeded else ('completed_with_errors' if errors else 'completed')
    LOGGER.log(logging.ERROR if outcome == 'failed' else logging.WARNING if errors else logging.INFO,
               'Enrichment outcome=%s; successful results persisted; sync is a separate DAG', outcome)
    return 1 if outcome == 'failed' else 0


def run(path='configs/enrichment.yaml', *, dry_run=False, max_jobs=None):
    from joblake.supabase_sync import configure
    try:
        config = load_config(path)
        if max_jobs is not None:
            if max_jobs < 1:
                raise ValueError('max-jobs must be positive')
            config['max_jobs_per_run'] = max_jobs
        configure()  # Only resolves LOCAL_DATABASE_URL; never opens a remote connection.
        if not os.getenv('LOCAL_DATABASE_URL'):
            raise ValueError('LOCAL_DATABASE_URL is required')
        with psycopg.connect(os.environ['LOCAL_DATABASE_URL'], autocommit=True, connect_timeout=15) as c:
            c.execute("SET statement_timeout='120s'")
            c.execute("SET lock_timeout='10s'")
            cutoff = c.execute('SELECT eligible_from FROM core.enrichment_settings WHERE id').fetchone()[0]
            if cutoff != datetime.fromisoformat(config['eligible_from']):
                raise ValueError('Configured cutoff differs from persisted cutoff; refusing implicit backfill')
            store = Store(c)
            if dry_run:
                count = c.execute('SELECT count(*) FROM core.enrichment_candidates').fetchone()[0]
                LOGGER.info('Enrichment dry-run cutoff=%s eligible_current=%s queue=%s; no writes/API calls',
                            cutoff.isoformat(), count, store.summary())
                return 0
            if not store.lock():
                LOGGER.error('Another enrichment worker is running')
                return 1
            store.enqueue()
            return process(store, config)
    except (ValueError, KeyError, OSError, yaml.YAMLError) as exc:
        LOGGER.error('Enrichment configuration failure (%s); check config and local migration', type(exc).__name__)
        return 2
    except psycopg.Error as exc:
        LOGGER.error('Enrichment database failure (%s, SQLSTATE=%s)', type(exc).__name__, exc.sqlstate)
        return 1
