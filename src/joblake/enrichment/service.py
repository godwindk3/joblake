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

from joblake.enrichment.providers import ProviderError, extract, extract_batch
from joblake.enrichment.schema import PROMPT, SCHEMA, input_text, validate, batch_contract, validate_batch
from joblake.enrichment.store import Store, request_token_limit

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
    if type(config.get('calibrate_input_tokens', False)) is not bool:
        raise ValueError('Invalid calibrate_input_tokens')
    seen = set()
    for p in config['providers']:
        if p['name'] not in ('gemini', 'groq', 'openrouter') or p['name'] in seen:
            raise ValueError('Unknown or duplicate provider')
        seen.add(p['name'])
        if type(p.get('enabled', True)) is not bool:
            raise ValueError('Invalid provider enabled flag')
        if type(p.get('enforce_daily_budget', True)) is not bool:
            raise ValueError('Invalid provider enforce_daily_budget flag')
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
        size = p.get('batch_size', 1)
        if type(size) is not int or not 1 <= size <= 3 or (p['name'] != 'gemini' and size != 1):
            raise ValueError('batch_size must be 1..3 for Gemini and 1 for other providers')
        if type(p.get('batch_max_input_tokens', 12000)) is not int or p.get('batch_max_input_tokens', 12000) < 1:
            raise ValueError('Invalid batch_max_input_tokens')
    if not seen:
        raise ValueError('At least one provider is required')
    return config


def input_bytes(payload, *, batch=False):
    prompt, schema = PROMPT, SCHEMA
    if batch:
        prompt, schema, payload = batch_contract(payload)
    return len((input_text(payload) + prompt + json.dumps(schema)).encode('utf-8'))


def estimate_tokens(payload, output, *, ratio=0.5, batch=False):
    # Conservative estimate, not a tokenizer. Actual usage reconciles the ledger.
    # Include schema/system overhead and the whole completion (including reasoning).
    return math.ceil(input_bytes(payload, batch=batch) * ratio) + output


def group_jobs(head, followers, provider, output_per_job, *, ratio=0.5):
    selected = [head]
    if head['attempts'] or provider.get('batch_size', 1) == 1:
        return selected
    for follower in followers[:provider.get('batch_size', 1) - 1]:
        proposed = selected + [follower]
        output = output_per_job * len(proposed)
        total = estimate_tokens(proposed, output, ratio=ratio, batch=True)
        if total - output > provider.get('batch_max_input_tokens', 12000):
            break
        if total > request_token_limit(provider):
            break
        selected = proposed
    return selected


def process(store, config, *, call=extract, batch_call=extract_batch, clock=time.monotonic, sleep=time.sleep):
    providers = [p for p in config['providers'] if p.get('enabled', True) and os.getenv(p['key_env'])]
    if not providers:
        LOGGER.error('No enrichment API keys configured; queue retained, sync remains independent')
        return 2
    for p in config['providers']:
        LOGGER.info('Provider %s model=%s configured=%s enabled=%s budget_rpd=%s budget_tpd=%s enforce_daily_budget=%s',
                    p['name'], p['model'], bool(os.getenv(p['key_env'])), p.get('enabled', True),
                    p['requests_per_day'], p['tokens_per_day'], p.get('enforce_daily_budget', True))
    deadline = clock() + config['max_run_seconds']
    attempted = attempted_jobs = succeeded = errors = 0
    ratios = {}
    for provider in providers:
        for is_batch in (False, True):
            ratio = store.input_token_ratio(provider, batch=is_batch) if config.get('calibrate_input_tokens', False) else 0.5
            ratios[provider['name'], is_batch] = ratio if type(ratio) in (int, float) and math.isfinite(ratio) and ratio > 0 else 0.5
    last_wait_log = 0
    while attempted < config['max_jobs_per_run'] and clock() < deadline:
        job = store.next_job(config['max_attempts'])
        if job is None:
            break
        estimates = {p['name']: estimate_tokens(job['input_payload'],
                     p.get('max_output_tokens', config['max_output_tokens']), ratio=ratios[p['name'], False]) for p in providers}
        # Oversized inputs remain visible for manual review; never silently truncate JD.
        if all(estimates[p['name']] > request_token_limit(p) for p in providers):
            store.c.execute("""UPDATE core.job_enrichments SET status='failed',
                error_code='input_exceeds_budget',updated_at=now() WHERE id=%s""", (job['id'],))
            errors += 1
            LOGGER.warning('Enrich id=%s skipped=input_exceeds_budget estimates=%s', job['id'], estimates)
            continue
        selected = None
        for provider in providers:
            jobs = [job]
            per_job_output = provider.get('max_output_tokens', config['max_output_tokens'])
            if provider.get('batch_size', 1) > 1 and job['attempts'] == 0:
                followers = store.batch_followers(job, config['max_attempts'], provider['batch_size'] - 1)
                jobs = group_jobs(job, followers, provider, per_job_output, ratio=ratios[provider['name'], True])
            # Shrink when the full group does not fit the remaining quota; then try fallback providers.
            while jobs:
                output = per_job_output * len(jobs)
                payload = jobs if len(jobs) > 1 else job['input_payload']
                tokens = estimate_tokens(payload, output, ratio=ratios[provider['name'], len(jobs) > 1], batch=len(jobs) > 1)
                reserve = store.reserve_batch if len(jobs) > 1 else store.reserve
                attempt = reserve(jobs if len(jobs) > 1 else job, provider, tokens,
                                  input_bytes=input_bytes(payload, batch=len(jobs) > 1), max_attempts=config['max_attempts'])
                if attempt is not None:
                    selected = provider
                    break
                jobs = jobs[:-1]
            if selected is not None:
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
        attempted_jobs += len(jobs)
        started = clock()
        response = None
        LOGGER.info('Enrich request=%s provider=%s jobs=%s reserved_tokens=%s max_output_tokens=%s',
                    attempt, selected['name'], len(jobs), tokens, output)
        for member in jobs:
            LOGGER.info('Enrich start id=%s posting=%s provider=%s model=%s attempt=%s request=%s',
                        member['id'], member['source_posting_id'], selected['name'], selected['model'],
                        member['attempts'] + 1, attempt)
        try:
            if len(jobs) > 1:
                response = batch_call(selected, jobs, max_output=output, timeout=config['request_timeout_seconds'])
                outcomes = validate_batch(response.data, jobs)
            else:
                response = call(selected, job['input_payload'], max_output=output, timeout=config['request_timeout_seconds'])
                outcomes = {job['id']: (validate(response.data, job['input_payload']), None)}
        except ProviderError as exc:
            store.block(selected['name'], exc.code, exc.cooldown)
            outcomes = {member['id']: (None, exc.code) for member in jobs}
            LOGGER.warning('Enrich request=%s provider=%s error=%s cooldown_seconds=%s',
                           attempt, selected['name'], exc.code, exc.cooldown)
        except ValueError as exc:
            # Validator errors are fixed local codes, never provider text.
            outcomes = {member['id']: (None, str(exc)) for member in jobs}
        usage = dict(tokens=response.tokens if response else None,
                     input_tokens=response.input_tokens if response else None,
                     output_tokens=response.output_tokens if response else None, max_attempts=config['max_attempts'])
        if len(jobs) > 1:
            store.finish_batch(jobs, attempt, outcomes, **usage)
        else:
            result, error = outcomes[job['id']]
            store.finish(job, attempt, result=result, error=error, **usage)
        for member in jobs:
            _, error = outcomes[member['id']]
            errors += int(error is not None)
            succeeded += int(error is None)
            LOGGER.log(logging.WARNING if error else logging.INFO,
                       'Enrich result id=%s posting=%s request=%s status=%s error=%s', member['id'],
                       member['source_posting_id'], attempt, 'retry_or_failed' if error else 'succeeded', error)
        LOGGER.info('Enrich request=%s actual_tokens=%s elapsed_seconds=%.1f',
                    attempt, usage['tokens'], clock() - started)
    LOGGER.info('Enrichment complete api_requests=%s attempted_jobs=%s succeeded=%s errors=%s queue=%s',
                attempted, attempted_jobs, succeeded, errors, store.summary())
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
