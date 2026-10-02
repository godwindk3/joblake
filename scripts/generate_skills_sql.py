"""Generate deterministic local and serving SQL from the reviewed skill registry."""
import json
from pathlib import Path
root = Path(__file__).resolve().parents[1]
rows = json.loads((root/'src/joblake/skills/catalogue.json').read_text(encoding='utf8'))
q=lambda s:"'"+s.replace("'","''")+"'"
aliases={}
for row in rows:
 for a in [row['label'],*row['aliases']]:
  k=' '.join(a.lower().split())
  assert k not in aliases or aliases[k]==row['key'],k
  aliases[k]=row['key']
base="""-- Generated from joblake.skills/catalogue.json. Version 2026-10-02.1.
CREATE OR REPLACE FUNCTION serving.skill_key(value text) RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE SET search_path='' AS $$
 SELECT CASE lower(regexp_replace(btrim(normalize(value,NFC)), '[[:space:]]+', ' ', 'g'))
"""+'\n'.join(' WHEN '+q(a)+' THEN '+q(k) for a,k in sorted(aliases.items()))+"\n END\n$$;\n"
base+='''CREATE OR REPLACE FUNCTION serving.normalize_skills(values_ text[]) RETURNS text[]
LANGUAGE sql IMMUTABLE PARALLEL SAFE SET search_path='' AS $$
 SELECT coalesce(array_agg(DISTINCT key ORDER BY key), '{}'::text[])
 FROM (SELECT serving.skill_key(v) key FROM unnest(values_) v) s WHERE key IS NOT NULL
$$;
CREATE OR REPLACE FUNCTION serving.preferred_skills(required_ text[], preferred_ text[]) RETURNS text[]
LANGUAGE sql IMMUTABLE PARALLEL SAFE SET search_path='' AS $$
 SELECT ARRAY(SELECT k FROM unnest(serving.normalize_skills(preferred_)) k
 WHERE NOT k=ANY(serving.normalize_skills(required_)) ORDER BY k)
$$;
'''
sql="SET LOCAL lock_timeout='10s';\nSET LOCAL statement_timeout='120s';\nSELECT pg_advisory_xact_lock(741205,1);\n"+base
sql+='''CREATE OR REPLACE FUNCTION serving.skill_catalogue() RETURNS TABLE(key text,label text,aliases text[])
LANGUAGE sql IMMUTABLE PARALLEL SAFE SET search_path='' AS $$ VALUES
'''+',\n'.join('('+q(r['key'])+','+q(r['label'])+',ARRAY['+','.join(q(a) for a in r['aliases'])+']::text[])' for r in rows)+'\n$$;\n'
sql+='''ALTER TABLE serving.jobs
 ADD COLUMN IF NOT EXISTS required_skill_keys text[] GENERATED ALWAYS AS
 (CASE WHEN enrichment_status='succeeded' THEN serving.normalize_skills(skills_required) ELSE '{}'::text[] END) STORED,
 ADD COLUMN IF NOT EXISTS preferred_skill_keys text[] GENERATED ALWAYS AS
 (CASE WHEN enrichment_status='succeeded' THEN serving.preferred_skills(skills_required,skills_preferred) ELSE '{}'::text[] END) STORED;
CREATE INDEX IF NOT EXISTS jobs_required_skills_idx ON serving.jobs USING gin(required_skill_keys);
CREATE INDEX IF NOT EXISTS jobs_all_skills_idx ON serving.jobs USING gin((required_skill_keys || preferred_skill_keys));
'''
v2=(root/'src/joblake/sql/serving_search_v2.sql').read_text(encoding='utf8')
declare=v2[v2.index('DECLARE'):v2.index('\nBEGIN')]
query=v2[v2.index(" IF btrim(COALESCE(p_query"):v2.index('\n RETURN QUERY')].replace('THEN RETURN;','THEN RETURN q;')
sql+='CREATE OR REPLACE FUNCTION serving.skills_search_query(p_query text) RETURNS tsquery LANGUAGE plpgsql STABLE SET search_path=\'\' AS $$\n'+declare+'\nBEGIN\n'+query+'\n RETURN q;\nEND $$;\n'
params="p_query text DEFAULT '', p_sources text[] DEFAULT '{}', p_cities text[] DEFAULT '{}', p_experience text DEFAULT '', p_seniority text[] DEFAULT '{}', p_modes text[] DEFAULT '{}', p_days integer DEFAULT 0, p_skills text[] DEFAULT '{}', p_skill_match text DEFAULT 'any', p_skill_scope text DEFAULT 'required'"
args='p_query,p_sources,p_cities,p_experience,p_seniority,p_modes,p_days,p_skills,p_skill_match,p_skill_scope'
validation=v2[v2.index(' IF p_limit'):v2.index(" IF btrim(COALESCE(p_query")]
validation=validation.replace("p_limit IS NULL OR p_limit NOT BETWEEN 1 AND 100 OR p_offset IS NULL OR p_offset NOT BETWEEN 0 AND 10000\n OR ",'').replace(" OR p_sort IS NULL OR p_sort NOT IN ('relevance','newest')\n",'\n')
validation=validation.replace(" THEN RAISE", " OR p_skills IS NULL OR cardinality(p_skills)>10 OR p_skill_match IS NULL OR p_skill_match NOT IN ('any','all')\n OR p_skill_scope IS NULL OR p_skill_scope NOT IN ('required','all')\n OR EXISTS(SELECT 1 FROM unnest(p_skills) k WHERE k IS NULL OR NOT EXISTS(SELECT 1 FROM serving.skill_catalogue() c WHERE c.key=k))\n THEN RAISE")
sql+='CREATE OR REPLACE FUNCTION serving.validate_skill_filters('+params+") RETURNS void LANGUAGE plpgsql STABLE SET search_path='' AS $$ BEGIN\n"+validation+' END $$;\n'
where=v2[v2.rindex(' CROSS JOIN LATERAL'):v2.index('\n ORDER BY CASE')]
where=where.replace(' WHERE (q IS NULL OR j.search_vector @@ q)', ' WHERE (sq.q IS NULL OR j.search_vector @@ sq.q)')
skill_where='''
 AND (cardinality(p_skills)=0 OR CASE WHEN p_skill_match='all'
 THEN (CASE WHEN p_skill_scope='all' THEN j.required_skill_keys || j.preferred_skill_keys ELSE j.required_skill_keys END) @> p_skills
 ELSE (CASE WHEN p_skill_scope='all' THEN j.required_skill_keys || j.preferred_skill_keys ELSE j.required_skill_keys END) && p_skills END)
'''
sql+='CREATE OR REPLACE FUNCTION serving.matching_skill_ids('+params+") RETURNS TABLE(id bigint) LANGUAGE sql STABLE SECURITY INVOKER SET search_path='' AS $$\n WITH search AS MATERIALIZED (SELECT serving.skills_search_query(p_query) q) SELECT j.id FROM serving.jobs j JOIN serving.sources s ON s.id=j.source_id\n CROSS JOIN search sq\n"+where+skill_where+'$$;\n'
ret=v2[v2.index('RETURNS TABLE ('):v2.index('\nLANGUAGE plpgsql')].replace('enrichment_status text,score real','enrichment_status text,required_skill_keys text[],preferred_skill_keys text[],score real')
sql+='CREATE OR REPLACE FUNCTION serving.search_jobs_v3('+params+", p_sort text DEFAULT 'relevance', p_limit integer DEFAULT 20, p_offset integer DEFAULT 0)\n"+ret+"\nLANGUAGE plpgsql STABLE SECURITY INVOKER SET search_path='' AS $$ DECLARE query_ tsquery; BEGIN\n PERFORM serving.validate_skill_filters("+args+''');
 IF p_sort IS NULL OR p_sort NOT IN ('relevance','newest') OR p_limit IS NULL OR p_limit NOT BETWEEN 1 AND 100 OR p_offset IS NULL OR p_offset NOT BETWEEN 0 AND 10000 THEN
 RAISE EXCEPTION 'Invalid search pagination' USING ERRCODE='22023'; END IF;
 query_ := serving.skills_search_query(p_query);\n RETURN QUERY SELECT j.id,j.title,j.employer_name_raw,j.canonical_url,s.code,s.display_name,j.location_cities,
 j.salary_raw,j.employment_type_raw,j.experience_raw,j.posted_at,j.last_seen_at,j.first_seen_at,
 j.experience_min_years,j.experience_max_years,j.seniority_levels,j.work_mode,j.employment_type,j.enrichment_status,
 j.required_skill_keys,j.preferred_skill_keys,
 coalesce(ts_rank(j.search_vector,query_),0::real) score
 FROM serving.jobs j JOIN serving.sources s ON s.id=j.source_id
 '''+where.replace('sq.q','query_')+skill_where+'''
 ORDER BY CASE WHEN p_sort='relevance' THEN coalesce(ts_rank(j.search_vector,query_),0::real) END DESC,
 coalesce(j.posted_at,j.first_seen_at) DESC NULLS LAST,j.id DESC LIMIT p_limit OFFSET p_offset;
END $$;
'''
sql+='CREATE OR REPLACE FUNCTION serving.job_statistics_v1('+params+") RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY INVOKER SET search_path='' AS $$\nDECLARE result jsonb; BEGIN\n PERFORM serving.validate_skill_filters("+args+''');
 WITH base AS MATERIALIZED (
 SELECT j.id,source_id,location_cities,enrichment_status,skills_required,skills_preferred,required_skill_keys,preferred_skill_keys,
 CASE WHEN enrichment_status='succeeded' AND experience_min_years BETWEEN 0 AND 60 AND (experience_max_years IS NULL OR experience_max_years BETWEEN experience_min_years AND 60) THEN experience_min_years END exp,
 CASE WHEN enrichment_status='succeeded' THEN ARRAY(SELECT DISTINCT x FROM unnest(seniority_levels) x WHERE x IN ('intern','fresher','junior','middle','senior','lead','manager','director')) ELSE '{}'::text[] END levels,
 CASE WHEN enrichment_status='succeeded' AND work_mode IN ('onsite','hybrid','remote') THEN work_mode END mode
 FROM serving.matching_skill_ids('''+args+''') matches JOIN serving.jobs j ON j.id=matches.id
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
'''
types='text,text[],text[],text,text[],text[],integer,text[],text,text'
functions=[('skill_key','text'),('normalize_skills','text[]'),('preferred_skills','text[],text[]'),('skill_catalogue',''),('skills_search_query','text'),('validate_skill_filters',types),('matching_skill_ids',types),('search_jobs_v3',types+',text,integer,integer'),('job_statistics_v1',types)]
for name,typ in functions:
 sql+=f'REVOKE ALL ON FUNCTION serving.{name}({typ}) FROM PUBLIC;\n'
sql+="DO $$ BEGIN IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='joblake_web_reader') THEN\n"
for name,typ in functions: sql+=f'GRANT EXECUTE ON FUNCTION serving.{name}({typ}) TO joblake_web_reader;\n'
sql+='END IF; END $$;\n'
(root/'src/joblake/sql/serving_skills.sql').write_text(sql,encoding='utf8')
local=base.replace('serving.','core.')+'''CREATE OR REPLACE VIEW core.current_job_skills WITH (security_invoker=true) AS
SELECT e.parse_result_id,
 CASE WHEN e.status='succeeded' THEN core.normalize_skills(ARRAY(SELECT jsonb_array_elements_text(e.result->'skills_required'))) ELSE '{}'::text[] END required_skill_keys,
 CASE WHEN e.status='succeeded' THEN core.preferred_skills(ARRAY(SELECT jsonb_array_elements_text(e.result->'skills_required')),ARRAY(SELECT jsonb_array_elements_text(e.result->'skills_preferred'))) ELSE '{}'::text[] END preferred_skill_keys,
 '2026-10-02.1'::text normalization_version
FROM core.current_job_enrichments e;
'''
# Nullable JSON fields are explicit JSON null; array extraction must accept them.
local=local.replace("jsonb_array_elements_text(e.result->'skills_required')","jsonb_array_elements_text(CASE WHEN jsonb_typeof(e.result->'skills_required')='array' THEN e.result->'skills_required' ELSE '[]'::jsonb END)").replace("jsonb_array_elements_text(e.result->'skills_preferred')","jsonb_array_elements_text(CASE WHEN jsonb_typeof(e.result->'skills_preferred')='array' THEN e.result->'skills_preferred' ELSE '[]'::jsonb END)")
(root/'src/joblake/sql/skills_local.sql').write_text(local,encoding='utf8')
print('Generated',len(rows),'skills,',len(aliases),'aliases')




