# Local setup

Use Python 3.11+ and Docker Desktop with Linux containers. Run commands from the repository root. The dependency snapshot comes from the existing Python 3.12 environment; validate installation on other Python versions.

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

## Logging

Logs go to stderr with UTC timestamps. Add --log-level DEBUG for details. --strict returns nonzero for blocked or failed ingestion; suspicious results remain successful. See [log retention](../operations/log-retention.md).
