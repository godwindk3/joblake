# Standalone Docker (without Airflow)

This stack runs PostgreSQL, MinIO and one small Python runner. The runner starts
up to **three source subprocesses** concurrently; each source runs
`discovery -> detail -> parse`. A free slot immediately takes the next source.
Python, CloakBrowser, browser system libraries and Xvfb are inside the image.
Only Docker Engine with Compose v2 (or Docker Desktop with Linux containers)
is needed on the host.

## First deployment

Run from the repository root. Copy `.env.example` to `.env` if it does not exist
and fill in `POSTGRES_PASSWORD`, `MINIO_ACCESS_KEY` and `MINIO_SECRET_KEY`.
MinIO requires an access key of at least 3 characters and a secret of at least
8 characters. Review the source scopes/budgets in `configs/*.yaml` before running.

```sh
docker compose -f compose.standalone.yaml build
docker compose -f compose.standalone.yaml run --rm --no-deps joblake-runner validate
docker compose -f compose.standalone.yaml up -d
docker compose -f compose.standalone.yaml logs -f joblake-init joblake-runner
```

Or use `docker compose -f compose.standalone.yaml up -d --build` after configuration.
On first start, `joblake-init` waits for authenticated PostgreSQL/MinIO access and
runs `alembic upgrade head`. The runner starts only if init succeeds, then begins
the first crawl immediately. `joblake-init` exiting with code 0 is expected.

The stack uses the project name `joblake-standalone` and **new, separate volumes**:
`postgres_data`, `minio_data`, `runner_data`, `runner_output`. Existing local/core
or Airflow volumes are not reused or migrated. Restore the full PostgreSQL backup
and required MinIO/browser state if continuing an existing deployment. Do not
enable sync against an existing serving database from a new/partial local DB:
sync reconciles the entire dataset, including removals.

No database or MinIO ports are exposed to the host by default. Services communicate
using `postgres:5432` and `minio:9000`. The runner derives `LOCAL_DATABASE_URL` from
the same internal `POSTGRES_*` settings used by ingestion and migrations, ignoring
the host-oriented URL/port in `.env`. Source-specific credentials and optional
provider settings still come from `.env`.

## Schedule and optional tasks

Edit `orchestration/standalone/config.yaml`, then restart the runner to reload it:

```sh
docker compose -f compose.standalone.yaml restart joblake-runner
```

- `max_concurrent_sources: 3`: set to 1 or 2 for a smaller server. Browser memory
  still scales with concurrency; the image gives browser processes 1 GiB shared memory.
- `sources`: ordered source queue. Each code must name an enabled `configs/<code>.yaml`.
- `interval_seconds: 86400`: wait 24 hours **after a cycle finishes**, not a daily
  clock time. The saved next-run timestamp survives restarts. Missed intervals
  coalesce into one run; there is no catch-up queue. An interrupted cycle is retried
  on restart using the crawler's existing state/recovery rules.
- `phase_timeout_seconds: 14400`, `phase_retries: 2`: four hours per attempt, at
  most three attempts per ingestion phase. Review against real source size and
  delays. Exit 124 indicates timeout; 130 indicates interruption.
- `enrichment.enabled: false`: enable only after configuring provider credentials
  and the local enrichment settings. Uses the persistent AI queue and a bounded
  job/time budget without outer retries.
- `sync.enabled: false`: enable after verifying the complete local dataset and
  provisioning the serving schema/credentials. Requires all configured sources in
  the runner list. Does not run remote schema setup or migrations.
- `cleanup.enabled: true`, `cleanup.apply: false`: bounded dry-run at the end of
  a cycle when due (24 hours by default). It never overlaps this runner's crawl,
  enrichment or sync. Set `apply: true` only when actual retention is intended;
  existing eligibility rules remain in force. It is not an independent exact-time
  scheduler; a long cycle delays maintenance until the runner is free.

After all sources finish, the runner writes a fresh health report and checks it.
Only the selected sources are evaluated, with their existing health thresholds.
Any failed ingestion phase or health check blocks enrichment and sync for that
cycle. A failed discovery still allows detail/parse to drain backlog; other
sources continue. Suspicious ingestion remains exit 0 under the existing CLI
contract and is subject to the health gate.

When enabled and eligible, global tasks run `enrichment -> connection check ->
sync`. An enrichment failure is recorded but does not block publication of valid
base data. Sync performs its existing transactional verification before commit.
Cleanup is independent of publication success and makes one bounded attempt.

## Inspect, run once, stop

```sh
docker compose -f compose.standalone.yaml ps -a
docker compose -f compose.standalone.yaml logs --tail 200 joblake-runner
docker compose -f compose.standalone.yaml exec joblake-runner python -m joblake.standalone status
docker compose -f compose.standalone.yaml stop
```

The latest cycle's phase exit codes, elapsed times and next-run timestamp are in
`data/state/standalone/latest.json` in `runner_data`; health JSON/Markdown reports
are under `data/state/standalone/health`. `status` shows the last finished cycle,
not live task progress; use logs for progress. Docker health checks measure the
runner heartbeat, **not data quality**. A failed cycle stays visible in `status`
while the scheduler remains healthy and waits for the next interval. Logs rotate
at 10 MiB x 3 files per container. Health report retention is not automatic.

For a manual cycle, stop the scheduled runner first. `once` ignores the saved
next-run timestamp and returns nonzero on any task/health failure:

```sh
docker compose -f compose.standalone.yaml stop joblake-runner
docker compose -f compose.standalone.yaml run --rm joblake-runner once
docker compose -f compose.standalone.yaml up -d joblake-runner
```

A shared filesystem lock rejects simultaneous `once`, `schedule` or `init` on the
same runner volume. It does not coordinate separate volumes or Airflow/manual CLI
processes; use one orchestrator per database. Existing per-source DB locks remain
an additional guard. Stop signals interrupt child process groups and retry waits;
no new phase starts during shutdown.

## Upgrade and recovery

```sh
docker compose -f compose.standalone.yaml stop joblake-runner
docker compose -f compose.standalone.yaml build
docker compose -f compose.standalone.yaml run --rm joblake-init
docker compose -f compose.standalone.yaml up -d
```

Stop ingestion before migrations. Back up PostgreSQL and required raw/browser
state before moving servers or changing schemas. `down` preserves named volumes;
`down -v` deletes them. `restart: unless-stopped` resumes running services when
Docker starts again, provided Docker itself starts on boot and you have not
manually stopped the containers.

This mode supplies no Airflow UI, external alert delivery, automatic backups or
enrichment backfill schedule. Local/manual CLI and Airflow remain available.
