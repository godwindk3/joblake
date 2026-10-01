-- Local-only state. Never expose this schema through the Supabase Data API.
CREATE TABLE core.enrichment_settings (
    id boolean PRIMARY KEY DEFAULT true CHECK (id),
    eligible_from timestamptz NOT NULL
);
INSERT INTO core.enrichment_settings VALUES (true, '2026-09-26T00:00:00+07:00');
CREATE INDEX job_parse_enrichment_cutoff_idx ON core.job_parse_results(fetched_at,source_posting_id)
    WHERE is_current AND quality_status IN ('accepted','partial');

CREATE FUNCTION core.enrichment_input(r core.job_parse_results) RETURNS jsonb
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT jsonb_build_object(
        'title', r.title, 'description_text', r.description_text,
        'requirements_text', r.requirements_text, 'benefits_text', r.benefits_text,
        'skills_raw', r.skills_raw, 'experience_raw', r.experience_raw,
        'employment_type_raw', r.employment_type_raw)
$$;
CREATE FUNCTION core.enrichment_hash(r core.job_parse_results) RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT encode(sha256(convert_to(core.enrichment_input(r)::text, 'UTF8')), 'hex')
$$;

CREATE TABLE core.job_enrichments (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_posting_id bigint NOT NULL REFERENCES core.source_job_postings(id) ON DELETE CASCADE,
    parse_result_id bigint NOT NULL REFERENCES core.job_parse_results(id) ON DELETE CASCADE,
    input_hash text NOT NULL,
    input_payload jsonb NOT NULL,
    schema_version text NOT NULL DEFAULT 'v1',
    prompt_version text NOT NULL DEFAULT 'v1',
    status text NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending','processing','succeeded','retry_wait','failed','superseded')),
    attempts integer NOT NULL DEFAULT 0,
    next_attempt_at timestamptz NOT NULL DEFAULT now(),
    provider text,
    model text,
    result jsonb,
    error_code text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(source_posting_id,input_hash,schema_version,prompt_version),
    CHECK (status <> 'succeeded' OR result IS NOT NULL)
);
CREATE INDEX job_enrichments_queue_idx ON core.job_enrichments(next_attempt_at,id)
    WHERE status IN ('pending','retry_wait');
CREATE TABLE core.enrichment_attempts (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    enrichment_id bigint REFERENCES core.job_enrichments(id) ON DELETE SET NULL,
    provider text NOT NULL,
    model text NOT NULL,
    started_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    reserved_tokens integer NOT NULL,
    actual_tokens integer,
    status text NOT NULL DEFAULT 'processing',
    error_code text
);
CREATE INDEX enrichment_attempts_quota_idx ON core.enrichment_attempts(provider,started_at);
CREATE TABLE core.enrichment_provider_state (
    provider text PRIMARY KEY,
    blocked_until timestamptz NOT NULL DEFAULT now(),
    error_code text
);

-- Persisted cutoff plus pre-cutoff parse history prevents recrawls of unchanged old
-- jobs from becoming a backfill, including installation after the activation date.
CREATE VIEW core.enrichment_candidates AS
SELECT r.id AS parse_result_id, p.id AS source_posting_id,
       core.enrichment_hash(r) AS input_hash, core.enrichment_input(r) AS input_payload
FROM core.job_parse_results r
JOIN core.source_job_postings p ON p.id=r.source_posting_id
JOIN crawl_state.jobs j ON j.id=p.crawler_job_id
CROSS JOIN core.enrichment_settings settings
WHERE r.is_current AND r.quality_status IN ('accepted','partial')
  AND j.listing_status='active' AND r.fetched_at >= settings.eligible_from
  AND NOT EXISTS (
      SELECT 1 FROM core.job_parse_results old
      WHERE old.source_posting_id=p.id AND old.fetched_at < settings.eligible_from
        AND core.enrichment_hash(old)=core.enrichment_hash(r)
  );

CREATE VIEW core.current_job_enrichments AS
SELECT r.id AS parse_result_id, e.status, e.result, e.updated_at AS enriched_at
FROM core.job_parse_results r
JOIN core.job_enrichments e ON e.source_posting_id=r.source_posting_id
    AND e.input_hash=core.enrichment_hash(r)
    AND e.schema_version='v1' AND e.prompt_version='v1'
WHERE r.is_current;
