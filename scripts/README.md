# Maintenance scripts

Run from the repository root after installing the project. Paths are stable:
some tools resolve config relative to the repo and tests import them directly.
Review options before applying writes. Legacy/reset tools are not normal setup.

| Tool | Purpose and side effects |
| --- | --- |
| `docker.ps1` | Manage core/Airflow stacks; reset removes selected volumes |
| `airflow.ps1` | Build, initialize and manage Airflow |
| `run_ci_tests.py` | All tests with integration opt-ins; fail on skips; creates/drops uniquely named test databases |
| `freeze_constraints.py` | Write installed dependency snapshot to constraints.txt |
| `inspect_local_postgres.py` | Read-only local database inventory |
| `audit_web_data.py` | Read-only local schema/data audit; writes `tmp/web-data-audit.json` |
| `audit_retention.py` | Inspect retention and raw-object state |
| `cdc_report.py` | Read-only URL presence/change report |
| `verify_enrichment_install.py` | Read local/remote enrichment schema, cutoff and RLS; no model calls |
| `check_enrichment_providers.py` | Synthetic JD smoke; consumes at most one request per enabled provider with a key, outside persistent quota ledger |
| `benchmark_search_prefix.py` | Read-only query-plan benchmark, local/remote options; writes measurements |
| `verify_search_prefix.py` | Read-only prefix/reader smoke checks; writes a report |
| `test_supabase_connection.py` | Read-only remote PostgreSQL connectivity check |
| `verify_supabase_migration.py` | Verify compact serving replica; uses temporary staging and locks |
| `migrate_to_supabase.py` | Legacy full-replica migration; refuses a serving deployment |
| `supabase_location_cities.sql` | Legacy core-replica location rollout, not current serving setup |
| `migrate_state_to_postgres.py` | Legacy SQLite snapshot/import/verification; import writes to empty target |
| `reset_joblake_data.py` | Destructive reset; inspect scope and backups before use |

Ordinary operations use modules: `python -m joblake.main --help`,
`python -m joblake.data_health --help`, `python -m joblake.health_policy --help`
and `python -m joblake.raw_cleanup --help`. `joblake.log_cleanup` requires Airflow.

See [testing/CI](../docs/development/testing.md), [runbook](../docs/operations/runbook.md),
[health](../docs/operations/data-health.md), [enrichment](../docs/operations/enrichment.md),
[sync](../docs/operations/supabase-cli.md) and [retention](../docs/operations/raw-cleanup.md).
