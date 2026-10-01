# Local setup

Use Python 3.11+ and Docker Desktop with Linux containers. Run commands from the
repository root. Python 3.12 is the local reference environment; the CI matrix
targets Python 3.11/3.12 on Windows/Linux. A configured CI job is not evidence
that its latest run passed; see [testing](../development/testing.md).

## Python environment

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m cloakbrowser install
```

On Linux use python3 -m venv .venv and source .venv/bin/activate. Install browser system libraries with python -m playwright install-deps chromium.

pyproject.toml declares direct dependencies. constraints.txt snapshots transitive versions. requirements.txt installs the project in editable mode using those constraints; Docker uses the same entry point.

## Configuration and services

If .env does not exist, copy .env.example to .env. Fill in MinIO credentials and PostgreSQL settings. Keep LOCAL_DATABASE_URL consistent with POSTGRES_* settings. Configure proxies only for sources that need them. Remote connection settings are only needed for remote sync commands.

```powershell
.\scripts\docker.ps1 start core
python -m alembic upgrade head
python -m joblake.main --help
python -m unittest discover -s tests
```

See [PostgreSQL schema setup](postgres.md) and [optional Airflow setup](airflow.md). Airflow does not migrate JobLake business schemas automatically.

## First run and health

```powershell
python -m joblake.main --config configs/topdev.yaml --phase full --strict
python -m joblake.main --config configs/topdev.yaml --phase parse --strict
python -m joblake.data_health
python -m joblake.health_policy
```

`full` omits parse. Source YAML controls scope and batch sizes; review it before
a first live run. Health checks cover all configured sources, so sources not yet
initialized will alert. See [runbook](../operations/runbook.md) for subsequent
enrichment and remote sync. Shared `data_health.yaml` and `enrichment.yaml` are
not source configs and must not be passed as ingestion `--config`.

If a copied `.venv` launcher points to a missing Python installation, create a
fresh environment with the installed interpreter and reinstall requirements.
Do not assume a copied environment is a reproducible installation.

## Logging

Logs go to stderr with UTC timestamps. Add --log-level DEBUG for details. --strict returns nonzero for blocked or failed ingestion; suspicious results remain successful. See [log retention](../operations/log-retention.md).
