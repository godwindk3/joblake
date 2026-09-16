-- Apply to an existing core/ref replica before the next supabase-sync.
BEGIN;
ALTER TABLE core.job_parse_results
    ADD COLUMN IF NOT EXISTS location_cities text[] NOT NULL DEFAULT '{}'::text[];
CREATE INDEX IF NOT EXISTS ix_job_parse_results_location_cities
    ON core.job_parse_results USING gin (location_cities);
COMMIT;
