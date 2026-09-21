-- Additive remote serving migration; run once after serving.sources/jobs exist.
SET LOCAL lock_timeout = '10s';
SET LOCAL statement_timeout = '120s';
SELECT pg_advisory_xact_lock(741205, 1);
CREATE SCHEMA IF NOT EXISTS extensions;
CREATE EXTENSION IF NOT EXISTS unaccent WITH SCHEMA extensions;

CREATE FUNCTION serving.normalize_search(p_text text)
RETURNS text LANGUAGE sql STABLE SECURITY INVOKER SET search_path = ''
AS $$
 SELECT regexp_replace(
          regexp_replace(
           regexp_replace(
            regexp_replace(lower(extensions.unaccent(COALESCE(p_text,''))),
              '(^|[^a-z0-9_])c\+\+($|[^a-z0-9_+])', '\1cplusplus\2', 'g'),
              '(^|[^a-z0-9_])c#($|[^a-z0-9_])', '\1csharp\2', 'g'),
              '(^|[^a-z0-9_])\.net\M', '\1dotnet', 'g'),
              '\mnode\.js\M', 'nodejs', 'g')
$$;

CREATE FUNCTION serving.build_job_search(p_title text, p_skills text[], p_employer text, p_categories text[])
RETURNS tsvector LANGUAGE sql STABLE SECURITY INVOKER SET search_path = ''
AS $$
 SELECT setweight(to_tsvector('pg_catalog.simple', serving.normalize_search(
            COALESCE(p_title,'') || ' ' || COALESCE(array_to_string(p_skills,' '),''))), 'A')
     || setweight(to_tsvector('pg_catalog.simple', serving.normalize_search(
            COALESCE(p_employer,'') || ' ' || COALESCE(array_to_string(p_categories,' '),''))), 'B')
$$;

ALTER TABLE serving.jobs ADD COLUMN search_vector tsvector;
CREATE FUNCTION serving.refresh_job_search()
RETURNS trigger LANGUAGE plpgsql SECURITY INVOKER SET search_path = ''
AS $$
BEGIN
 IF TG_OP = 'INSERT' THEN
   NEW.search_vector := serving.build_job_search(NEW.title,NEW.skills_raw,NEW.employer_name_raw,NEW.categories_raw);
 ELSIF (NEW.title,NEW.skills_raw,NEW.employer_name_raw,NEW.categories_raw)
       IS DISTINCT FROM (OLD.title,OLD.skills_raw,OLD.employer_name_raw,OLD.categories_raw)
       OR NEW.search_vector IS DISTINCT FROM OLD.search_vector THEN
   NEW.search_vector := serving.build_job_search(NEW.title,NEW.skills_raw,NEW.employer_name_raw,NEW.categories_raw);
 END IF;
 RETURN NEW;
END
$$;
CREATE TRIGGER jobs_refresh_search
BEFORE INSERT OR UPDATE OF title,skills_raw,employer_name_raw,categories_raw,search_vector
ON serving.jobs FOR EACH ROW EXECUTE FUNCTION serving.refresh_job_search();

UPDATE serving.jobs SET search_vector =
 serving.build_job_search(title,skills_raw,employer_name_raw,categories_raw);
ALTER TABLE serving.jobs ALTER COLUMN search_vector SET NOT NULL;
CREATE INDEX jobs_search_vector_idx ON serving.jobs USING gin(search_vector);
CREATE INDEX jobs_location_cities_idx ON serving.jobs USING gin(location_cities);

CREATE FUNCTION serving.search_jobs(
 p_query text DEFAULT '',
 p_source_code text DEFAULT NULL,
 p_city text DEFAULT NULL,
 p_limit integer DEFAULT 20,
 p_offset integer DEFAULT 0
)
RETURNS TABLE (
 id bigint, title text, employer_name_raw text, canonical_url text,
 source_code text, source_name text, location_cities text[],
 salary_raw text, employment_type_raw text, experience_raw text,
 posted_at timestamptz, last_seen_at timestamptz, score real
)
LANGUAGE plpgsql STABLE SECURITY INVOKER SET search_path = ''
AS $$
DECLARE q tsquery;
BEGIN
 IF p_limit IS NULL OR p_limit < 1 OR p_limit > 100
    OR p_offset IS NULL OR p_offset < 0 OR p_offset > 10000 THEN
   RAISE EXCEPTION 'limit must be 1..100; offset must be 0..10000' USING ERRCODE='22023';
 END IF;
 IF length(COALESCE(p_query,'')) > 200 THEN
   RAISE EXCEPTION 'query must be at most 200 characters' USING ERRCODE='22023';
 END IF;
 IF btrim(COALESCE(p_query,'')) <> '' THEN
   q := websearch_to_tsquery('pg_catalog.simple', serving.normalize_search(p_query));
   IF numnode(q) = 0 THEN RETURN; END IF;
 END IF;
 RETURN QUERY
 SELECT j.id,j.title,j.employer_name_raw,j.canonical_url,
        s.code,s.display_name,j.location_cities,j.salary_raw,j.employment_type_raw,
        j.experience_raw,j.posted_at,j.last_seen_at,
        CASE WHEN q IS NULL THEN 0::real ELSE ts_rank(j.search_vector,q) END AS score
 FROM serving.jobs j JOIN serving.sources s ON s.id=j.source_id
 WHERE (q IS NULL OR j.search_vector @@ q)
   AND (p_source_code IS NULL OR s.code=p_source_code)
   AND (p_city IS NULL OR j.location_cities @> ARRAY[p_city]::text[])
 ORDER BY score DESC,j.posted_at DESC NULLS LAST,j.id DESC
 LIMIT p_limit OFFSET p_offset;
END
$$;

REVOKE ALL ON FUNCTION serving.normalize_search(text) FROM PUBLIC;
REVOKE ALL ON FUNCTION serving.build_job_search(text,text[],text,text[]) FROM PUBLIC;
REVOKE ALL ON FUNCTION serving.refresh_job_search() FROM PUBLIC;
REVOKE ALL ON FUNCTION serving.search_jobs(text,text,text,integer,integer) FROM PUBLIC;
-- Backend-only access. No anon/authenticated policy or public read grants.
DO $$
DECLARE role_name text;
BEGIN
 FOREACH role_name IN ARRAY ARRAY['anon','authenticated','service_role'] LOOP
   IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname=role_name) THEN
     EXECUTE format('REVOKE ALL ON FUNCTION serving.normalize_search(text), serving.build_job_search(text,text[],text,text[]), serving.refresh_job_search(), serving.search_jobs(text,text,text,integer,integer) FROM %I',role_name);
   END IF;
 END LOOP;
 IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='service_role') THEN
   GRANT USAGE ON SCHEMA serving,extensions TO service_role;
   GRANT SELECT ON serving.jobs,serving.sources TO service_role;
   GRANT EXECUTE ON FUNCTION serving.normalize_search(text) TO service_role;
   GRANT EXECUTE ON FUNCTION serving.search_jobs(text,text,text,integer,integer) TO service_role;
 END IF;
END
$$;
COMMENT ON COLUMN serving.jobs.search_vector IS 'FTS v1: title/skills A; employer/categories B; simple + unaccent + technology aliases. Managed by trigger.';
ANALYZE serving.jobs;
NOTIFY pgrst, 'reload schema';
