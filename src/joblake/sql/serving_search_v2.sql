-- Additive filter contract. Keep search_jobs v1 for rollback.
SET LOCAL lock_timeout='10s';
SET LOCAL statement_timeout='120s';
SELECT pg_advisory_xact_lock(741205, 1);
ALTER TABLE serving.jobs ADD COLUMN IF NOT EXISTS first_seen_at timestamptz;
CREATE INDEX IF NOT EXISTS jobs_effective_date_idx ON serving.jobs
 ((coalesce(posted_at,first_seen_at)) DESC NULLS LAST, id DESC);

CREATE OR REPLACE FUNCTION serving.search_jobs_v2(
 p_query text DEFAULT '', p_sources text[] DEFAULT '{}', p_cities text[] DEFAULT '{}',
 p_experience text DEFAULT '', p_seniority text[] DEFAULT '{}', p_modes text[] DEFAULT '{}',
 p_days integer DEFAULT 0, p_sort text DEFAULT 'relevance',
 p_limit integer DEFAULT 20, p_offset integer DEFAULT 0
)
RETURNS TABLE (
 id bigint,title text,employer_name_raw text,canonical_url text,
 source_code text,source_name text,location_cities text[],salary_raw text,
 employment_type_raw text,experience_raw text,posted_at timestamptz,last_seen_at timestamptz,
 first_seen_at timestamptz,experience_min_years double precision,experience_max_years double precision,
 seniority_levels text[],work_mode text,employment_type text,enrichment_status text,score real
)
LANGUAGE plpgsql STABLE SECURITY INVOKER SET search_path=''
AS $$
DECLARE
 q tsquery; normalized text; tail text; head text; terms text[];
 term_query tsquery; tail_query tsquery; term_index integer;
BEGIN
 IF p_limit IS NULL OR p_limit NOT BETWEEN 1 AND 100 OR p_offset IS NULL OR p_offset NOT BETWEEN 0 AND 10000
 OR length(coalesce(p_query,''))>200 OR p_days IS NULL OR p_days NOT IN (0,1,7,30)
 OR p_sort IS NULL OR p_sort NOT IN ('relevance','newest')
 OR p_experience IS NULL OR p_experience NOT IN ('','zero','under1','1to3','3to5','5plus','unknown')
 OR p_sources IS NULL OR p_cities IS NULL OR p_seniority IS NULL OR p_modes IS NULL
 OR cardinality(p_sources)>20 OR cardinality(p_cities)>20 OR cardinality(p_seniority)>9 OR cardinality(p_modes)>4
 OR EXISTS(SELECT 1 FROM unnest(p_sources) x WHERE x IS NULL OR x !~ '^[a-z0-9_-]{1,50}$')
 OR EXISTS(SELECT 1 FROM unnest(p_cities) x WHERE x IS NULL OR length(x) NOT BETWEEN 1 AND 120 OR x ~ '[[:cntrl:]]')
 OR EXISTS(SELECT 1 FROM unnest(p_seniority) x WHERE x IS NULL OR x NOT IN ('intern','fresher','junior','middle','senior','lead','manager','director','unknown'))
 OR EXISTS(SELECT 1 FROM unnest(p_modes) x WHERE x IS NULL OR x NOT IN ('onsite','hybrid','remote','unknown'))
 THEN RAISE EXCEPTION 'Invalid search filters' USING ERRCODE='22023'; END IF;
 IF btrim(COALESCE(p_query,'')) <> '' THEN
   q := websearch_to_tsquery('pg_catalog.simple', serving.normalize_search(p_query));
   IF numnode(q) = 0 THEN RETURN; END IF;
   normalized := regexp_replace(serving.normalize_search(p_query), '[[:space:]]+$', '');
   -- Preserve web-search syntax, including lowercase OR. An internal hyphen
   -- belongs to a technology name, not to the exclusion operator.
   IF normalized !~ '"'
      AND normalized !~ '(^|[^[:alnum:]_-])or($|[^[:alnum:]_-])'
      AND normalized !~ '(^|[^[:alnum:]_])-'
   THEN
     tail := substring(normalized FROM '[^[:space:]]+$');
     head := left(normalized, length(normalized) - length(tail));
     -- Let PostgreSQL tokenize aliases, punctuation, hosts and Unicode.
     -- For a final hyphenated word use its parts: the full compound would
     -- otherwise require the unfinished spelling to match exactly.
     SELECT array_agg(l.lexeme ORDER BY d.ordinality, l.ordinality)
       INTO terms
       FROM ts_debug('pg_catalog.simple', tail) WITH ORDINALITY AS d
       CROSS JOIN LATERAL unnest(d.lexemes) WITH ORDINALITY AS l(lexeme, ordinality)
       WHERE d.alias NOT IN ('asciihword', 'numhword', 'hword');
     IF length(terms[array_length(terms, 1)]) >= 3 THEN
       FOR term_index IN 1..array_length(terms, 1) LOOP
         -- tsvector output quotes/escapes an already normalized lexeme.
         -- No raw input is interpreted as tsquery syntax or dynamic SQL.
         term_query := (array_to_tsvector(ARRAY[terms[term_index]])::text ||
           CASE WHEN term_index = array_length(terms, 1) THEN ':*' ELSE '' END)::tsquery;
         tail_query := CASE WHEN tail_query IS NULL THEN term_query
                            ELSE tail_query && term_query END;
       END LOOP;
       q := websearch_to_tsquery('pg_catalog.simple', head);
       q := CASE WHEN numnode(q) = 0 THEN tail_query ELSE q && tail_query END;
     END IF;
   END IF;
 END IF;

 RETURN QUERY
 SELECT j.id,j.title,j.employer_name_raw,j.canonical_url,s.code,s.display_name,j.location_cities,
 j.salary_raw,j.employment_type_raw,j.experience_raw,j.posted_at,j.last_seen_at,j.first_seen_at,
 j.experience_min_years,j.experience_max_years,j.seniority_levels,j.work_mode,j.employment_type,j.enrichment_status,
 CASE WHEN q IS NULL THEN 0::real ELSE ts_rank(j.search_vector,q) END AS score
 FROM serving.jobs j JOIN serving.sources s ON s.id=j.source_id
 CROSS JOIN LATERAL (SELECT
   CASE WHEN j.enrichment_status='succeeded' AND j.experience_min_years BETWEEN 0 AND 60
     AND (j.experience_max_years IS NULL OR (j.experience_max_years BETWEEN j.experience_min_years AND 60))
     THEN j.experience_min_years END AS exp,
   CASE WHEN j.enrichment_status='succeeded' THEN
     ARRAY(SELECT x FROM unnest(j.seniority_levels) x WHERE x IN ('intern','fresher','junior','middle','senior','lead','manager','director')) ELSE '{}'::text[] END AS levels,
   CASE WHEN j.enrichment_status='succeeded' AND j.work_mode IN ('onsite','hybrid','remote') THEN j.work_mode END AS mode
 ) e
 WHERE (q IS NULL OR j.search_vector @@ q)
 AND (cardinality(p_sources)=0 OR s.code=ANY(p_sources))
 AND (cardinality(p_cities)=0 OR j.location_cities && p_cities)
 AND (p_experience='' OR (p_experience='unknown' AND e.exp IS NULL)
   OR (p_experience='zero' AND e.exp=0) OR (p_experience='under1' AND e.exp>0 AND e.exp<1)
   OR (p_experience='1to3' AND e.exp>=1 AND e.exp<3) OR (p_experience='3to5' AND e.exp>=3 AND e.exp<5)
   OR (p_experience='5plus' AND e.exp>=5))
 AND (cardinality(p_seniority)=0 OR e.levels && p_seniority OR ('unknown'=ANY(p_seniority) AND cardinality(e.levels)=0))
 AND (cardinality(p_modes)=0 OR e.mode=ANY(p_modes) OR ('unknown'=ANY(p_modes) AND e.mode IS NULL))
 AND (p_days=0 OR coalesce(j.posted_at,j.first_seen_at) BETWEEN CURRENT_TIMESTAMP - make_interval(days=>p_days) AND CURRENT_TIMESTAMP)
 ORDER BY CASE WHEN p_sort='relevance' THEN CASE WHEN q IS NULL THEN 0::real ELSE ts_rank(j.search_vector,q) END END DESC,
 coalesce(j.posted_at,j.first_seen_at) DESC NULLS LAST,j.id DESC
 LIMIT p_limit OFFSET p_offset;
END
$$;
REVOKE ALL ON FUNCTION serving.search_jobs_v2(text,text[],text[],text,text[],text[],integer,text,integer,integer) FROM PUBLIC;
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='joblake_web_reader') THEN
 GRANT EXECUTE ON FUNCTION serving.search_jobs_v2(text,text[],text[],text,text[],text[],integer,text,integer,integer) TO joblake_web_reader;
 END IF;
END $$;
NOTIFY pgrst,'reload schema';
