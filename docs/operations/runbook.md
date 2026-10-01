# JobLake operational runbook

Run from the repository root after [local setup](../setup/local.md). Commands
below describe separate actions; ingestion does not automatically trigger parse,
enrichment or remote sync. Airflow equivalents are in [source operations](airflow-sources.md).

## Collect and publish

```powershell
python -m joblake.main --config configs/topdev.yaml --phase discovery --strict
python -m joblake.main --config configs/topdev.yaml --phase detail --strict
python -m joblake.main --config configs/topdev.yaml --phase parse --strict
python -m joblake.data_health
python -m joblake.health_policy
```

Inspect any alerts before publication. `--strict` flags blocked/failed execution,
while suspicious runs remain successful. The health gate adds quality checks; it
does not reset retries, repair records or verify MinIO objects live.

Optional enrichment can run after parse; first inspect its dry-run and provider
budgets. Then preview and apply serving sync when the local state is ready:

```powershell
python -m joblake.main --phase enrich --dry-run
python -m joblake.main --phase supabase-sync --dry-run
python -m joblake.main --phase supabase-sync
```

Enrichment dry-run does not invoke models or update its queue. Actual enrichment
requires a separate invocation without `--dry-run`. Sync publishes all sources,
not just the last source crawled, and can remove expired/unknown rows. Use
[sync rules](supabase-cli.md) to interpret the preview. Sync verifies the same
staged snapshot before commit; a later standalone verify can see newer local data.

## Investigate alerts

| Finding | Next action |
| --- | --- |
| Missing/stale report | Check the health DAG, scheduler, DB connection and report directory; regenerate a complete snapshot |
| No recent completed phase | Inspect that source's phase status and intended manual cadence; suspicious is not completed |
| Fetch backlog | Inspect batch limits, next retry time, terminal HTTP 410 and blocked/validation errors |
| Parse backlog/error rate | Inspect latest attempt samples and retained HTML; repair/version the parser only with evidence |
| Stuck fetch/parse | Inspect the active process and source lock before retrying; normal recovery honors stale thresholds |

An Airflow Clear replays the phase but does not reset exhausted records or ignore
`next_retry_at`. Never remove validation merely to turn a task green. `partial`
is accepted data. Tune [health budgets](data-health.md) to volume and crawl cadence;
do not disable a threshold solely because it exposes unresolved work.

## Retention and recovery

Raw cleanup is scheduled but defaults to preview. [Review candidates](raw-cleanup.md)
before applying a bounded deletion batch. Docker log rotation and
[Airflow task-log cleanup](log-retention.md) are separate policies. Health snapshots
and maintenance/enrichment logs currently have no automatic retention.

Back up local PostgreSQL schemas together, preserve required raw objects and
browser sessions, and keep credentials/config recoverable outside Git. Test a
restore into a separate database. This repository does not currently supply an
automated backup schedule or a verified recurring restore drill.

## Operational limits

- Source, sync and enrichment DAGs are manual; no ingestion-to-sync scheduler exists.
- Source tasks have request/state budgets but no Airflow `execution_timeout` yet.
- Health failures appear in reports and Airflow; no email/chat notification sender
  or independent report watchdog is installed. The offline health CLI can be
  invoked by an external scheduler, but a stopped scheduler cannot alert on itself.
- CI checks code, migrations and the runtime image; browser access and frontend
  deployment still require environment-specific smoke tests.

See the dated [verification record](../archive/verification-2026-10-01.md) for what
has actually been checked, rather than treating these instructions as proof of
deployment or current production health.
