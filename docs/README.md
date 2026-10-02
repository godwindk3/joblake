# JobLake documentation

Current documentation describes the checked-in implementation. Live database,
website and Airflow state must be verified separately. Run commands from the
repository root unless a page says otherwise.

## Start and understand the system

- [Local setup](setup/local.md): Python, dependencies, credentials and first run.
- [PostgreSQL setup](setup/postgres.md): business schemas and migrations.
- [Airflow setup](setup/airflow.md): Docker runtime and mounted configuration.
- [Architecture](architecture/overview.md): ingestion, enrichment, serving and monitoring.
- [Storage and state](architecture/storage-state.md): claims, recovery and parse history.
- [Location normalization](architecture/location-cities.md): cities and backfill.

## Operate the pipeline

- [Daily runbook](operations/runbook.md): crawl, inspect health, sync and recover.
- [Source DAGs](operations/airflow-sources.md): all nine sources, transports, limits and retries.
- Source-specific notes: [Devwork](operations/devwork.md), [CareerViet](operations/careerviet.md),
  [Vieclam24h](operations/vieclam24h.md), [CareerLink](operations/careerlink.md), [JobsGO](operations/jobsgo.md).
- [Data health and alerts](operations/data-health.md): budgets, reports and quality gate.
- [URL CDC](operations/url-cdc.md): listing presence, expiry and coverage requirements.
- [Serving sync](operations/supabase-cli.md): compact active-job export to Supabase.
- [AI enrichment](operations/enrichment.md): eligibility, evidence, quotas and retries.
- [Raw cleanup](operations/raw-cleanup.md), [log retention](operations/log-retention.md),
  [browser diagnostics](operations/diagnostics-and-storage.md).
- [PostgreSQL state and legacy cutover](operations/postgres-state-migration.md).
- [Maintenance script inventory](../scripts/README.md).

## Develop and integrate

- [Adding a source](development/adding-source.md): adapter, parser, fixtures and registration.
- [Testing and CI](development/testing.md): unit, disposable SQL databases and Airflow image checks.
- [Website serving contract](development/serving-contract.md): search v1/v2, filters, dates and enrichment UI.
- [Skills and filtered insights plan](development/skills-and-insights-plan.md): proposed cross-repository roadmap; not yet implemented.

## Historical evidence

[Archive](archive/README.md) contains dated audits, validation results, previous
handoffs and migration procedures. It is not the setup guide or the current API
contract. The [2026-10-01 verification](archive/verification-2026-10-01.md) records
the health/CI implementation checks and their remaining limits.
