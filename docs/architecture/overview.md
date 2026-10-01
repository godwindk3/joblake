# Current architecture

JobLake collects nine configured sources: ITviec, TopCV, TopDev, VietnamWorks,
Devwork, CareerViet, Vieclam24h, CareerLink and JobsGO. Each has a source adapter,
YAML configuration and parser. The public website is maintained in a separate repo.

```text
Source listings -> discovery -> PostgreSQL crawl_state (URL presence / CDC)
                                    |
                                 detail -> MinIO raw HTML
                                              |
                                            parse
                                              |
                              PostgreSQL ref + core (versioned results)
                                  |                    |
                          optional enrichment          |
                                  |                    |
                                  +---- manual sync ---+
                                              |
                                 Supabase serving.sources/jobs
                                              |
                               Search RPC v1/v2 -> joblake-web

Local PostgreSQL -> data health snapshot -> independent quality check
```

## Execution and ownership

- `full` runs discovery and detail only; parse is a separate restartable phase.
- All current source configs use PostgreSQL state and MinIO raw storage. SQLite
  and file state remain legacy backends, not fallback storage for a failed DB.
- Discovery finalizes URL CDC only after confirmed complete listing coverage.
  Active/expired means observed/absent in that scope, not a verified deadline.
- Parsed output is versioned by raw hash and parser version. Accepted and partial
  results are usable; rejected output stays in parse-attempt diagnostics.
- Optional enrichment has its own persistent queue, quotas and evidence checks.
  It is not required to crawl, parse, publish or search jobs.
- Sync takes a consistent local snapshot and atomically reconciles compact active
  jobs remotely. Raw objects, crawl state and parse history remain local.

## Orchestration

There are 13 DAGs: nine source DAGs, manual sync, optional manual enrichment,
daily health at 07:00 and daily raw cleanup at 15:00, Asia/Ho_Chi_Minh. Scheduled
maintenance DAGs start paused; unpause to activate their schedules. Cleanup
defaults to dry-run. Source DAGs and sync have no automatic schedule or dependency
between them. Airflow uses LocalExecutor and a shared three-slot pool.

Source phases run sequentially with `detail`/`parse` using `all_done`; a watcher
keeps failed phases visible in the final DAG status. `suspicious` remains exit 0.
The health DAG saves a report before its independent `check_quality` task flags
threshold violations. No external notification delivery is configured.

See [Airflow operation](../operations/airflow-sources.md),
[health checks](../operations/data-health.md) and the [runbook](../operations/runbook.md).

## Implementation authority

| Concern | Source |
| --- | --- |
| Parsed dataclasses and quality validation | `src/joblake/parsing/models.py`, `parsing/validation.py` |
| Local schema history | `migrations/versions/` (Alembic) |
| State, recovery and source locks | `src/joblake/postgres_state.py` |
| Enrichment contract and projection | `src/joblake/enrichment/` |
| Serving schema and synchronization | `src/joblake/supabase_sync.py`, `supabase_serving_setup.py` |
| Search functions | `src/joblake/sql/serving_search_*.sql` |
| Health budgets | `configs/data_health.yaml`, `src/joblake/health_policy.py` |
| Automated verification | `.github/workflows/ci.yml` |

See [storage and state](storage-state.md), [location cities](location-cities.md),
[URL CDC](../operations/url-cdc.md) and [website contract](../development/serving-contract.md).
