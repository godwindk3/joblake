"""Persistent queue and rolling quota ledger. One session lock guards dispatch."""
from datetime import datetime, timedelta, timezone

from psycopg.rows import dict_row
from psycopg import sql
from psycopg.types.json import Jsonb

from joblake.enrichment.schema import VERSION
from joblake.enrichment.candidates import CURRENT_CONTENT


def request_token_limit(provider):
    """Keep minute pacing even when the API owns the daily limit."""
    if not provider.get('enforce_daily_budget', True):
        return provider['tokens_per_minute']
    return min(provider['tokens_per_minute'], provider['tokens_per_day'])


class Store:
    def __init__(self, connection, *, candidates=None, ordered_selection=False):
        self.c = connection
        self.candidates = candidates if candidates is not None else sql.SQL(
            'SELECT * FROM core.enrichment_candidates')
        self.order = sql.SQL('c.priority,e.id' if ordered_selection else 'e.next_attempt_at,e.id')

    def lock(self):
        return self.c.execute('SELECT pg_try_advisory_lock(741205, 2)').fetchone()[0]

    def recover(self):
        with self.c.transaction():
            # Recover interrupted work. The session lock guarantees no live worker owns it.
            self.c.execute("""UPDATE core.job_enrichments SET status='retry_wait',
                next_attempt_at=now(), error_code='interrupted', updated_at=now()
                WHERE status='processing'""")
            self.c.execute("""UPDATE core.enrichment_attempt_jobs SET status='interrupted',
                error_code='interrupted' WHERE status='processing'""")
            self.c.execute("""UPDATE core.enrichment_attempts SET status='interrupted',
                finished_at=now() WHERE status='processing'""")
            self.c.execute(sql.SQL("""UPDATE core.job_enrichments e SET status='superseded',updated_at=now()
                WHERE status IN ('pending','retry_wait') AND NOT EXISTS (
                    SELECT 1 FROM ({}) c
                    WHERE c.source_posting_id=e.source_posting_id AND c.input_hash=e.input_hash)""").format(
                        sql.SQL(CURRENT_CONTENT)))

    def enqueue(self, *, recover=True):
        if recover:
            self.recover()
        with self.c.transaction():
            self.c.execute(sql.SQL("""INSERT INTO core.job_enrichments
                (source_posting_id,parse_result_id,input_hash,input_payload,schema_version,prompt_version)
                SELECT source_posting_id,parse_result_id,input_hash,input_payload,%s,%s
                FROM ({}) c ON CONFLICT DO NOTHING""").format(self.candidates), (VERSION, VERSION))
            # Reuse queued/failed state if content returns; succeeded results remain cached.
            self.c.execute(sql.SQL("""UPDATE core.job_enrichments e SET status='pending',updated_at=now()
                FROM ({}) c WHERE e.status='superseded'
                AND e.source_posting_id=c.source_posting_id AND e.input_hash=c.input_hash
                AND e.schema_version=%s AND e.prompt_version=%s""").format(self.candidates), (VERSION, VERSION))

    def next_job(self, max_attempts):
        self.c.execute(sql.SQL("""UPDATE core.job_enrichments e SET status='failed',updated_at=now()
            FROM ({}) c WHERE e.source_posting_id=c.source_posting_id AND e.input_hash=c.input_hash
            AND e.schema_version=%s AND e.prompt_version=%s
            AND e.status IN ('pending','retry_wait') AND e.attempts >= %s""").format(self.candidates),
            (VERSION, VERSION, max_attempts))
        with self.c.cursor(row_factory=dict_row) as cur:
            cur.execute(sql.SQL("""SELECT e.* FROM core.job_enrichments e
                JOIN ({}) c ON c.source_posting_id=e.source_posting_id
                    AND c.input_hash=e.input_hash
                WHERE e.status IN ('pending','retry_wait') AND e.next_attempt_at <= now()
                  AND e.attempts < %s
                  AND e.schema_version=%s AND e.prompt_version=%s
                ORDER BY {} LIMIT 1""").format(self.candidates, self.order), (max_attempts, VERSION, VERSION))
            return cur.fetchone()

    def batch_followers(self, job, max_attempts, limit=2):
        with self.c.cursor(row_factory=dict_row) as cur:
            cur.execute(sql.SQL("""SELECT e.* FROM core.job_enrichments e
                JOIN ({}) c ON c.source_posting_id=e.source_posting_id AND c.input_hash=e.input_hash
                WHERE e.status IN ('pending','retry_wait') AND e.next_attempt_at <= now()
                  AND e.attempts=0 AND e.attempts < %s AND e.id<>%s
                  AND e.schema_version=%s AND e.prompt_version=%s
                ORDER BY {} LIMIT %s""").format(self.candidates, self.order),
                (max_attempts, job['id'], VERSION, VERSION, limit))
            return cur.fetchall()

    def input_token_ratio(self, provider, *, batch=False):
        """Only learn from provider input usage, never from total/output tokens."""
        row = self.c.execute("""SELECT count(*),percentile_cont(0.95) WITHIN GROUP
            (ORDER BY input_tokens::double precision/input_bytes) FROM (
                SELECT input_tokens,input_bytes FROM core.enrichment_attempts
                WHERE provider=%s AND model=%s AND input_bytes>0 AND input_tokens>0
                  AND (item_count>1)=%s AND started_at>now()-interval '30 days'
                ORDER BY started_at DESC LIMIT 100) samples""",
                (provider['name'], provider['model'], batch)).fetchone()
        if row[0] < 20:
            return 0.5
        # Headroom and conservative floor; ratios >0.5 are allowed to correct underestimates.
        return max(0.25, row[1] * 1.25)

    def reserve(self, job, provider, tokens, **kwargs):
        return self.reserve_batch([job], provider, tokens, **kwargs)

    def reserve_batch(self, jobs, provider, tokens, *, input_bytes=None, purpose='production', max_attempts=3):
        """Reserve before the request; crashed/unknown attempts keep their reservation.

        A rolling 24h window is intentionally conservative across provider reset zones.
        Minute limits are rolling too, not calendar-minute counters.
        """
        if not 1 <= len(jobs) <= 3 or len({j['id'] for j in jobs}) != len(jobs):
            raise ValueError('invalid_request_members')
        if purpose not in ('production', 'benchmark'):
            raise ValueError('invalid_request_purpose')
        with self.c.transaction():
            blocked = self.c.execute("""SELECT blocked_until > now()
                FROM core.enrichment_provider_state WHERE provider=%s""", (provider['name'],)).fetchone()
            if blocked and blocked[0]:
                return None
            counts = self.c.execute("""SELECT count(*),
                coalesce(sum(coalesce(actual_tokens,reserved_tokens)),0),
                count(*) FILTER (WHERE started_at > now()-interval '60 seconds'),
                coalesce(sum(coalesce(actual_tokens,reserved_tokens))
                    FILTER (WHERE started_at > now()-interval '60 seconds'),0)
                FROM core.enrichment_attempts WHERE provider=%s
                    AND started_at > now()-interval '24 hours'""", (provider['name'],)).fetchone()
            rpd, tpd, rpm, tpm = counts
            daily_exhausted = provider.get('enforce_daily_budget', True) and (
                rpd >= provider['requests_per_day'] or tpd + tokens > provider['tokens_per_day'])
            if (daily_exhausted or rpm >= provider['requests_per_minute']
                    or tpm + tokens > provider['tokens_per_minute']):
                return None
            if purpose == 'production':
                # Check every member before writing anything; a stale group consumes no quota.
                for job in jobs:
                    if not self.c.execute(sql.SQL("""SELECT 1 FROM ({}) c
                        JOIN core.job_enrichments e ON e.source_posting_id=c.source_posting_id
                          AND e.input_hash=c.input_hash
                        WHERE e.id=%s AND e.input_hash=%s AND e.status IN ('pending','retry_wait')
                          AND e.next_attempt_at<=now() AND e.attempts<%s
                          AND e.schema_version=%s AND e.prompt_version=%s""").format(self.candidates),
                        (job['id'], job['input_hash'], max_attempts, VERSION, VERSION)).fetchone():
                        return None
            request_id = self.c.execute("""INSERT INTO core.enrichment_attempts
                (enrichment_id,provider,model,reserved_tokens,item_count,input_bytes,purpose)
                VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                (jobs[0]['id'] if len(jobs) == 1 and purpose == 'production' else None,
                 provider['name'], provider['model'], tokens, len(jobs), input_bytes, purpose)).fetchone()[0]
            if purpose == 'production':
                for job in jobs:
                    self.c.execute("""UPDATE core.job_enrichments SET status='processing',
                        attempts=attempts+1,provider=%s,model=%s,updated_at=now() WHERE id=%s""",
                        (provider['name'], provider['model'], job['id']))
                    self.c.execute('INSERT INTO core.enrichment_attempt_jobs(attempt_id,enrichment_id) VALUES (%s,%s)',
                                   (request_id, job['id']))
            return request_id

    def finish(self, job, attempt, *, result=None, tokens=None, error=None, max_attempts=3,
               input_tokens=None, output_tokens=None):
        self.finish_batch([job], attempt, {job['id']: (result, error)}, tokens=tokens, max_attempts=max_attempts,
                          input_tokens=input_tokens, output_tokens=output_tokens)

    def finish_batch(self, jobs, attempt, outcomes, *, tokens=None, input_tokens=None,
                     output_tokens=None, max_attempts=3, purpose='production'):
        if set(outcomes) != {j['id'] for j in jobs}:
            raise ValueError('request_outcomes_must_match_jobs')
        with self.c.transaction():
            statuses, errors = [], []
            for job in jobs:
                result, error = outcomes[job['id']]
                status = 'succeeded' if error is None else ('failed' if job.get('attempts', 0) + 1 >= max_attempts else 'retry_wait')
                statuses.append(status)
                if error:
                    errors.append(error)
                if purpose == 'production':
                    self.c.execute("""UPDATE core.enrichment_attempt_jobs SET status=%s,error_code=%s
                        WHERE attempt_id=%s AND enrichment_id=%s""", (status, error, attempt, job['id']))
                    self.c.execute("""UPDATE core.job_enrichments SET status=%s,result=%s,error_code=%s,
                        next_attempt_at=now()+interval '15 minutes',updated_at=now() WHERE id=%s""",
                        (status, Jsonb(result) if result is not None else None, error, job['id']))
            request_status = statuses[0] if len(set(statuses)) == 1 else 'partial'
            self.c.execute("""UPDATE core.enrichment_attempts SET status=%s,actual_tokens=%s,
                input_tokens=%s,output_tokens=%s,error_code=%s,finished_at=now() WHERE id=%s""",
                (request_status, tokens, input_tokens, output_tokens,
                 errors[0] if len(set(errors)) == 1 else 'partial_failure' if errors else None, attempt))

    def block(self, name, code, seconds):
        if seconds:
            self.c.execute("""INSERT INTO core.enrichment_provider_state(provider,blocked_until,error_code)
                VALUES (%s,%s,%s) ON CONFLICT(provider) DO UPDATE
                SET blocked_until=excluded.blocked_until,error_code=excluded.error_code""",
                (name, datetime.now(timezone.utc) + timedelta(seconds=seconds), code))

    def can_retry_soon(self, providers, tokens):
        """Don't hold an Airflow slot for a daily quota or a long provider outage."""
        for p in providers:
            if tokens > request_token_limit(p):
                continue
            blocked = self.c.execute("""SELECT blocked_until > now()+interval '60 seconds'
                FROM core.enrichment_provider_state WHERE provider=%s""", (p['name'],)).fetchone()
            if blocked and blocked[0]:
                continue
            if not p.get('enforce_daily_budget', True):
                return True
            requests, used = self.c.execute("""SELECT count(*),
                coalesce(sum(coalesce(actual_tokens,reserved_tokens)),0)
                FROM core.enrichment_attempts WHERE provider=%s
                AND started_at > now()-interval '24 hours'""", (p['name'],)).fetchone()
            if requests < p['requests_per_day'] and used + tokens <= p['tokens_per_day']:
                return True
        return False

    def summary(self):
        return dict(self.c.execute('SELECT status,count(*) FROM core.job_enrichments GROUP BY status').fetchall())
