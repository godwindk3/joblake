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
- `parse_outcomes_in_window`: one latest terminal attempt per job, used for the
  quality gate's error-rate denominator rather than summed historical attempts.
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

Both generation and the offline gate accept `--thresholds`; it defaults to
`configs/data_health.yaml`. Source enumeration skips shared YAML without a source
key and rejects invalid or duplicate source names before connecting to PostgreSQL.

## Quality checks

`configs/data_health.yaml` defines initial budgets, with per-source overrides:

| Threshold | Default | Meaning |
| --- | --- | --- |
| freshness_hours | 48 | Maximum hours since a completed discovery, detail and parse run |
| max_pending_fetch | 100 | Pending fetch jobs per source |
| max_parse_backlog | 100 | Unpurged raw objects without a usable current parse |
| max_stuck_jobs | 0 | Stuck fetches plus latest stuck parses |
| max_parse_error_pct | 20 | Error percentage among the latest terminal parse outcomes per job in the report window |
| min_parse_jobs | 10 | Minimum distinct jobs before evaluating the error percentage |

Limits are exceeded strictly (`observed > limit`). Set an individual threshold
to `null` to disable it; `min_parse_jobs` must remain a positive integer. Source
overrides merge with defaults. Unknown source names or threshold keys are errors.
These budgets are initial operational choices, not measured SLAs; tune them to
each source's volume and intended crawl cadence. A manually operated source can
exceed freshness even when no new run has been requested.

A completed `full` run satisfies discovery and detail freshness, never parse.
Missing success history and missing inventory are alerts. `suspicious` does not
count as completed. Partial parses have a successful terminal status and count
as usable; optional missing fields do not trigger alerts. The parse error rate
counts each job once using its latest non-`parsing` attempt started in the window,
so a successful retry replaces earlier failure instead of inflating the rate.
Backlog still includes expired jobs, matching the inventory report.

Generation saves the thresholds and alert list in JSON and displays alerts at
the top of Markdown. Data issues do not prevent saving the report. The separate
Airflow `check_quality` task runs after `generate_report` and fails on alerts,
without retrying the same quality findings. Database/query/write errors in
generation retain two retries. No partial report is saved when a query fails.

Check the latest snapshot independently, without a database connection:

```powershell
python -m joblake.health_policy
python -m joblake.health_policy --max-report-age-hours 30
```

Exit codes: **0** healthy, **1** quality alerts, **2** missing/stale/invalid report
or configuration. The default age budget is 30 hours for independent daily checks;
Airflow's immediate post-generation check uses one hour. Future
timestamps beyond five minutes are rejected. Reports made before the new parse
outcome metric must be regenerated. `--output-dir`, `--config-dir`, and
`--thresholds` allow explicit paths. Run from the repository root.

Alerts are available in Airflow task status/logs and saved reports. No email/chat
delivery or automatic remediation is configured. An independent scheduler can
invoke this read-only check to detect a missing daily report; a stopped Airflow
scheduler cannot monitor itself.
