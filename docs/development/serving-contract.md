# Website serving contract

This is the current contract implemented in this repository, reviewed against
packaged SQL on 2026-10-01. It does not assert that a particular frontend build or
remote database has been deployed. Historical rollout evidence is in the
[prefix report](../archive/search-prefix-2026-09-22.md) and
[enrichment/v2 handoff](../archive/web-enrichment-2026-09-27.md).

## Data boundary

The website reads `serving.sources` and `serving.jobs`, one row per active local
posting. `id` is the local posting ID. Detail text and raw display fields remain
available; raw HTML, attempt history and AI evidence/provider metadata stay local.
Use [sync operations](../operations/supabase-cli.md) for publication behavior and
[enrichment](../operations/enrichment.md) for the full nullable-column contract.

`first_seen_at` is the posting's first local observation; `posted_at` is the date
extracted from the source and can be null. V2 uses `coalesce(posted_at,first_seen_at)`
for date filtering and ordering. Label the fallback as “Ghi nhận lần đầu”, not
“Ngày đăng”. `last_seen_at` is observation freshness; `updated_at` is the last
serving-row change. None is interchangeable with an employer's closing date.

## Search functions

The legacy function is named **`serving.search_jobs`**, not `search_jobs_v1`:

```sql
serving.search_jobs(
  p_query text = '', p_source_code text = NULL, p_city text = NULL,
  p_limit integer = 20, p_offset integer = 0
)
```

It returns `id`, `title`, `employer_name_raw`, `canonical_url`, `source_code`,
`source_name`, `location_cities`, `salary_raw`, `employment_type_raw`,
`experience_raw`, `posted_at`, `last_seen_at`, `score`. Source/city filters are
single exact values. It remains available for existing consumers.

V2 is additive:

```sql
serving.search_jobs_v2(
  p_query text = '', p_sources text[] = '{}', p_cities text[] = '{}',
  p_experience text = '', p_seniority text[] = '{}', p_modes text[] = '{}',
  p_days integer = 0, p_sort text = 'relevance',
  p_limit integer = 20, p_offset integer = 0
)
```

V2 returns the v1 listing fields plus `first_seen_at`, `experience_min_years`,
`experience_max_years`, `seniority_levels`, `work_mode`, `employment_type` and
`enrichment_status`. It does **not** return `skills_required`, `skills_preferred`,
`enriched_at` or full detail text; select those from the detail row if needed.
Neither RPC returns a total count. A consumer can request 21/display 20 to detect
another page. Do not filter only an already-loaded page or invent a total count.

## V2 filter semantics

| Parameter | Accepted values and behavior |
| --- | --- |
| `p_sources` | Up to 20 source codes; any match within the array |
| `p_cities` | Up to 20 exact normalized city labels; any overlap with `location_cities` |
| `p_experience` | Empty = all; `zero` = 0; `under1` = (0,1); `1to3` = [1,3); `3to5` = [3,5); `5plus` = ≥5; `unknown` = unavailable/invalid |
| `p_seniority` | Up to 9: intern, fresher, junior, middle, senior, lead, manager, director, unknown |
| `p_modes` | Up to 4: onsite, hybrid, remote, unknown |
| `p_days` | 0 = unrestricted, or 1/7/30 rolling days through current DB time; future dates excluded for a nonzero window |
| `p_sort` | `relevance` or `newest` |

Empty arrays disable that filter. Values within a filter are ORed; separate
filters are ANDed before pagination. `unknown` can be combined with known
seniority/work modes. Experience buckets use the **minimum** required years,
not overlap with the advertised min/max range.

Only `succeeded` enrichment with valid values contributes to the AI-derived
filters. Experience must have a minimum in 0–60 and a compatible upper bound;
missing or invalid bounds map to unknown. Invalid/empty seniority and invalid/null
work modes likewise map to unknown. Raw experience strings are not parsed at query
time. The returned columns remain stored values; consumers must honor status/nulls.

Both functions limit `p_limit` to 1–100, offset to 0–10000 and query to 200
characters. V2 rejects null arrays/options, invalid enums and malformed entries
with SQLSTATE `22023`. Source codes match `[a-z0-9_-]{1,50}`; city labels are
1–120 characters without control characters.

## Shared text matching

- PostgreSQL `simple`/unaccent normalization supports accented/unaccented Vietnamese.
  Technology aliases include C++ → cplusplus, C# → csharp, .NET → dotnet and
  Node.js → nodejs.
- Ordinary queries prefix-match the last normalized lexeme when it has at least
  three characters. Earlier words remain exact: `data eng` matches `data engineer`;
  `data en` does not expand the short final token.
- Trailing whitespace does not change matching. Quotes, OR and exclusion syntax
  preserve web-search semantics without automatic prefix expansion. Internal
  hyphens belong to a term; a final compound such as `full-sta` matches its parts.
- Empty/whitespace queries disable keyword filtering; punctuation-only queries
  with no lexemes return no results. There is no typo correction or infix search.
- Title/raw skills have weight A; employer/categories weight B. Description text
  and AI-extracted skill arrays are not included in the search vector.
- Relevance is `ts_rank` using the same query that filters rows. V1 ties use
  `posted_at DESC NULLS LAST, id DESC`; v2 uses effective date then ID. V2 `newest`
  omits relevance from ordering. There is no separate exact-match bonus.

## Installation and access

New empty `supabase-setup` creates base tables, enrichment columns, v1, prefix
matching and v2 in one transaction. Existing deployments need the relevant
reviewed additive SQL, not a fresh bootstrap:

- `20260922011629_serving_search_prefix.sql`
- `20260925113037_serving_enrichment.sql`
- `20260927020719_serving_search_v2.sql`

These files under `supabase/migrations/` are not a complete empty-database
bootstrap. V2 depends on enrichment columns; existing rows may need an explicit
`first_seen_at` backfill or a normal sync. Direct setup commands do not maintain
Supabase CLI migration history automatically. Check actual schema/history before
applying changes. V1 prefix rollback SQL is not a rollback for v2.

Both RPCs use `SECURITY INVOKER`. Table RLS/grants and schema usage must permit
the application reader. V2 revokes PUBLIC execution and grants it to an existing
`joblake_web_reader` role; it does not create that role, its login or row policies.
Bootstrap does not make tables public to `anon`/`authenticated`. Keep database
credentials in the server environment. Verify deployed privileges independently.

## Frontend handling and verification

Null enrichment means unknown, never zero years, onsite or no skills. A successful
result can still have null fields. Preserve raw display fallbacks, render zero
experience explicitly, support min-only/max-only ranges, and keep provider/quota
details out of the job browsing flow. The frontend does not call model APIs.

Run the disposable SQL tests described in [testing](testing.md), including
`test_search_v2.py`, `test_supabase_serving.py` and `test_enrichment_sql.py`.
Then test the actual frontend separately: prefix/aliases, source/city filters,
unknown combinations, dates, pagination, old unenriched jobs and detail pages.
Frontend cache/deployment behavior is owned by its separate repository; database
smoke tests do not establish current UI behavior.

## Skills/insights serving v3 (2026-10-02)

Additive migrations20261002132327_skills_insights,20261002133754_skills_query_optimization,20261002134007_skills_search_direct_plan đã áp dụng; tên file local khớp version history Supabase. search_jobs_v1/v2 giữ nguyên để rollback.

serving.jobs thêm required_skill_keys/preferred_skill_keys generated STORED, hai GIN indexes. Chỉ ánh xạ skills_required/preferred khi succeeded; required thắng preferred. Registry version2026-10-02.1 tại joblake.skills/catalogue.json; local view core.current_job_skills dùng cùng mapping. Không cần đổi input sync, không dùng AI mới để tạo projection.

search_jobs_v3 bổ sung p_skills(max10),p_skill_match(any/all),p_skill_scope(required/all) trước sort/limit/offset; summary thêm hai key arrays, giữ nguyên FTS/ranking/date filters. job_statistics_v1 nhận cùng filter, trả tổng/rows/coverage/calculatedAt. Predicate được sinh từ một nguồn qua scripts/generate_skills_sql.py; count DISTINCT mỗi posting/bucket, không gộp trùng khác nguồn.

Không mở anon/authenticated/PUBLIC execute. Reader vẫn chỉ đọc. Web catalogue static phải đồng bộ registry; thay mapping IMMUTABLE phải migration tính lại generated STORED cho hàng cũ. Quy trình audit, kết quả test/benchmark, giới hạn coverage, firewall và rollback: [runbook](../operations/skills-insights.md).
