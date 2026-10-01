-- Additive serving contract. Does not change grants, RLS or existing columns.
ALTER TABLE serving.jobs
    ADD COLUMN IF NOT EXISTS skills_required text[],
    ADD COLUMN IF NOT EXISTS skills_preferred text[],
    ADD COLUMN IF NOT EXISTS experience_min_years double precision,
    ADD COLUMN IF NOT EXISTS experience_max_years double precision,
    ADD COLUMN IF NOT EXISTS seniority_levels text[],
    ADD COLUMN IF NOT EXISTS work_mode text,
    ADD COLUMN IF NOT EXISTS employment_type text,
    ADD COLUMN IF NOT EXISTS enrichment_status text NOT NULL DEFAULT 'not_enriched',
    ADD COLUMN IF NOT EXISTS enriched_at timestamptz;
