-- Function-only upgrade; execute in one transaction after serving_search_v1.sql.
SET LOCAL lock_timeout = '10s';
SET LOCAL statement_timeout = '120s';
SELECT pg_advisory_xact_lock(741205, 1);
CREATE OR REPLACE FUNCTION serving.search_jobs(
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

NOTIFY pgrst, 'reload schema';
