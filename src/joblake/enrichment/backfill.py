"""Explicit historical enrichment, with a read-only preview and bounded selection."""
import json
import logging
import os
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

import psycopg
import yaml
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from joblake.enrichment.candidates import CURRENT_CONTENT
from joblake.enrichment.schema import VERSION
from joblake.enrichment.service import estimate_tokens, group_jobs, load_config, process
from joblake.enrichment.store import Store, request_token_limit

LOGGER = logging.getLogger(__name__)
VIETNAM = timezone(timedelta(hours=7))
DEFAULTS = dict(dry_run=True, lookback_days=30, date_from=None, date_to=None,
                as_of=None, date_field='first_seen_at', sources=[], posting_ids=[],
                sort_order='newest_first', max_jobs=100, max_api_attempts=100)


def timestamp(value):
    """Date-only and naive ISO values mean local Vietnam time; upper bounds exclude."""
    result = datetime.fromisoformat(value)
    return result.replace(tzinfo=VIETNAM) if result.tzinfo is None else result.astimezone(VIETNAM)


def normalize(options, *, now=None):
    if not isinstance(options, dict) or options.keys() - DEFAULTS.keys():
        raise ValueError('Backfill options must be an object with known parameter names')
    value = {**DEFAULTS, **options}
    if type(value['dry_run']) is not bool:
        raise ValueError('dry_run must be boolean')
    for key, upper in [('lookback_days', 36500), ('max_jobs', 1000), ('max_api_attempts', 1000)]:
        if type(value[key]) is not int or not 1 <= value[key] <= upper:
            raise ValueError(f'{key} must be between 1 and {upper}')
    if value['date_field'] not in ('first_seen_at', 'posted_at', 'fetched_at'):
        raise ValueError('Invalid date_field')
    if value['sort_order'] not in ('newest_first', 'oldest_first'):
        raise ValueError('Invalid sort_order')
    for key in ('date_from', 'date_to', 'as_of'):
        if value[key] is not None and not isinstance(value[key], str):
            raise ValueError(f'{key} must be an ISO timestamp or null')
    sources, ids = value['sources'], value['posting_ids']
    if not isinstance(sources, list) or len(sources) > 100 or any(
            not isinstance(s, str) or not s.strip() for s in sources):
        raise ValueError('sources must be an array of source codes (maximum 100)')
    if not isinstance(ids, list) or len(ids) > 1000 or any(
            type(i) is not int or not 1 <= i <= 9223372036854775807 for i in ids):
        raise ValueError('posting_ids must be an array of positive bigint IDs (maximum 1000)')
    anchor = timestamp(value['as_of']) if value['as_of'] else (now or datetime.now(VIETNAM)).astimezone(VIETNAM)
    end = timestamp(value['date_to']) if value['date_to'] else anchor
    start = timestamp(value['date_from']) if value['date_from'] else end - timedelta(days=value['lookback_days'])
    if start >= end or end > anchor:
        raise ValueError('Require date_from < date_to <= as_of')
    value.update(as_of=anchor.isoformat(), date_from=start.isoformat(), date_to=end.isoformat(),
                 sources=sorted(set(sources)), posting_ids=sorted(set(ids)))
    return value


def selection_query(options):
    # Identifiers are allow-listed by normalize; all values remain bound parameters.
    query = sql.SQL("""
        WITH current_content AS ({})
        SELECT c.*, e.status, coalesce(e.attempts,0) AS attempts,
               (e.id IS NULL OR e.next_attempt_at <= CURRENT_TIMESTAMP) AS due,
               c.{date} AS selection_date
        FROM current_content c LEFT JOIN core.job_enrichments e
          ON e.source_posting_id=c.source_posting_id AND e.input_hash=c.input_hash
          AND e.schema_version=%s AND e.prompt_version=%s
        WHERE (%s::text[]='{{}}' OR c.source=ANY(%s::text[]))
          AND (%s::bigint[]='{{}}' OR c.source_posting_id=ANY(%s::bigint[]))
          AND (c.{date} IS NULL OR (c.{date} >= %s::timestamptz AND c.{date} < %s::timestamptz))
        ORDER BY c.{date} {direction} NULLS LAST,c.source_posting_id {direction}
    """).format(sql.SQL(CURRENT_CONTENT), date=sql.Identifier(options['date_field']),
                direction=sql.SQL('DESC' if options['sort_order'] == 'newest_first' else 'ASC'))
    return query, (VERSION, VERSION, options['sources'], options['sources'],
                   options['posting_ids'], options['posting_ids'], options['date_from'], options['date_to'])


def bucket(row, max_attempts):
    if row['selection_date'] is None:
        return 'missing_date'
    if row['status'] == 'succeeded':
        return 'succeeded'
    if row['status'] == 'failed' or row['attempts'] >= max_attempts:
        return 'failed_or_exhausted'
    if row['status'] == 'processing':
        return 'processing'
    return 'ready' if row['due'] else 'retry_later'


def preview(connection, options, config):
    """Call inside a read-only repeatable-read transaction. Stream unbounded matches."""
    counts, by_source, selected = Counter(), defaultdict(Counter), []
    query, params = selection_query(options)
    with connection.cursor(name='backfill_preview', row_factory=dict_row) as cur:
        cur.execute(query, params)
        for row in cur:
            category = bucket(row, config['max_attempts'])
            counts[category] += 1
            by_source[row['source']][category] += 1
            if category == 'missing_date':
                continue
            counts['matched'] += 1
            by_source[row['source']]['matched'] += 1
            if category == 'ready' and len(selected) < options['max_jobs']:
                selected.append(row)
                by_source[row['source']]['selected'] += 1
    counts['selected'] = len(selected)
    counts['eligible'] = counts['ready'] + counts['retry_later']
    # Always print zeros so an empty preview has an unambiguous meaning.
    for key in ('matched', 'missing_date', 'succeeded', 'failed_or_exhausted', 'processing',
                'ready', 'retry_later'):
        counts.setdefault(key, 0)
    providers = []
    store = Store(connection)
    for provider in config['providers']:
        if not provider.get('enabled', True):
            continue
        usage = connection.execute("""SELECT count(*),
            coalesce(sum(coalesce(actual_tokens,reserved_tokens)),0)
            FROM core.enrichment_attempts WHERE provider=%s
            AND started_at > CURRENT_TIMESTAMP-interval '24 hours'""", (provider['name'],)).fetchone()
        blocked = connection.execute('SELECT blocked_until FROM core.enrichment_provider_state WHERE provider=%s',
                                     (provider['name'],)).fetchone()
        output_cap = provider.get('max_output_tokens', config['max_output_tokens'])
        ratios = {batch: store.input_token_ratio(provider, batch=batch)
                  if config.get('calibrate_input_tokens', False) else 0.5 for batch in (False, True)}
        estimates = [estimate_tokens(row['input_payload'], output_cap, ratio=ratios[False]) for row in selected]
        remaining = [dict(row, id=row['source_posting_id']) for row in selected]
        planned_tokens, planned_requests = 0, 0
        while remaining:
            head = remaining[0]
            group = group_jobs(head, [row for row in remaining[1:] if row['attempts'] == 0],
                               provider, output_cap, ratio=ratios[True])
            payload = group if len(group) > 1 else head['input_payload']
            planned_tokens += estimate_tokens(payload, output_cap * len(group), ratio=ratios[len(group) > 1], batch=len(group) > 1)
            planned_requests += 1
            used_ids = {row['id'] for row in group}
            remaining = [row for row in remaining if row['id'] not in used_ids]
        providers.append(dict(provider=provider['name'], key_configured=bool(os.getenv(provider['key_env'])),
                              enforce_daily_budget=provider.get('enforce_daily_budget', True),
                              used_requests_24h=usage[0], used_tokens_24h=usage[1],
                              remaining_requests_24h=(max(0, provider['requests_per_day'] - usage[0])
                                  if provider.get('enforce_daily_budget', True) else None),
                              remaining_tokens_24h=(max(0, provider['tokens_per_day'] - usage[1])
                                  if provider.get('enforce_daily_budget', True) else None),
                              blocked_until=blocked[0].astimezone(VIETNAM).isoformat() if blocked else None,
                              batch_size=provider.get('batch_size', 1), planned_requests=planned_requests,
                              selected_estimated_tokens=planned_tokens,
                              single_job_estimated_tokens=sum(estimates),
                              input_tokens_per_byte=ratios[False], batch_input_tokens_per_byte=ratios[True],
                              selected_exceeding_request_budget=sum(t > request_token_limit(provider) for t in estimates)))
    report = dict(options=options, counts=dict(counts), by_source=dict(by_source), providers=providers,
                  sample=[dict(source_posting_id=row['source_posting_id'], title=row['title'], source=row['source'],
                               selection_date=row['selection_date'].astimezone(VIETNAM).isoformat(),
                               status=row['status'] or 'not_enriched') for row in selected[:20]])
    return report, selected


def selected_candidates(selected):
    """Freeze IDs, content hashes and priority; still recheck content/activity at dispatch."""
    scope = [dict(source_posting_id=row['source_posting_id'], input_hash=row['input_hash'], priority=i)
             for i, row in enumerate(selected)]
    return sql.SQL("""SELECT c.*, chosen.priority FROM ({}) c
        JOIN jsonb_to_recordset({}::jsonb)
          AS chosen(source_posting_id bigint,input_hash text,priority integer)
        ON chosen.source_posting_id=c.source_posting_id AND chosen.input_hash=c.input_hash""").format(
            sql.SQL(CURRENT_CONTENT), sql.Literal(Jsonb(scope)))


def run(path='configs/enrichment.yaml', *, options=None):
    from joblake.supabase_sync import configure
    try:
        options = normalize({} if options is None else options)
        config = load_config(path)
        config['max_jobs_per_run'] = options['max_api_attempts']
        configure()
        if not os.getenv('LOCAL_DATABASE_URL'):
            raise ValueError('LOCAL_DATABASE_URL is required')
        with psycopg.connect(os.environ['LOCAL_DATABASE_URL'], autocommit=True, connect_timeout=15) as c:
            c.execute("SET statement_timeout='120s'")
            c.execute("SET lock_timeout='10s'")
            store = Store(c)
            if not options['dry_run']:
                if not store.lock():
                    LOGGER.error('Another enrichment worker is running')
                    return 1
                store.recover()
            with c.transaction():
                c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
                report, selected = preview(c, options, config)
            LOGGER.info('Backfill %s report=%s', 'dry-run' if options['dry_run'] else 'execution',
                        json.dumps(report, ensure_ascii=False, default=str))
            LOGGER.info('Backfill counts: matched=%s succeeded=%s failed_or_exhausted=%s '
                        'processing=%s retry_later=%s ready=%s selected=%s missing_date=%s; max_api_attempts=%s',
                        *(report['counts'][key] for key in ('matched', 'succeeded', 'failed_or_exhausted',
                          'processing', 'retry_later', 'ready', 'selected', 'missing_date')),
                        options['max_api_attempts'])
            LOGGER.info('Selection is not a success guarantee; quota is local rolling-24h accounting. '
                        'Reuse options.as_of/date_from/date_to to repeat this window; data is rechecked each run.')
            if options['dry_run'] or not selected:
                return 0
            store = Store(c, candidates=selected_candidates(selected), ordered_selection=True)
            store.enqueue(recover=False)
            return process(store, config)
    except (ValueError, KeyError, TypeError, OverflowError, OSError, yaml.YAMLError) as exc:
        LOGGER.error('Backfill configuration failure (%s); check parameters and local configuration', type(exc).__name__)
        return 2
    except psycopg.Error as exc:
        LOGGER.error('Backfill database failure (%s, SQLSTATE=%s)', type(exc).__name__, exc.sqlstate)
        return 1
