# Historical operation report

Dated observations; not a current health check.

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
