# Supabase migration test

JobLake keeps local PostgreSQL as the processed-data authority. This procedure
copies only the curated serving schemas (`ref` and `core`) to Supabase; it never
copies MinIO raw HTML, crawler SQLite state, PostgreSQL roles, or Supabase-owned
schemas.

## Configuration

Copy the safe placeholders from `.env.example` into the untracked `.env` file
and replace only the values there. The expected variables are:

```dotenv
LOCAL_DATABASE_URL=postgresql://...
SUPABASE_DATABASE_URL=postgresql://...?sslmode=require
```

Use the Supabase **direct PostgreSQL connection** URI, not an HTTP API URL. Do
not use a Supabase service key. A direct database connection is needed by
`pg_restore`.

## Audit and connectivity

Run these commands from the repository root using the project's working Python
environment:

```powershell
python scripts/inspect_local_postgres.py
python scripts/test_supabase_connection.py
python scripts/migrate_to_supabase.py --preflight-only
```

The connectivity script runs only `SELECT version()` and `SELECT
current_database(), current_schema()`. The preflight verifies that `core` and
`ref` do not already exist in the selected Supabase database.

## Initial migration and verification

```powershell
python scripts/migrate_to_supabase.py
python scripts/verify_supabase_migration.py
```

The migration is intentionally conservative:

- `pg_dump` uses custom format with `--schema=ref --schema=core`, `--no-owner`,
  and `--no-privileges`.
- `pg_restore` uses `--single-transaction` and `--exit-on-error`.
- It never runs `--clean`, nor does it name `public`, `auth`, `storage`,
  `extensions`, `realtime`, or any Supabase internal schema.
- It refuses to start if destination `ref` or `core` already exists. This avoids
  silently merging into or overwriting a previous test.

The verifier compares every migrated table's row count and ID range, important
null counts, known unique keys, constraint definitions, index definitions,
identity-sequence state, deterministic JSON samples, and the count of rows with
non-ASCII text.

If PostgreSQL client programs are not on `PATH`, set these only for the current
PowerShell session before running migration:

```powershell
$env:PG_DUMP_BIN = 'C:\Program Files\PostgreSQL\18\bin\pg_dump.exe'
$env:PG_RESTORE_BIN = 'C:\Program Files\PostgreSQL\18\bin\pg_restore.exe'
```

`pg_dump` creates a temporary file and deletes it on completion. Use
`--keep-dump` only when you deliberately need to retain a local copy of the
curated data.

## Scoped rollback for this test

Only after verifying that the target is the disposable test project and that
these schemas contain no other data, connect with Supabase's SQL editor or
`psql` and run:

```sql
DROP SCHEMA IF EXISTS core CASCADE;
DROP SCHEMA IF EXISTS ref CASCADE;
```

This leaves all Supabase-owned schemas and the local database untouched.

## Future incremental sync

Do not replace local PostgreSQL. Implement a separate, batched UPSERT worker
once this one-time migration has passed verification. Use the existing unique
keys in dependency order:

1. `ref.sources(code)`;
2. `core.source_job_postings(source_id, canonical_url)`;
3. immutable parse results on `(source_posting_id, raw_sha256, parser_name,
   parser_version)`.

The posting key already provides the closest current stable identity. Where a
source supplies a reliable external identifier, retain and use
`source_external_job_id` as an additional match key, but do not change the
current database design merely for this test. Each batch should commit only
after all three layers succeed and should be rerunnable without duplicating
rows.
