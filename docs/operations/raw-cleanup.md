# Raw HTML cleanup

`joblake_raw_cleanup` runs at 15:00 Asia/Ho_Chi_Minh, starts paused, and
defaults to dry-run. It reserves all three slots in the `joblake_serial` pool
to avoid overlapping ingestion, and uses the same PostgreSQL
source advisory locks as discovery/detail/parse. Busy sources are skipped.

Only MinIO objects in the configured bucket's `raw/detail/` prefix are deleted.
No rows in `core` or `ref` are deleted or changed. Parsed text and analytical
history remain available; deleted HTML cannot be reparsed until fetched again.

## Eligibility

- CDC expired for at least 7 days and not subsequently observed.
- Or unknown, raw older than 30 days, and absent across at least two qualifying
  scans in the current scope spanning at least 7 days after last observation.
- Both require a current parsed result matching the raw hash, bucket and key.
- Active jobs, unparsed raw and in-progress parses are excluded.
- Orphan objects and historical bucket versions are deliberately excluded:
  current state does not provide a complete persistent orphan observation log.

Limits default to 200 objects / 250 MiB per task attempt. Retries have a new
budget. Output JSON includes candidate totals, per-source/status bytes, bounded
selected keys, deleted bytes, missing/changed objects and busy sources.
Dry-run reports DB candidates, not verified physical storage occupancy.

## Rollout

1. Deploy code and apply `alembic upgrade head` before restarting crawler tasks.
   Migration 0005 adds only crawl-state metadata and a deletion journal.
2. Run `python -m joblake.raw_cleanup` and review the candidate JSON.
3. Inspect MinIO lifecycle/versioning. Apply refuses versioned/suspended buckets
   and enabled expiration rules, which could bypass the DB protection policy.
   Review lifecycle configuration explicitly; this tool never changes it.
4. Trigger the Airflow DAG with `apply=false` first, then `apply=true` for a
   reviewed batch. Unpausing alone continues daily dry-runs. To make scheduled
   executions delete, intentionally change the DAG's default `apply` parameter.

CLI example: `python -m joblake.raw_cleanup --apply --max-objects 200 --max-mib 250`.
Airflow parameters also expose `expired_days` and `unknown_days`.

## Recovery and reappearance

Before deleting, cleanup commits an intent row, verifies the current object's
size and SHA256, and holds the source lock. Changed objects are skipped.
After deletion it sets `raw_objects.purged_at`; `storage_missing` on the job is
distinguished as intentional by this marker. Integrity auditing skips such raw.
If interrupted after deletion, a later attempt detects the missing object and
completes the marker; prior pending journal rows remain as historical intents.

When discovery observes a purged job again, it queues a fresh fetch and grants
a fresh retry budget while preserving monotonic fetch attempt numbers. Upload
replaces the current raw metadata and clears the purge marker. Old parse
attempts are retained but do not block parsing the refreshed raw generation.
All writers must honor the source lock; external/manual MinIO writers are not
coordinated by this mechanism.

Do not roll back migration 0005: it records intentional deletions. To stop
cleanup, pause the DAG or set `apply=false`.
