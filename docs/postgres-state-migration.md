# PostgreSQL crawler state

The four source configs use `state.provider: postgres`. State lives in the
existing JobLake PostgreSQL database, in schema `crawl_state`; parsed output
continues to use `core` and `ref`. MinIO keeps the same immutable HTML objects.
Airflow metadata remains in its own database. Listing CDC is described in
[URL CDC operation](url-cdc.md).

## Configuration

State reuses the existing `postgres` section and `POSTGRES_*` environment variables,
with application name `joblake-state`. Connection/schema errors fail the task;
there is no SQLite fallback. Run `alembic upgrade head` before ingestion.
The application does not create PostgreSQL tables at startup.

`state.database_path` remains only as a legacy SQLite setting and backup reference.
Browser session files still use `data/state`, so retain the Airflow volume mount.
The existing psycopg dependency is sufficient; no new service is required.

All six state tables retain their IDs, keys, statuses and retry behavior. Times
use `TIMESTAMPTZ`; SQLite times without offsets are interpreted as UTC. JSON
reports remain text. `core` crawler ID references retain their original meaning.

## Concurrency

Keep the one-slot Airflow pool. Each pipeline phase acquires a dedicated session
advisory lock for its source before recovery and holds it until exit. Another
phase for that source fails immediately. Use `IngestionPipeline` as the entry
point: direct state-store calls are not a supported parallel worker API.

Claims commit before HTTP/MinIO calls. Same-source parallel workers still require
leases/heartbeats and are outside this migration. Parsed output and state writes
retain separate transactions and the existing replay behavior.

## Offline migration

Stop all writers and drain active/queued tasks. Back up JobLake with `pg_dump -Fc`
and test a restore in a separate database. Create a consistent SQLite snapshot:

```powershell
.venv/Scripts/python.exe scripts/migrate_state_to_postgres.py snapshot --sqlite data/state/joblake.db --output data/state/backups/run-id/joblake.db
```

Rehearse schema migration and import in a separate database, then run on JobLake:

```powershell
.venv/Scripts/python.exe -m alembic upgrade head
.venv/Scripts/python.exe scripts/migrate_state_to_postgres.py import --sqlite data/state/backups/run-id/joblake.db
.venv/Scripts/python.exe scripts/migrate_state_to_postgres.py verify --sqlite data/state/backups/run-id/joblake.db
```

Import refuses nonempty targets. All rows are imported and compared in one
transaction; IDs are preserved and sequences advanced. Verification compares
every column after timestamp normalization and reports counts/hashes. Switch all
source configs only after verification, then check host and Airflow connections.
After new ingestion writes, comparison against the old snapshot will naturally
differ. Preserve the cutover report.

## Rollback and backups

Before new PostgreSQL ingestion writes, the verified SQLite snapshot can be used
by reverting the provider. After new writes, stop writers and reconcile/export
the new state first, or fix forward. No automatic reverse migration is provided.
Do not drop the PostgreSQL schema as part of ordinary rollback.

Back up `crawl_state`, `core` and `ref` together. The old SQLite file is a frozen
reference, not a synchronized backup. Existing reset tools for parsed output and
raw objects are not a complete reset of crawler state.

## Tests

```powershell
$env:JOBLAKE_TEST_POSTGRES='1'
.venv/Scripts/python.exe -m unittest discover -s tests -v
```

Integration tests create uniquely named temporary databases and drop only those
databases. The test account needs database creation permission. They never
truncate the configured JobLake database.

## Cutover on 2026-09-12

Backup directory: `data/state/backups/20260912T035924Z/` (ignored by Git).
It contains the consistent SQLite snapshot, PostgreSQL custom-format dump,
successful restore rehearsal, row-comparison import report, final audit and test log.
Imported: 70 runs, 58 targets, 5,071 jobs, 5,179 fetch attempts, 5,020 raw objects
and 5,020 parse attempts. Every imported row matched; all existing parsed-output
references matched state IDs.

The TopDev live smoke run scanned 10 pages / 141 URLs with zero new URLs; detail
and parse had no pending work and completed successfully (runs 71 and 72).
The original SQLite data remained unchanged. All 127 tests passed, including
13 real PostgreSQL integration tests. No DAG was triggered or resumed by this
migration; the final check found no running/queued DAG runs. Existing DAG pause
flags were left unchanged (unpaused).
