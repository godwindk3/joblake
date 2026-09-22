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
DECLARE
 q tsquery;
 normalized text;
 tail text;
 head text;
 terms text[];
 term_query tsquery;
 tail_query tsquery;
 term_index integer;
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
