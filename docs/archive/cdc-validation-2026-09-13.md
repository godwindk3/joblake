# Historical operation report

Dated observations; not a current health check.

## Deployment check, 2026-09-13

Migration `0003_url_cdc` preserved 5,114 URLs and all existing crawl/parse rows.
The PostgreSQL backup and migration/test reports are in
`data/state/backups/cdc-20260913T032947Z/` (not tracked by Git).
TopDev run 85 created a baseline of 130 URLs from 9 pages. Run 86 completed
reconciliation with 0 expired and 0 reappeared. Historical unseen URLs remained
unknown. The other enabled sources establish their baseline on their next
qualifying discovery; no extra DAG runs or schedules were created.
