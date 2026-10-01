# Historical documents

These dated reports preserve implementation decisions and evidence. They are not
current setup instructions, runtime counts or deployment status. Use the
[current documentation](../README.md) and [runbook](../operations/runbook.md).

## Validation and audits

- [Health and CI verification — 2026-10-01](verification-2026-10-01.md)
- [Project audit — 2026-09-29](project-audit-2026-09-29.md)
- [CDC validation — 2026-09-13](cdc-validation-2026-09-13.md)
- [PostgreSQL cutover — 2026-09-12](postgres-cutover-2026-09-12.md)
- [Data reset and retention — 2026-09-08](data-reset-and-retention-2026-09-08.md)
- [Airflow validation — 2026-09-07](airflow-validation-2026-09-07.md)
- [Storage audit — 2026-09-07](storage-audit-2026-09-07.md)

## Earlier website handoffs

- [Search prefix rollout — 2026-09-22](search-prefix-2026-09-22.md), with
  [before](search-prefix-before.json), [after](search-prefix-after.json) and
  [reader smoke](search-prefix-smoke.json) measurements.
- [Enrichment and v2 filters — 2026-09-26/27](web-enrichment-2026-09-27.md).
- [Legacy full-replica migration](supabase-full-replica-migration.md).

The current API lives in the [serving contract](../development/serving-contract.md).
Old deployment statements and test counts remain historical evidence.

## Earlier design work

- [Initial Airflow plan](airflow-plan.md)
- [Architecture review — 2026-08](architecture-review-2026-08.md)
- [Canonical field proposal](canonical-fields-v1.md)

The obsolete ASCII architecture proposal was removed during the 2026-10-01 docs
cleanup. The [implemented architecture](../architecture/overview.md) supersedes
its unimplemented Scrapy/Pandas/Pydantic/Elasticsearch/Kibana design.
