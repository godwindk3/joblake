# JobLake

Collect job listings from ITviec, TopCV, TopDev, VietnamWorks, Devwork, CareerViet, Vieclam24h, CareerLink and JobsGO. Raw HTML lives in MinIO; crawl state and parsed records live in PostgreSQL.

## Live demo

**[Explore JobLake — joblake-web.vercel.app](https://joblake-web.vercel.app)**

The public job-search website uses data collected and processed by the JobLake pipeline. Search listings, filter by source and province/city, view job details, and explore job statistics.

[Try searching for `data enginee`](https://joblake-web.vercel.app/?q=data+enginee): the last word supports prefix matching from three normalized characters. The website source is maintained in a separate private repository.

## Start here

Follow [local setup](docs/setup/local.md), then run from the repository root:

```powershell
python -m joblake.main --config configs/topdev.yaml --phase full
python -m joblake.main --config configs/topdev.yaml --phase parse
```

`full` runs discovery and detail. Parsing is a separate restartable step.
All nine sources currently use PostgreSQL crawl state and MinIO raw storage.
Optional AI enrichment and active-job sync to Supabase are independent manual phases.

After ingestion, generate and check data health:

```powershell
python -m joblake.data_health
python -m joblake.health_policy
```

The report is saved before quality is evaluated by the separate Airflow gate.
Health thresholds are configurable per source in `configs/data_health.yaml`.
See the [operational runbook](docs/operations/runbook.md) for publishing and recovery.

## Documentation

- [Documentation index](docs/README.md)
- [Current architecture](docs/architecture/overview.md)
- [Airflow setup](docs/setup/airflow.md)
- [Devwork source and validation](docs/operations/devwork.md)
- [CareerViet source and validation](docs/operations/careerviet.md)
- [Vieclam24h source and validation](docs/operations/vieclam24h.md)
- [CareerLink source and validation](docs/operations/careerlink.md)
- [JobsGO source and validation](docs/operations/jobsgo.md)
- [Development, tests and CI](docs/development/testing.md)
- [Data health and alerts](docs/operations/data-health.md)
- [Website search/filter contract](docs/development/serving-contract.md)
- [Active-job serving sync](docs/operations/supabase-cli.md)
- [Optional AI enrichment](docs/operations/enrichment.md)
- [Maintenance scripts](scripts/README.md)

## Repository

| Directory | Purpose |
| --- | --- |
| src/joblake/ | Application, source adapters and parsers |
| configs/ | Source YAML configuration |
| migrations/ | Local PostgreSQL Alembic migrations |
| supabase/migrations/ | Additive serving migrations; not a complete bootstrap |
| .github/workflows/ | Unit, PostgreSQL integration and Airflow image CI |
| orchestration/airflow/ | Airflow image, Compose and DAGs |
| scripts/ | Operational utilities |
| tests/ | Automated tests and manual checks |
| docs/ | Setup, architecture, development, operation and history |

Local data/, output/, tmp/, environments and logs are ignored by Git.
