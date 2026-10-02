SET LOCAL lock_timeout='10s';
SET LOCAL statement_timeout='120s';
CREATE OR REPLACE FUNCTION serving.matching_skill_ids(p_query text DEFAULT '', p_sources text[] DEFAULT '{}', p_cities text[] DEFAULT '{}', p_experience text DEFAULT '', p_seniority text[] DEFAULT '{}', p_modes text[] DEFAULT '{}', p_days integer DEFAULT 0, p_skills text[] DEFAULT '{}', p_skill_match text DEFAULT 'any', p_skill_scope text DEFAULT 'required') RETURNS TABLE(id bigint) LANGUAGE sql STABLE SECURITY INVOKER SET search_path='' AS $$
 WITH search AS MATERIALIZED (SELECT serving.skills_search_query(p_query) q) SELECT j.id FROM serving.jobs j JOIN serving.sources s ON s.id=j.source_id
 CROSS JOIN search sq
 CROSS JOIN LATERAL (SELECT
   CASE WHEN j.enrichment_status='succeeded' AND j.experience_min_years BETWEEN 0 AND 60
     AND (j.experience_max_years IS NULL OR (j.experience_max_years BETWEEN j.experience_min_years AND 60))
     THEN j.experience_min_years END AS exp,
   CASE WHEN j.enrichment_status='succeeded' THEN
     ARRAY(SELECT x FROM unnest(j.seniority_levels) x WHERE x IN ('intern','fresher','junior','middle','senior','lead','manager','director')) ELSE '{}'::text[] END AS levels,
   CASE WHEN j.enrichment_status='succeeded' AND j.work_mode IN ('onsite','hybrid','remote') THEN j.work_mode END AS mode
 ) e
 WHERE (sq.q IS NULL OR j.search_vector @@ sq.q)
 AND (cardinality(p_sources)=0 OR s.code=ANY(p_sources))
 AND (cardinality(p_cities)=0 OR j.location_cities && p_cities)
 AND (p_experience='' OR (p_experience='unknown' AND e.exp IS NULL)
   OR (p_experience='zero' AND e.exp=0) OR (p_experience='under1' AND e.exp>0 AND e.exp<1)
   OR (p_experience='1to3' AND e.exp>=1 AND e.exp<3) OR (p_experience='3to5' AND e.exp>=3 AND e.exp<5)
   OR (p_experience='5plus' AND e.exp>=5))
 AND (cardinality(p_seniority)=0 OR e.levels && p_seniority OR ('unknown'=ANY(p_seniority) AND cardinality(e.levels)=0))
 AND (cardinality(p_modes)=0 OR e.mode=ANY(p_modes) OR ('unknown'=ANY(p_modes) AND e.mode IS NULL))
 AND (p_days=0 OR coalesce(j.posted_at,j.first_seen_at) BETWEEN CURRENT_TIMESTAMP - make_interval(days=>p_days) AND CURRENT_TIMESTAMP)
 AND (cardinality(p_skills)=0 OR CASE WHEN p_skill_match='all'
 THEN (CASE WHEN p_skill_scope='all' THEN j.required_skill_keys || j.preferred_skill_keys ELSE j.required_skill_keys END) @> p_skills
 ELSE (CASE WHEN p_skill_scope='all' THEN j.required_skill_keys || j.preferred_skill_keys ELSE j.required_skill_keys END) && p_skills END)
$$;
CREATE OR REPLACE FUNCTION serving.search_jobs_v3(p_query text DEFAULT '', p_sources text[] DEFAULT '{}', p_cities text[] DEFAULT '{}', p_experience text DEFAULT '', p_seniority text[] DEFAULT '{}', p_modes text[] DEFAULT '{}', p_days integer DEFAULT 0, p_skills text[] DEFAULT '{}', p_skill_match text DEFAULT 'any', p_skill_scope text DEFAULT 'required', p_sort text DEFAULT 'relevance', p_limit integer DEFAULT 20, p_offset integer DEFAULT 0)
RETURNS TABLE (
 id bigint,title text,employer_name_raw text,canonical_url text,
 source_code text,source_name text,location_cities text[],salary_raw text,
 employment_type_raw text,experience_raw text,posted_at timestamptz,last_seen_at timestamptz,
 first_seen_at timestamptz,experience_min_years double precision,experience_max_years double precision,
 seniority_levels text[],work_mode text,employment_type text,enrichment_status text,required_skill_keys text[],preferred_skill_keys text[],score real
)
LANGUAGE plpgsql STABLE SECURITY INVOKER SET search_path='' AS $$ DECLARE query_ tsquery; BEGIN
 PERFORM serving.validate_skill_filters(p_query,p_sources,p_cities,p_experience,p_seniority,p_modes,p_days,p_skills,p_skill_match,p_skill_scope);
 IF p_sort IS NULL OR p_sort NOT IN ('relevance','newest') OR p_limit IS NULL OR p_limit NOT BETWEEN 1 AND 100 OR p_offset IS NULL OR p_offset NOT BETWEEN 0 AND 10000 THEN
 RAISE EXCEPTION 'Invalid search pagination' USING ERRCODE='22023'; END IF;
 query_ := serving.skills_search_query(p_query);
 RETURN QUERY SELECT j.id,j.title,j.employer_name_raw,j.canonical_url,s.code,s.display_name,j.location_cities,
 j.salary_raw,j.employment_type_raw,j.experience_raw,j.posted_at,j.last_seen_at,j.first_seen_at,
 j.experience_min_years,j.experience_max_years,j.seniority_levels,j.work_mode,j.employment_type,j.enrichment_status,
 j.required_skill_keys,j.preferred_skill_keys,
 coalesce(ts_rank(j.search_vector,query_),0::real) score
 FROM serving.matching_skill_ids(p_query,p_sources,p_cities,p_experience,p_seniority,p_modes,p_days,p_skills,p_skill_match,p_skill_scope) matches JOIN serving.jobs j ON j.id=matches.id JOIN serving.sources s ON s.id=j.source_id
 ORDER BY CASE WHEN p_sort='relevance' THEN coalesce(ts_rank(j.search_vector,query_),0::real) END DESC,
 coalesce(j.posted_at,j.first_seen_at) DESC NULLS LAST,j.id DESC LIMIT p_limit OFFSET p_offset;
END $$;
CREATE OR REPLACE FUNCTION serving.job_statistics_v1(p_query text DEFAULT '', p_sources text[] DEFAULT '{}', p_cities text[] DEFAULT '{}', p_experience text DEFAULT '', p_seniority text[] DEFAULT '{}', p_modes text[] DEFAULT '{}', p_days integer DEFAULT 0, p_skills text[] DEFAULT '{}', p_skill_match text DEFAULT 'any', p_skill_scope text DEFAULT 'required') RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY INVOKER SET search_path='' AS $$
DECLARE result jsonb; BEGIN
 PERFORM serving.validate_skill_filters(p_query,p_sources,p_cities,p_experience,p_seniority,p_modes,p_days,p_skills,p_skill_match,p_skill_scope);
 WITH base AS MATERIALIZED (
 SELECT j.id,source_id,location_cities,enrichment_status,skills_required,skills_preferred,required_skill_keys,preferred_skill_keys,
 CASE WHEN enrichment_status='succeeded' AND experience_min_years BETWEEN 0 AND 60 AND (experience_max_years IS NULL OR experience_max_years BETWEEN experience_min_years AND 60) THEN experience_min_years END exp,
 CASE WHEN enrichment_status='succeeded' THEN ARRAY(SELECT DISTINCT x FROM unnest(seniority_levels) x WHERE x IN ('intern','fresher','junior','middle','senior','lead','manager','director')) ELSE '{}'::text[] END levels,
 CASE WHEN enrichment_status='succeeded' AND work_mode IN ('onsite','hybrid','remote') THEN work_mode END mode
 FROM serving.matching_skill_ids(p_query,p_sources,p_cities,p_experience,p_seniority,p_modes,p_days,p_skills,p_skill_match,p_skill_scope) matches JOIN serving.jobs j ON j.id=matches.id
 ), facts AS (
 SELECT 'source'::text kind,s.code key,s.display_name label,b.id FROM base b JOIN serving.sources s ON s.id=b.source_id
 UNION ALL SELECT 'city',c,c,b.id FROM base b LEFT JOIN LATERAL (SELECT DISTINCT x c FROM unnest(b.location_cities) x WHERE nullif(btrim(x),'') IS NOT NULL) loc ON true
 UNION ALL SELECT 'skill',c.key,c.label,b.id FROM base b CROSS JOIN LATERAL unnest(CASE WHEN p_skill_scope='all' THEN required_skill_keys || preferred_skill_keys ELSE required_skill_keys END) k JOIN serving.skill_catalogue() c ON c.key=k
 UNION ALL SELECT 'seniority',coalesce(l,'unknown'),coalesce(l,'unknown'),b.id FROM base b LEFT JOIN LATERAL unnest(levels) l ON true
 UNION ALL SELECT 'mode',coalesce(mode,'unknown'),coalesce(mode,'unknown'),id FROM base
 UNION ALL SELECT 'experience',bucket,bucket,id FROM (SELECT id,CASE WHEN exp IS NULL THEN 'unknown' WHEN exp=0 THEN 'zero' WHEN exp<1 THEN 'under1' WHEN exp<3 THEN '1to3' WHEN exp<5 THEN '3to5' ELSE '5plus' END bucket FROM base) e
 ), counts AS (SELECT kind,key,label,count(DISTINCT id)::int count FROM facts GROUP BY kind,key,label), ranked AS (
 SELECT *,row_number() OVER(PARTITION BY kind ORDER BY count DESC,label NULLS LAST) pos FROM counts
 ) SELECT jsonb_build_object('total',(SELECT count(*) FROM base),'calculatedAt',CURRENT_TIMESTAMP,
 'rows',coalesce((SELECT jsonb_agg(jsonb_build_object('kind',kind,'key',key,'label',label,'count',count) ORDER BY kind,pos) FROM ranked WHERE kind<>'skill' OR pos<=15),'[]'::jsonb),
 'coverage',(SELECT jsonb_build_object('enriched',count(*) FILTER(WHERE enrichment_status='succeeded'),
 'extracted',count(*) FILTER(WHERE enrichment_status='succeeded' AND (cardinality(skills_required)>0 OR (p_skill_scope='all' AND cardinality(skills_preferred)>0))),
 'normalized',count(*) FILTER(WHERE cardinality(required_skill_keys)>0 OR (p_skill_scope='all' AND cardinality(preferred_skill_keys)>0)),
 'experience',count(exp),'seniority',count(*) FILTER(WHERE cardinality(levels)>0),'mode',count(mode)) FROM base)) INTO result;
 RETURN result;
END $$;
REVOKE ALL ON FUNCTION serving.skill_key(text) FROM PUBLIC;
REVOKE ALL ON FUNCTION serving.normalize_skills(text[]) FROM PUBLIC;
REVOKE ALL ON FUNCTION serving.preferred_skills(text[],text[]) FROM PUBLIC;
REVOKE ALL ON FUNCTION serving.skill_catalogue() FROM PUBLIC;
REVOKE ALL ON FUNCTION serving.skills_search_query(text) FROM PUBLIC;
REVOKE ALL ON FUNCTION serving.validate_skill_filters(text,text[],text[],text,text[],text[],integer,text[],text,text) FROM PUBLIC;
REVOKE ALL ON FUNCTION serving.matching_skill_ids(text,text[],text[],text,text[],text[],integer,text[],text,text) FROM PUBLIC;
REVOKE ALL ON FUNCTION serving.search_jobs_v3(text,text[],text[],text,text[],text[],integer,text[],text,text,text,integer,integer) FROM PUBLIC;
REVOKE ALL ON FUNCTION serving.job_statistics_v1(text,text[],text[],text,text[],text[],integer,text[],text,text) FROM PUBLIC;
DO $$ BEGIN IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='joblake_web_reader') THEN
GRANT EXECUTE ON FUNCTION serving.skill_key(text) TO joblake_web_reader;
GRANT EXECUTE ON FUNCTION serving.normalize_skills(text[]) TO joblake_web_reader;
GRANT EXECUTE ON FUNCTION serving.preferred_skills(text[],text[]) TO joblake_web_reader;
GRANT EXECUTE ON FUNCTION serving.skill_catalogue() TO joblake_web_reader;
GRANT EXECUTE ON FUNCTION serving.skills_search_query(text) TO joblake_web_reader;
GRANT EXECUTE ON FUNCTION serving.validate_skill_filters(text,text[],text[],text,text[],text[],integer,text[],text,text) TO joblake_web_reader;
GRANT EXECUTE ON FUNCTION serving.matching_skill_ids(text,text[],text[],text,text[],text[],integer,text[],text,text) TO joblake_web_reader;
GRANT EXECUTE ON FUNCTION serving.search_jobs_v3(text,text[],text[],text,text[],text[],integer,text[],text,text,text,integer,integer) TO joblake_web_reader;
GRANT EXECUTE ON FUNCTION serving.job_statistics_v1(text,text[],text[],text,text[],text[],integer,text[],text,text) TO joblake_web_reader;
END IF; END $$;
