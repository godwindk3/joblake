-- enrichment_attempts remains the request/quota ledger: exactly one row per API call.
ALTER TABLE core.enrichment_attempts
    ADD COLUMN item_count integer NOT NULL DEFAULT 1 CHECK (item_count BETWEEN 1 AND 3),
    ADD COLUMN purpose text NOT NULL DEFAULT 'production' CHECK (purpose IN ('production','benchmark')),
    ADD COLUMN input_bytes integer CHECK (input_bytes > 0),
    ADD COLUMN input_tokens integer CHECK (input_tokens >= 0),
    ADD COLUMN output_tokens integer CHECK (output_tokens >= 0);

CREATE TABLE core.enrichment_attempt_jobs (
    attempt_id bigint NOT NULL REFERENCES core.enrichment_attempts(id) ON DELETE CASCADE,
    enrichment_id bigint NOT NULL REFERENCES core.job_enrichments(id) ON DELETE CASCADE,
    status text NOT NULL DEFAULT 'processing',
    error_code text,
    PRIMARY KEY (attempt_id, enrichment_id)
);
CREATE INDEX enrichment_attempt_jobs_enrichment_idx ON core.enrichment_attempt_jobs(enrichment_id);
INSERT INTO core.enrichment_attempt_jobs(attempt_id,enrichment_id,status,error_code)
SELECT id,enrichment_id,status,error_code FROM core.enrichment_attempts WHERE enrichment_id IS NOT NULL;
