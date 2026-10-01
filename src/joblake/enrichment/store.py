"""Persistent queue and rolling quota ledger. One session lock guards dispatch."""
from datetime import datetime, timedelta, timezone

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from joblake.enrichment.schema import VERSION


class Store:
    def __init__(self, connection):
        self.c = connection

    def lock(self):
        return self.c.execute('SELECT pg_try_advisory_lock(741205, 2)').fetchone()[0]

    def enqueue(self):
        with self.c.transaction():
            # Recover interrupted work. The session lock guarantees no live worker owns it.
            self.c.execute("""UPDATE core.job_enrichments SET status='retry_wait',
                next_attempt_at=now(), error_code='interrupted', updated_at=now()
                WHERE status='processing'""")
            self.c.execute("""UPDATE core.enrichment_attempts SET status='interrupted',
                finished_at=now() WHERE status='processing'""")
            self.c.execute("""UPDATE core.job_enrichments e SET status='superseded',updated_at=now()
                WHERE status IN ('pending','retry_wait') AND NOT EXISTS (
                    SELECT 1 FROM core.enrichment_candidates c
                    WHERE c.source_posting_id=e.source_posting_id AND c.input_hash=e.input_hash)""")
            self.c.execute("""INSERT INTO core.job_enrichments
                (source_posting_id,parse_result_id,input_hash,input_payload,schema_version,prompt_version)
                SELECT source_posting_id,parse_result_id,input_hash,input_payload,%s,%s
                FROM core.enrichment_candidates ON CONFLICT DO NOTHING""", (VERSION, VERSION))
            # Reuse queued/failed state if content returns; succeeded results remain cached.
            self.c.execute("""UPDATE core.job_enrichments e SET status='pending',updated_at=now()
                FROM core.enrichment_candidates c WHERE e.status='superseded'
                AND e.source_posting_id=c.source_posting_id AND e.input_hash=c.input_hash""")

    def next_job(self, max_attempts):
        self.c.execute("""UPDATE core.job_enrichments SET status='failed',updated_at=now()
            WHERE status IN ('pending','retry_wait') AND attempts >= %s""", (max_attempts,))
        with self.c.cursor(row_factory=dict_row) as cur:
            cur.execute("""SELECT e.* FROM core.job_enrichments e
                JOIN core.enrichment_candidates c ON c.source_posting_id=e.source_posting_id
                    AND c.input_hash=e.input_hash
                WHERE e.status IN ('pending','retry_wait') AND e.next_attempt_at <= now()
                  AND e.attempts < %s
                ORDER BY e.next_attempt_at,e.id LIMIT 1""", (max_attempts,))
            return cur.fetchone()

    def reserve(self, job, provider, tokens):
        """Reserve before the request; crashed/unknown attempts keep their reservation.

        A rolling 24h window is intentionally conservative across provider reset zones.
        Minute limits are rolling too, not calendar-minute counters.
        """
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
            if (rpd >= provider['requests_per_day'] or tpd + tokens > provider['tokens_per_day']
                    or rpm >= provider['requests_per_minute'] or tpm + tokens > provider['tokens_per_minute']):
                return None
            # Recheck after dispatch delay; never enrich content known to be superseded.
            if not self.c.execute("""SELECT 1 FROM core.enrichment_candidates
                WHERE source_posting_id=%s AND input_hash=%s""",
                (job['source_posting_id'], job['input_hash'])).fetchone():
                return None
            self.c.execute("""UPDATE core.job_enrichments SET status='processing',
                attempts=attempts+1,provider=%s,model=%s,updated_at=now() WHERE id=%s""",
                (provider['name'], provider['model'], job['id']))
            return self.c.execute("""INSERT INTO core.enrichment_attempts
                (enrichment_id,provider,model,reserved_tokens) VALUES (%s,%s,%s,%s) RETURNING id""",
                (job['id'], provider['name'], provider['model'], tokens)).fetchone()[0]

    def finish(self, job, attempt, *, result=None, tokens=None, error=None, max_attempts=3):
        with self.c.transaction():
            status = 'succeeded' if error is None else ('failed' if job['attempts'] + 1 >= max_attempts else 'retry_wait')
            self.c.execute("""UPDATE core.enrichment_attempts SET status=%s,actual_tokens=%s,
                error_code=%s,finished_at=now() WHERE id=%s""", (status, tokens, error, attempt))
            self.c.execute("""UPDATE core.job_enrichments SET status=%s,result=%s,error_code=%s,
                next_attempt_at=now()+interval '15 minutes',updated_at=now() WHERE id=%s""",
                (status, Jsonb(result) if result is not None else None, error, job['id']))

    def block(self, name, code, seconds):
        if seconds:
            self.c.execute("""INSERT INTO core.enrichment_provider_state(provider,blocked_until,error_code)
                VALUES (%s,%s,%s) ON CONFLICT(provider) DO UPDATE
                SET blocked_until=excluded.blocked_until,error_code=excluded.error_code""",
                (name, datetime.now(timezone.utc) + timedelta(seconds=seconds), code))

    def can_retry_soon(self, providers, tokens):
        """Don't hold an Airflow slot for a daily quota or a long provider outage."""
        for p in providers:
            if tokens > min(p['tokens_per_minute'], p['tokens_per_day']):
                continue
            blocked = self.c.execute("""SELECT blocked_until > now()+interval '60 seconds'
                FROM core.enrichment_provider_state WHERE provider=%s""", (p['name'],)).fetchone()
            if blocked and blocked[0]:
                continue
            requests, used = self.c.execute("""SELECT count(*),
                coalesce(sum(coalesce(actual_tokens,reserved_tokens)),0)
                FROM core.enrichment_attempts WHERE provider=%s
                AND started_at > now()-interval '24 hours'""", (p['name'],)).fetchone()
            if requests < p['requests_per_day'] and used + tokens <= p['tokens_per_day']:
                return True
        return False

    def summary(self):
        return dict(self.c.execute('SELECT status,count(*) FROM core.job_enrichments GROUP BY status').fetchall())
