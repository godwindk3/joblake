# JobLake

Collect job listings from ITviec, TopCV, TopDev and VietnamWorks. Raw HTML lives in MinIO; crawl state and parsed records live in PostgreSQL.

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
