# Raw storage and PostgreSQL state

All nine source configs use MinIO for raw detail HTML and the local PostgreSQL
database for both operational state (`crawl_state`) and normalized output
(`core`, `ref`). Airflow metadata uses a separate database. SQLite/file state
is retained for legacy use and migration; there is no automatic fallback.

## Runtime configuration

MinIO exposes API port 9000 and console 9001 in the core Compose stack. Credentials
come from `MINIO_ACCESS_KEY` and `MINIO_SECRET_KEY`. Host CLI uses
`MINIO_ENDPOINT=localhost:9000`; the separate Airflow stack defaults to
`host.docker.internal:9000`. Service-name addressing only works on a shared network.

Typical source settings (use the source's actual YAML for its retry budget):

```yaml
storage:
  provider: minio
  endpoint: localhost:9000
  endpoint_env: MINIO_ENDPOINT
  access_key_env: MINIO_ACCESS_KEY
  secret_key_env: MINIO_SECRET_KEY
  bucket_name: joblake
  secure: false
  ensure_bucket: true
  prefix: raw
  store_discovery: false
state:
  provider: postgres
  detail_max_attempts: 3
  detail_retry_delay_seconds: 3600
  integrity_check_on_start: true
  integrity_check_limit: 100
```

`ensure_bucket` creates a missing bucket. Listing pages are fetched again on
each discovery run; target metrics are not permanent page checkpoints.

## State and recovery

`crawl_runs` and `discovery_targets` track execution; `jobs` identifies URLs by
source; `fetch_attempts`, `raw_objects` and `parse_attempts` track acquisition and
parsing. CDC adds source baselines and URL events. Raw cleanup adds purge metadata
and a deletion journal. See [schema setup](../setup/postgres.md).

Detail moves through `pending -> fetching -> validating -> uploading -> raw_ready`.
Before upload it persists the locator, byte length and SHA-256. A later detail run
can recover an interrupted upload by checking the object, or mark it retryable
when missing/corrupt. HTTP 410 is terminal; other failures follow source/state
retry policy. A source-wide block stops the run. CareerLink additionally stops
detail after its configured consecutive-error limit.

A PostgreSQL session advisory lock covers each source phase, including recovery.
Different sources can run concurrently. Claims commit before network calls; state
and normalized-result writes use separate transactions with idempotent replay.
The default source-lock wait is zero; CareerLink currently waits up to 60 seconds.
See [state concurrency and cutover](../operations/postgres-state-migration.md).

## Validation and parsing

Raw acceptance checks HTTP status, HTML content/size, challenge pages, expected
host/path and source-specific identity/content rules. Only accepted raw objects
enter normal parsing. Browser evidence has a separate diagnostics lifecycle.

`parse` looks up eligible `raw_ready` objects in PostgreSQL; it does not enumerate
the bucket or fetch the website. It downloads the recorded locator and checks
byte length, full SHA-256 and UTF-8 before invoking the source parser. Metadata
audits at ingestion startup supplement, but do not replace, this full check.

Accepted/partial results are committed to `core.job_parse_results` before the
parse attempt is marked successful. The identity is posting + raw hash + parser
name/version, so replay returns the existing result. A new parser version can
reprocess retained raw without crawling again. Validation rejections are recorded
in `crawl_state.parse_attempts`, not inserted as usable normalized output.
Transient parse errors have bounded retries; exhausted work makes the run
`suspicious`. Stale in-progress parses recover after `parse.stale_after_seconds`.

If detail stopped during upload, run detail recovery before parse. Clearing an
Airflow task does not reset per-URL attempts or bypass `next_retry_at`.

## Retention and publication

Raw cleanup deliberately removes only eligible, already-parsed objects and marks
their state. Parsed history stays local. A purged job observed again is queued
for a fresh fetch. See [raw cleanup](../operations/raw-cleanup.md).

Supabase stores a compact active-job projection, not the local state tables or
all historical parses. Missing usable content does not by itself prove expiry;
sync can retain previously published content while a current active job awaits
parsing. See [serving sync](../operations/supabase-cli.md).

Back up `crawl_state`, `core` and `ref` together. Legacy SQLite snapshots are frozen
cutover references, not synchronized backups. Raw HTML and browser sessions have
separate recovery requirements; see the [runbook](../operations/runbook.md).
