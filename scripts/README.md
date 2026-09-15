# Maintenance scripts

Run from the repository root after installing the project. Scripts retain their paths because some resolve configuration relative to this directory and tests import them directly.

| Tool | Purpose |
| --- | --- |
| docker.ps1 | Manage both stacks; reset removes volumes |
| airflow.ps1 | Build, initialize and manage Airflow |
| audit_retention.py | Inspect retention and raw-object state |
| cdc_report.py | Report URL changes |
| inspect_local_postgres.py | Read-only database inventory |
| migrate_state_to_postgres.py | Offline state migration and verification |
| reset_joblake_data.py | Destructive data reset |
| migrate_to_supabase.py | Remote migration wrapper |
| test_supabase_connection.py | Remote connectivity check |
| verify_supabase_migration.py | Remote migration verification |
| supabase_location_cities.sql | Location field rollout |
| freeze_constraints.py | Snapshot installed runtime dependencies |

Review tool options before write operations. Recovery scripts are not part of ordinary setup.
