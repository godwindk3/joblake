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

## Documentation

- [Documentation index](docs/README.md)
- [Current architecture](docs/architecture/overview.md)
- [Airflow setup](docs/setup/airflow.md)
- [Devwork source and validation](docs/operations/devwork.md)
- [CareerViet source and validation](docs/operations/careerviet.md)
- [Vieclam24h source and validation](docs/operations/vieclam24h.md)
- [CareerLink source and validation](docs/operations/careerlink.md)
- [JobsGO source and validation](docs/operations/jobsgo.md)
- [Development and tests](docs/development/testing.md)
- [Maintenance scripts](scripts/README.md)

## Repository

| Directory | Purpose |
| --- | --- |
| src/joblake/ | Application, source adapters and parsers |
| configs/ | Source YAML configuration |
| migrations/ | Versioned database migrations |
| orchestration/airflow/ | Airflow image, Compose and DAGs |
| scripts/ | Operational utilities |
| tests/ | Automated tests and manual checks |
| docs/ | Setup, architecture, development, operation and history |

Local data/, output/, tmp/, environments and logs are ignored by Git.
