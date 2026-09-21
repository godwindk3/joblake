# Supabase: compact active jobs

Local PostgreSQL is authoritative. Supabase stores only `serving.sources` and
`serving.jobs`, one row per active posting. Raw HTML, parse history and crawl
state stay local. `core`/`ref` full replication is legacy and must not be used
on this deployment.

## Run manually in Airflow

Open `joblake_supabase_sync`, unpause it, then Trigger. There is **no schedule**
(`schedule=None`, `catchup=False`). Unpausing alone does not schedule a sync.

- `dry_run=false` (default): apply inserts, changed rows and removals atomically.
- `dry_run=true`: validate and display counts; never write serving rows.
- Tasks: `check_connection -> sync_active_jobs`.
- Sync verifies every staged publishable row and absence of inactive rows before
  committing. Failed verification rolls back the entire transaction.
- Sync reserves all three slots of `joblake_serial`; only one sync run is active.
- This DAG does not crawl. Trigger source DAGs first if fresh listing state is needed.

## Stored fields

`serving.sources`: `id`, `code`, `display_name`.

`serving.jobs`:

| Purpose | Columns |
| --- | --- |
| Identity and source link | `id`, `source_id`, `canonical_url` |
| Listing | `title`, `employer_name_raw` |
| Detail | `description_text`, `requirements_text`, `benefits_text` |
| Filters | `categories_raw`, `skills_raw`, `location_cities` |
| Conditions | `salary_raw`, `employment_type_raw`, `experience_raw` |
| Dates | `posted_at`, `expires_at`, `last_seen_at`, `updated_at` |

ID is the local `core.source_job_postings.id`, not a parse-result ID.
Only one benefit representation is stored: nonblank benefits text, falling back
to joined `benefit_items`. Full detail text is retained without truncation.
No raw payload, parser metadata, duplicate benefit array, detailed raw locations,
historical versions or crawler events are copied. Sources use numeric foreign keys.
Jobs have the primary key, source index, posted-date/id ordering index, and
GIN indexes for search_vector and location_cities. Search v1 covers title/skills
(weight A) and employer/categories (weight B), with simple/unaccent normalization.
A database trigger maintains search_vector; it is not exported from local.
Staging copies only the export columns and a primary key, not the GIN indexes.
Unchanged rows are not rewritten.
`updated_at` records an actual serving-row change; `last_seen_at` comes from crawl
state. Salary/experience remain display strings, not numeric range filters.

## State and failure behavior

Active means present in the last qualifying listing scope, not independently
verified employer availability. `expires_at` is displayed but is not an extra
expiry rule. Only complete successful discovery updates CDC state; skipped or
blocked discovery does not infer expiry. Sync exports the last committed state
even after a failed scan, so previously missed removals can catch up.

- `active` plus a current accepted/partial parse and nonblank title: publish.
- `expired` or `unknown`: remove from serving, retaining local history.
- Active without a usable current parse: retain any previously published content
  and refresh last-seen time; a never-published job waits for valid content.
- Reappeared jobs are reinserted when active with usable current content.
- Scope changes can reset previous jobs to unknown, removing them on the next sync.
- A posting missing its crawl-state mapping, inconsistent source identity, or
  active state without a valid CDC baseline aborts the whole sync before changes.
- An empty local source catalog is rejected. A valid catalog with no active jobs
  legitimately removes all serving jobs. Remote jobs missing from the complete
  local posting snapshot are removed too. Do not point sync at a partial database.

All sources are processed; `--config` only affects ingestion. No timestamp
checkpoint is required. A repeatable-read local snapshot is streamed with COPY
into temporary remote tables. A remote advisory lock is acquired before the
local snapshot, preventing older concurrent exports from committing last.
Temporary tables disappear on commit/rollback. Dry-run/verify still acquire
locks and write temporary staging data, but do not modify serving rows.

## CLI and configuration

```powershell
python -m joblake.main --phase supabase-test
python -m joblake.main --phase supabase-sync --dry-run
python -m joblake.main --phase supabase-sync
python -m joblake.main --phase supabase-verify
```

For a **new empty deployment only**, use `--phase supabase-setup`. It refuses an
existing `serving` schema and never deletes data. Legacy `supabase-migrate`
refuses a serving deployment. `scripts/verify_supabase_migration.py` now verifies
serving; the old `joblake.supabase_verify` module is retained for historical audits.

The root `.env` supplies `SUPABASE_DATABASE_URL` (direct/session-pooler PostgreSQL,
TLS required) and local PostgreSQL settings. Existing environment values win.
`LOCAL_DATABASE_URL` otherwise takes precedence over individual `POSTGRES_*`
fields. Inside Docker only, its loopback hostname is replaced by a configured
non-loopback `POSTGRES_HOST` (normally `host.docker.internal`); port, database and
credentials are preserved. Explicit non-loopback URLs are not rewritten.

RLS is enabled on both tables, with no public grants/policies. SQL Editor and
the database sync account can access them. Search v1 grants service_role read
access and EXECUTE on serving.search_jobs for server-side integration only;
anon/authenticated remain unprivileged. Data API schema exposure must be checked
separately. No client write permissions are granted. Security Advisor's informational
`rls_enabled_no_policy` is expected for these currently private tables.

See [web search handoff](../handoff/JOBLAKE_WEB_FTS_CONTEXT.md) for the RPC contract,
normalization rules, index measurements and integration requirements. The remote
migration is stored at `src/joblake/sql/serving_search_v1.sql` and has already been
applied to the current Supabase project; do not rerun it there. New empty setup
applies it automatically after creating the base serving schema.

## Verification

```powershell
$env:JOBLAKE_TEST_SERVING = '1'
python -m unittest discover -s tests -p 'test_supabase*.py' -v
docker compose -f orchestration/airflow/compose.yaml exec -T airflow-scheduler python /opt/airflow/check_dag.py
```

SQL integration tests create and drop a uniquely named local test database;
they never use Supabase for test writes. The live Airflow dry-run validates the
real credentials and source mapping without publishing rows.
