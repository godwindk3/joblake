# JobLake Supabase CLI

Run from the repository root with the installed JobLake environment.

```powershell
python -m joblake.main --phase supabase-test
python -m joblake.main --phase supabase-migrate --preflight-only
python -m joblake.main --phase supabase-migrate
python -m joblake.main --phase supabase-sync --dry-run
python -m joblake.main --phase supabase-sync
python -m joblake.main --phase supabase-verify
```

Use migrate once on a target without `core` or `ref`. For the already migrated
project, use sync directly. Sync updates/inserts all three application tables
and preserves their local IDs. It requires the existing schema and the original
replica's ID mapping; conflicting IDs or natural keys fail and roll back the
entire transaction. No row deletion, retention, or serving-schema redesign is
included. The local parser remains the authority for all synced fields.

All sources are synced together. `--config configs/topdev.yaml` remains accepted
but only configures ingestion phases, not Supabase phases.

The CLI loads the repository `.env`. Existing process environment takes priority.
Set `SUPABASE_DATABASE_URL` to the direct or session-pooler URI with
`sslmode=require`. Local settings reuse `POSTGRES_HOST`, `POSTGRES_PORT`,
`POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`. An explicit
`LOCAL_DATABASE_URL` overrides those values: remove an obsolete URL to avoid
connecting to the wrong port. No credentials belong in Git.

Sync reads a consistent local snapshot in batches of 200 rows. It uses one
remote transaction and locks the three destination tables against concurrent
writes, while ordinary SELECT queries remain possible. The remote should be
dedicated to this local data source. Dry run executes validation/upserts but
rolls back row changes; it still obtains locks and is not a read-only query.
Identity sequences are advanced transactionally only on a real sync.

This deliberately scans all rows on every run; no cursor/checkpoint can skip a
late local update. Pause parsing during verification to avoid differences from
newly committed local data. Verification retains the original count, ID-range,
constraint/index, null, sequence and sample checks; it is not an exhaustive
byte-for-byte audit. Remote-only rows are never deleted and can cause verify to
report a difference.

Old scripts remain compatibility entry points. The package implementation is
under `src/joblake/supabase_*.py`. Migration needs pg_dump/pg_restore; sync,
connection testing and verification use Psycopg directly.
