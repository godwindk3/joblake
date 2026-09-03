# MinIO raw storage and SQLite state

JobLake uses MinIO for immutable raw detail HTML, SQLite for crawl and
parse state, and PostgreSQL for accepted normalized job records.

## Runtime configuration

`docker-compose.yml` exposes MinIO API port `9000` and console port
`9001`. The application reads credentials from the same environment
variables as Docker Compose:

```dotenv
MINIO_ACCESS_KEY=replace-me
MINIO_SECRET_KEY=replace-me

# Optional when the crawler runs on the host.
MINIO_ENDPOINT=localhost:9000
```

When the crawler runs in another Docker Compose service, set
`MINIO_ENDPOINT=minio:9000`.

Source YAML uses:

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
  provider: sqlite
  database_path: data/state/joblake.db
  detail_max_attempts: 3
  detail_retry_delay_seconds: 3600
  integrity_check_on_start: true
  integrity_check_limit: 100
```

`ensure_bucket: true` creates the bucket when it is missing.
`store_discovery: false` means listing HTML is not retained. Listing
pages are always crawled again; SQLite only stores per-run target
metrics.

## Running phases independently

The default `full` phase runs discovery and then consumes the pending
detail queue from SQLite:

```powershell
python -m joblake.main --config configs/itviec.yaml --phase full
```

The crawl phases can also run independently:

```powershell
python -m joblake.main --config configs/itviec.yaml --phase discovery
python -m joblake.main --config configs/itviec.yaml --phase detail
python -m joblake.main --config configs/itviec.yaml --phase parse
```

`detail` does not need discovery to run in the same process. It claims
pending URLs already stored in `jobs`. With
`discovery.continue_on_target_error: true`, a fetch or pagination error
marks only that target as failed; other targets continue and `full`
still enters the detail phase. A source-wide block such as Cloudflare
still stops the run to avoid repeatedly hitting the blocked website.

`parse` is intentionally separate from `full`: it reads only existing
`raw_ready` objects from MinIO and writes accepted records to PostgreSQL.
It never fetches a job URL. If a previous detail process stopped while
an upload was still in progress, first run `--phase detail` once so its
upload-recovery logic can finalize that object.

## State tables

- `crawl_runs`: one pipeline execution and its final status.
- `discovery_targets`: aggregate page and URL metrics for each target in
  one run. It is not a permanent page checkpoint.
- `jobs`: one current state row per `(source, url)`.
- `fetch_attempts`: immutable history of detail attempts and validation
  failures.
- `raw_objects`: the single accepted raw object locator for each job.
- `parse_attempts`: versioned parser attempt history, quality issues and
  the PostgreSQL result locator.

## Detail state flow

```text
pending
  -> fetching
  -> validating
  -> uploading
  -> raw_ready
```

Only `raw_ready` means the URL has been successfully crawled. Blocked,
invalid, failed, or interrupted responses remain retryable until
`detail_max_attempts` is reached.

Before upload, JobLake stores the expected bucket, deterministic object
key, byte length, and SHA-256 in `fetch_attempts`. If the process exits
after MinIO accepts the object but before SQLite commits `raw_ready`, the
next run checks the pending object and completes or rejects the upload.

## Raw HTML validation

Validation runs before an object is accepted into `raw_objects`:

1. HTTP status must be `200`.
2. Content type must be HTML when the server provides it.
3. HTML and visible text must meet configured minimum sizes.
4. Known block and challenge pages are rejected.
5. Final host and path must match the source.
6. Every configured required selector must exist.

Example:

```yaml
detail:
  validation:
    min_html_bytes: 5000
    min_text_chars: 100
    required_selectors:
      - h1
    allowed_hosts:
      - itviec.com
      - www.itviec.com
    required_path_prefixes:
      - /it-jobs/
```

Selectors supported by the lightweight validator include `tag`, `#id`,
`.class`, `tag[attr]`, and `tag[attr='value']`. Source adapters can later
override `validate_detail_html()` for stronger website-specific rules.

## Parse flow and finding raw HTML

The parse phase queries SQLite instead of listing the MinIO bucket:

```sql
SELECT
    j.id AS job_id,
    j.source,
    j.url,
    r.id AS raw_object_id,
    r.bucket_name,
    r.object_key,
    r.object_version,
    r.content_length_bytes,
    r.content_sha256
FROM jobs AS j
JOIN raw_objects AS r ON r.job_id = j.id
WHERE j.raw_status = 'raw_ready'
AND NOT EXISTS (
    SELECT 1
    FROM parse_attempts AS p
    WHERE p.raw_object_id = r.id
      AND p.parser_name = :parser_name
      AND p.parser_version = :parser_version
      AND p.status IN (
          'success',
          'validation_error',
          'raw_missing',
          'raw_corrupt'
      )
);
```

The parser downloads `bucket_name + object_key`, checks byte length and
SHA-256, then uses the configured source parser. A new parser version
reuses the same raw object and does not call the source website again.
Successful and partial records are written transactionally to PostgreSQL
before SQLite marks the attempt successful. Replaying the same raw hash
and parser version returns the existing PostgreSQL row without overwriting
it.

Rejected output is retained in `parse_attempts` with validation issues
but is not inserted into PostgreSQL. Transient parser/database failures
retry in a later parse run up to `parse.max_attempts`; exhausted objects
make the run `suspicious` and are reported in its summary. In-progress
claims are only recovered after `parse.stale_after_seconds` (default one
hour), preventing a second parser process from stealing a recent claim.

At startup, the configured integrity audit rotates through raw objects
that were checked least recently. It uses MinIO object metadata to detect
missing objects and size mismatches. A future parser must still download
the object and verify the full SHA-256 before parsing.

## Existing local data

Legacy JSONL/TXT state and local raw files are not imported
automatically. Automatic import could mark a URL as complete without a
verified MinIO object. Migrate old data with a dedicated, auditable
command before relying on it in the new state database.
