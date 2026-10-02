# Optional AI enrichment

Enrichment is an independent phase and Airflow DAG. Neither ingestion nor
`supabase-sync` invokes it or depends on its success. The normal `enrich` phase processes only current,
active, accepted/partial parser results fetched at or after **2026-09-26 00:00
Asia/Ho_Chi_Minh** (2026-09-25 17:00 UTC). Re-parsing older HTML is not eligible.
Unchanged pre-cutoff content is excluded by comparison with local parse history.
Explicit historical processing is available through the separate
[`joblake_enrichment_backfill` DAG / `enrich-backfill` phase](enrichment-backfill.md).
It has its own date/source/ID filters and defaults to a read-only dry run.
Both workers share results, retry history, quota accounting and the session lock.

## Run in Airflow

Open `joblake_enrichment`, enable it if paused, and choose **Trigger DAG**.

- `dry_run=true` (default): report eligible count and queue status; no API calls
  and no database writes.
- `dry_run=false`: enqueue and process eligible records.
- `max_jobs=100` (default): maximum API attempts for this run, including failures.

Open the run, select `enrich_jobs`, then **Logs**. Logs show posting/enrichment IDs,
provider/model, attempt number, tokens, duration, error codes and final queue totals.
Keys, complete prompts and raw provider error responses are not logged. The CLI
runs with `-u`, so log output is not buffered. Times in logs are UTC.

The DAG is manual (`schedule=None`), with one active run and no automatic Airflow
retries. The persistent queue owns retries. It runs for at most 20 minutes plus
the final request (Airflow timeout: 25 minutes). A pending daily quota causes an
early exit. Trigger the DAG again later to resume. There is no automatic wakeup.
The independent `joblake_supabase_sync` DAG is unchanged.

## CLI

```powershell
.venv/Scripts/python.exe -m joblake.main --phase enrich --dry-run
.venv/Scripts/python.exe -m joblake.main --phase enrich --max-jobs 20
.venv/Scripts/python.exe -m joblake.main --phase supabase-sync --dry-run
```

`--enrichment-config` defaults to `configs/enrichment.yaml`; ingestion `--config`
is not used by enrichment. Keys live only in the root `.env`:
`GEMINI_API_KEY`, `GROQ_API_KEY`, `OPENROUTER_API_KEY`. Airflow already mounts this
file and loads it when each task starts; no container rebuild is needed.

## Provider policy

1. Gemini `gemini-3.1-flash-lite`, JSON Schema, minimal thinking.
2. Groq `openai/gpt-oss-120b`, strict JSON Schema, low reasoning.
3. OpenRouter is configured but **disabled** (`enabled: false`). Its configured
   model is `nvidia/nemotron-3-super-120b-a12b:free`, JSON Schema, reasoning off,
   completion cap 4096 tokens. The worker skips it until explicitly enabled.
   Pricing filters request zero-priced routing; no paid fallback is configured.

These are repository settings, not a guarantee of current provider availability
or account limits. Use the explicit synthetic provider check when validating a
deployment; it consumes API requests.

Only one successful model result is required per job content version. No model
judges another. Quota/cooldown determines dispatch; invalid results are queued
for later retry, not immediately escalated to a larger model. Default maximum:
three API attempts per content version, 15 minutes between attempts.

Gemini supports grouping up to three jobs per API request. The default remains
`batch_size: 1` until a paired live benchmark is reviewed; set Gemini's
`batch_size: 3` in `configs/enrichment.yaml` to opt in. Groq/OpenRouter remain
single-job requests. See [batching and its verification](enrichment-batches.md).
The run limit counts API requests; one grouped request can attempt up to three
jobs. Backfill's distinct `max_jobs` limit still bounds the selected job set.

Budgets in YAML deliberately leave headroom below the user's displayed limits.
Request/token reservations persist in PostgreSQL and include failures. Daily
budgets use a conservative rolling 24-hour window, minute budgets use a rolling
60-second window. Actual usage replaces reservations when available; interrupted
or uncertain calls retain reservations. Token reservations are estimates, not
provider token counts. API 429 remains authoritative. Other clients sharing the
same provider account are not included in this local ledger.

Missing keys skip that provider. Configuration/auth errors temporarily disable
the provider for 24 hours; 429 uses a cooldown (24h when daily quota is identified).
Exhaustion leaves work queued. Expected quota waiting can exit successfully;
mixed success/failure completes with `outcome=completed_with_errors` and exit 0,
with per-job failures retained in the retry queue. A batch with errors and no
successes exits 1 (`outcome=failed`); configuration/database failures still fail.
Airflow success therefore means the batch completed, not that every job succeeded.
Long JD inputs that fit no configured provider budget are marked failed rather
than silently truncated. Inspect `error_code` before changing budgets.
OpenRouter error envelopes inside HTTP 200 (such as upstream 503 overload) are
classified as provider failures and apply cooldown, not JSON validation failures.

As of 2026-09-26, OpenRouter is temporarily disabled (`enabled: false`) after
3 successes in 40 real-job attempts. Gemini and Groq remain enabled. Disabled
providers are skipped by the worker and synthetic smoke script. The prompt now
explicitly requires contiguous verbatim excerpts per input string, separate
quotes for separate passages, and empty evidence for null fields. Validation
remains strict; logs include the failing field without source text or responses.
Existing successful results are retained; no attempt counters are reset and no
historical backfill is enabled. Source/config are mounted into Airflow, so new
tasks load these changes without an image rebuild. Old failed runs stay failed.

## Storage and correctness

- Local: `core.job_enrichments`, `core.enrichment_attempts`,
  `core.enrichment_attempt_jobs`, `core.enrichment_provider_state`, `core.enrichment_settings`.
- `enrichment_attempts` is a request ledger (one row per API call); its child
  `enrichment_attempt_jobs` records per-job status/error. Mixed requests have
  status `partial`. Never multiply request token usage by the number of members.
- `core.enrichment_candidates` selects eligible content.
- `core.current_job_enrichments` only joins results matching current input hash.
- SHA-256 covers title, description, requirements, benefits, raw skills,
  experience and employment type. Crawl timestamps, IDs and unrelated HTML are
  excluded. Text changes, including whitespace changes, currently change the hash.
- Same-content successes are reused. Changing the model in config does not
  regenerate existing successes. Prompt/schema versions are stored explicitly.
- A session advisory lock prevents concurrent workers, including CLI plus Airflow.
  API calls occur outside database transactions. Interrupted work recovers on
  the next invocation without resetting attempt counts or quota reservations.
- Old content snapshots remain local for audit but are never exported for changed
  JD text. Supabase columns become null until a matching new result succeeds.

Validation checks schema keys/types/enums, experience bounds, duplicates and
verbatim evidence. It cannot guarantee semantic accuracy. No experience/remote
inference is made from missing fields. The provider smoke script uses synthetic
JD text; the historical September 26 evaluation also used real eligible jobs.
Neither establishes accuracy across every source. Maintain a representative
quality benchmark before increasing coverage or changing extraction policy.

## Serving contract for joblake-web

| Column | Type | Meaning |
|---|---|---|
| skills_required | nullable text[] | Explicit mandatory skills |
| skills_preferred | nullable text[] | Explicit preferred skills |
| experience_min_years | nullable double precision | Overall minimum; explicit months converted to years |
| experience_max_years | nullable double precision | Explicit overall upper bound |
| seniority_levels | nullable text[] | intern/fresher/junior/middle/senior/lead/manager/director |
| work_mode | nullable text | onsite/hybrid/remote |
| employment_type | nullable text | full_time/part_time/internship/contract/temporary/freelance |
| enrichment_status | text | not_enriched/pending/processing/retry_wait/failed/superseded/succeeded |
| enriched_at | nullable timestamptz | Successful enrichment timestamp |

`not_enriched` includes intentionally excluded old jobs and eligible jobs that
have not been enqueued yet. Null does not mean zero years/no skills/onsite. After
success a null field means the model found no explicit supported value. Detailed
evidence, provider metadata and failures stay local. Existing raw columns and
`serving.search_jobs` remain compatible. The additive `serving.search_jobs_v2`
supports experience/seniority/work-mode filters; see the
[website contract](../development/serving-contract.md). UI deployment belongs to
the separate frontend repository.

## Installation and verification

```powershell
.venv/Scripts/python.exe -m alembic upgrade head
.venv/Scripts/python.exe -m joblake.main --phase supabase-enrichment-setup
```

Base enrichment migration is `62e1356fadde`; request grouping adds
`0006_enrichment_batches`. Run `alembic upgrade head` before starting updated
workers. The grouping migration refuses to run while a worker owns the shared
lock and preserves existing attempts/quota totals. The cutoff is persisted and config must match.
Do not move it backwards to perform an implicit backfill. Supabase setup is an
idempotent additive DDL transaction, preserving rows, grants and RLS. Equivalent
SQL is versioned under `supabase/migrations/20260925113037_serving_enrichment.sql`.
The standalone setup applies DDL directly and does not register Supabase CLI
migration history; do not use a blanket migration push on this existing database.

Sync detects installed enrichment columns/views. Before installation it continues
to export original parser fields; with serving columns but no local view it
exports null AI fields. Running enrichment is never a prerequisite for sync.

Tests (SQL tests create/drop uniquely named disposable local databases):

```powershell
$env:JOBLAKE_TEST_ENRICHMENT='1'
.venv/Scripts/python.exe -m unittest discover -s tests -p 'test_enrichment*.py' -v
$env:JOBLAKE_TEST_SERVING='1'
.venv/Scripts/python.exe -m unittest discover -s tests -p 'test_supabase*.py' -v
```

`scripts/check_enrichment_providers.py` explicitly spends at most one request per
configured provider on a synthetic JD. It does not read stored jobs and is outside
the production quota ledger; reserve manual testing headroom when using it.

API references used during implementation (verify current provider behavior before changes):

- https://ai.google.dev/gemini-api/docs/generate-content/structured-output
- https://ai.google.dev/gemini-api/docs/models/gemini-3.1-flash-lite
- https://console.groq.com/docs/structured-outputs
- https://console.groq.com/docs/reasoning
- https://openrouter.ai/docs/api/reference/overview
- https://openrouter.ai/docs/guides/routing/provider-selection

Rollback: stop triggering enrichment. Original parser ingestion and serving sync
continue; no destructive schema rollback is necessary.
