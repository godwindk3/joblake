# Health and CI verification — 2026-10-01

This is a dated local verification record, not a live status page. Times below
are Asia/Ho_Chi_Minh (UTC+07:00) unless explicitly marked UTC.

## Changes verified

- Health thresholds are configurable per source in `configs/data_health.yaml`.
  Reports preserve the policy and alerts. The offline gate returns 0/1/2 for
  healthy/alerts/check errors and detects missing/stale snapshots.
- Parse error rate uses one latest terminal attempt per job in the window;
  successful retries replace earlier failures. Partial parses remain usable.
- Airflow health has `generate_report -> check_quality`, preserving reports
  before its independent non-retrying quality check.
- CI configuration adds Windows/Linux unit tests, PostgreSQL 16 integration and
  migrations, and production Airflow image/DAG validation.
- DAG validation now expects the actual one-minute fixed retry delay and
  CareerLink detail's zero Airflow retries.

## Test evidence

The full suite ran **340 tests with no failures or skips** using uniquely named
disposable local databases. Coverage includes state, CDC, serving sync/search,
enrichment SQL and health policy. A subsequently added test also passed: complete
Alembic migration from an empty disposable database and health SQL verifying
retry de-duplication and exclusion of old/in-progress attempts. Thus 341 tests
were verified across two runs, not in a single 341-test run.

Runtime: bundled Python 3.12 with project `src` and dependencies from the existing
`.venv` on PYTHONPATH because its launcher could not start the original interpreter.
This is not a clean-install or cross-platform CI result. Operational data was
queried read-only; integration fixtures used separate databases.

Local logs are ignored working artifacts:
`tmp/implementation-tests-20261001.txt` and `tmp/health-sql-tests-20261001.txt`.

## Health snapshot

The snapshot at **08:46:22** (01:46:22 UTC) included all nine configured sources.
JSON/Markdown files are under
`data/state/reports/data_health/20261001T014622401332Z-be0d84ca.*`; these artifacts
are intentionally not committed. Four initial-policy alerts were observed:

| Source | Metric | Observed | Limit |
| --- | --- | --- | --- |
| CareerLink | Pending fetch | 101 | 100 |
| TopCV | Raw awaiting usable parse | 153 | 100 |
| TopCV | Hours since completed detail | 72.55 | 48 |
| TopCV | Hours since completed parse | 93.38 | 48 |

The offline gate returned 1 as expected. Freshness measures completed phase
history, not whether a suspicious phase recently ran. Backlog includes expired
jobs under the current report definition. These findings were reported, not
automatically repaired or recrawled.

## Not established by this run

- GitHub-hosted CI success: the workflow was added locally, not run on GitHub.
- Docker build/import or Airflow activation: Docker was unavailable in the session.
- Remote Supabase schema, frontend behavior, browser access or MinIO integrity.
- External notification delivery, automatic ingestion/sync or scheduled restore drills.

The subsequent docs review updated current contracts and archived old handoffs.
See [runbook](../operations/runbook.md) for operational limits and
[testing](../development/testing.md) for rerun instructions.
