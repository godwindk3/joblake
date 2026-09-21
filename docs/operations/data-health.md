# Data health report

`joblake_data_health` runs daily at **07:00 Asia/Ho_Chi_Minh**, with catchup
disabled and initially paused, matching the repository's operational convention.
Unpause it in Airflow for daily reports or trigger it manually.

The `generate_report` task reads PostgreSQL in a single repeatable-read,
read-only transaction. It does not crawl, retry jobs, modify source data, or
contact MinIO. PostgreSQL migrations through `0005_raw_cleanup` are required.

## Output

Each execution writes a unique timestamped JSON snapshot and Markdown report to
`data/state/reports/data_health/`. The existing Airflow bind mount exposes these
files at the same path under the host repository. The report is also printed in
the task log. Snapshots are retained until manually removed; retries can produce
an additional snapshot rather than overwrite an earlier report.

- Inventory by source, including configured sources with no jobs.
- Current fetch errors, latest parse-attempt status, and bounded error samples
  per source/stage/status/error type with job IDs and URLs.
- Historical fetch/parse attempt counts and distinct affected jobs by error group.
  Distinct job counts across groups must not be summed: one job may occur in several.
- Current parse quality and missing-field percentages; optional absent fields
  are informational and do not automatically mean the parser failed.
- Pending fetches, overdue retries, stuck fetch/parse work, oldest pending time,
  and raw objects without a usable current parse matching the raw content hash.
- Raw objects intentionally purged are counted separately and excluded from
  parse backlog. Raw availability describes metadata, not verified object storage.
- Last completed run by source/phase, and discovery/CDC activity during the window.
  A phase with no completed run has no freshness row; absence is not success.

Current parse status means the latest attempt per job across parser versions;
quality describes the current stored result, which may precede a failed reparse.
The report includes expired jobs in totals/backlog; expiry alone is not an error.
Historical windows use attempt/run start times; new jobs use first-seen time.
Reports describe execution-time data, including manual runs, not a historical
reconstruction of the Airflow logical date. Compare JSON snapshots for trends.

## Parameters and manual execution

Airflow parameters: `window_hours=24`, `stale_hours=6`, `samples=5`.
The stale threshold flags in-progress work; it is not a source freshness SLA.

```powershell
python -m joblake.data_health --window-hours 24 --stale-hours 6 --samples 5
```

Run from the repository root with its Python environment. Existing PostgreSQL
environment variables and `.env` are used. `--output-dir` and `--config-dir` can
override the defaults for CLI use.

Data issues do not fail the DAG. Database/query/write errors fail the task and
are retried twice. No partial report is saved when a query fails. No notification
service or automatic remediation is configured.
