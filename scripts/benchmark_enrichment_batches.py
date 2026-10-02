"""Paired Gemini single/group benchmark. Explicit --execute spends shared quota.

Reads active JDs; never changes production job results/attempt counts. API calls
are recorded in the normal request ledger with purpose=benchmark. No raw text,
credentials or provider error bodies are logged.
"""
import argparse
import json
import os
import time
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row

from joblake.enrichment.candidates import CURRENT_CONTENT
from joblake.enrichment.providers import ProviderError, extract, extract_batch
from joblake.enrichment.schema import FIELDS, validate, validate_batch
from joblake.enrichment.service import estimate_tokens, input_bytes, load_config
from joblake.enrichment.store import Store
from joblake.supabase_sync import configure


def comparable(value):
    if isinstance(value, list):
        return sorted(comparable(item) for item in value)
    return ' '.join(value.casefold().split()) if isinstance(value, str) else value


def summarize(rows, singles, batches):
    paired = matching = total = 0
    differences = []
    for job in rows:
        left, right = singles.get(job['id']), batches.get(job['id'])
        if not left or not right or left['error'] or right['error']:
            continue
        paired += 1
        differing = [key for key in FIELDS if comparable(left['result'][key]) != comparable(right['result'][key])]
        matching += len(FIELDS) - len(differing)
        total += len(FIELDS)
        if differing:
            differences.append(dict(posting_id=job['id'], source=job['source'], fields=differing))
    return dict(paired_valid_jobs=paired, matching_fields=matching, compared_fields=total,
                field_agreement=matching / total if total else 0, differences=differences)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--jobs', type=int, choices=(12, 18, 24), default=12)
    parser.add_argument('--output', default='output/enrichment-batch-benchmark.json')
    args = parser.parse_args()
    load_dotenv(Path(__file__).resolve().parents[1] / '.env')
    configure()
    config = load_config('configs/enrichment.yaml')
    provider = next(p for p in config['providers'] if p['name'] == 'gemini')
    cap = provider.get('max_output_tokens', config['max_output_tokens'])
    report = dict(provider=provider['name'], model=provider['model'], sample_size=args.jobs,
                  planned_requests=args.jobs + args.jobs // 3, arms={}, comparison=None,
                  recommendation='not_evaluated', quality_note='Field agreement with single-call baseline is not ground-truth accuracy.')
    with psycopg.connect(os.environ['LOCAL_DATABASE_URL'], autocommit=True, connect_timeout=15) as c:
        c.execute("SET statement_timeout='120s'")
        store = Store(c)
        if args.execute and (not os.getenv(provider['key_env']) or not store.lock()):
            raise ValueError('Missing Gemini key or another enrichment worker is running')
        with c.transaction():
            c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
            with c.cursor(row_factory=dict_row) as cur:
                cur.execute('''WITH content AS (''' + CURRENT_CONTENT + '''), ranked AS (
                    SELECT *,row_number() OVER (PARTITION BY source ORDER BY input_hash) source_rank
                    FROM content)
                    SELECT source_posting_id AS id,source,input_hash,input_payload FROM ranked
                    ORDER BY source_rank,source LIMIT %s''', (args.jobs,))
                rows = cur.fetchall()
        if len(rows) != args.jobs:
            raise ValueError('Insufficient active jobs for requested paired sample')
        report['sample'] = [dict(posting_id=j['id'], source=j['source'], input_hash=j['input_hash']) for j in rows]
        print(json.dumps({k:v for k,v in report.items() if k != 'sample'}), flush=True)
        if not args.execute:
            return 0
        deadline = time.monotonic() + 1200
        completed = True
        for name, size in [('single', 1), ('batch3', 3)]:
            records, requests, actual_total, valid, seconds = {}, 0, 0, 0, 0
            report['arms'][name] = dict(results=records)
            for offset in range(0, len(rows), size):
                group = rows[offset:offset+size]
                payload = group if size > 1 else group[0]['input_payload']
                ratio = store.input_token_ratio(provider, batch=size > 1)
                reserved = estimate_tokens(payload, cap * size, ratio=ratio, batch=size > 1)
                request_id = None
                while time.monotonic() < deadline:
                    request_id = store.reserve_batch(group, provider, reserved,
                        input_bytes=input_bytes(payload, batch=size > 1), purpose='benchmark')
                    if request_id is not None:
                        break
                    if not store.can_retry_soon([provider], reserved):
                        break
                    time.sleep(5)
                if request_id is None:
                    completed = False
                    break
                requests += 1
                response = None
                started = time.monotonic()
                try:
                    if size > 1:
                        response = extract_batch(provider, group, max_output=cap*size, timeout=60)
                        outcomes = validate_batch(response.data, group)
                    else:
                        response = extract(provider, payload, max_output=cap, timeout=60)
                        outcomes = {group[0]['id']: (validate(response.data, payload), None)}
                except ProviderError as exc:
                    store.block(provider['name'], exc.code, exc.cooldown)
                    outcomes = {j['id']: (None, exc.code) for j in group}
                except ValueError as exc:
                    outcomes = {j['id']: (None, str(exc)) for j in group}
                elapsed = time.monotonic() - started
                seconds += elapsed
                store.finish_batch(group, request_id, outcomes, tokens=response.tokens if response else None,
                    input_tokens=response.input_tokens if response else None,
                    output_tokens=response.output_tokens if response else None, purpose='benchmark')
                actual_total += response.tokens if response and response.tokens is not None else reserved
                successes = sum(error is None for _, error in outcomes.values())
                valid += successes
                for job in group:
                    result, error = outcomes[job['id']]
                    records[job['id']] = dict(result=result, error=error, request_id=request_id)
                print(json.dumps(dict(arm=name, request_id=request_id, jobs=size, valid=successes,
                    actual_tokens=response.tokens if response else None, seconds=round(elapsed, 2))), flush=True)
            report['arms'][name].update(requests=requests, valid_jobs=valid, charged_tokens=actual_total,
                                       tokens_per_valid_job=actual_total / valid if valid else None,
                                       api_seconds=seconds)
            if not completed:
                break
        if completed:
            single, batch = report['arms']['single'], report['arms']['batch3']
            comparison = summarize(rows, single['results'], batch['results'])
            comparison['token_saving_fraction'] = 1 - batch['charged_tokens'] / single['charged_tokens']
            comparison['request_saving_fraction'] = 1 - batch['requests'] / single['requests']
            report['comparison'] = comparison
            # Deliberately strict: no validation regression and high field agreement before a default change.
            report['recommendation'] = 'candidate_for_batch3' if (
                batch['valid_jobs'] == args.jobs and single['valid_jobs'] == args.jobs
                and comparison['field_agreement'] >= 0.95 and comparison['token_saving_fraction'] > 0
            ) else 'keep_single_default_review_differences'
        else:
            report['recommendation'] = 'incomplete_quota_or_cooldown'
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('sample','arms')}, ensure_ascii=False), flush=True)
    return 0 if completed else 1


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (psycopg.Error, ValueError, OSError) as exc:
        print('Benchmark unavailable:', type(exc).__name__, flush=True)
        raise SystemExit(1)
