# Development and verification

After [local setup](../setup/local.md), run from the repository root:

```powershell
python -m unittest discover -s tests
python -m pip check
python -m joblake.main --help
```

Database integration tests are opt-in. Read their environment requirements and use a dedicated test database. Skipped tests do not verify live storage.

The historical DOM probe tests/manual/check_vnw_pagination.cjs runs with Node. It copies a predicate and supplements Python tests; it does not exercise a live website.

## Dependency updates

Update direct versions in pyproject.toml intentionally. Install and test in a clean environment. Install packaging as a maintenance tool and run python scripts/freeze_constraints.py to snapshot the installed closure. Review constraints.txt, then verify a fresh installation on Windows and Linux. This snapshot has no artifact hashes and is not a platform-independent solver lock.

## Docker and DAG validation

```powershell
docker compose config --quiet
docker compose -f orchestration/airflow/compose.yaml config --quiet
.\scripts\airflow.ps1 build
docker compose -f orchestration/airflow/compose.yaml exec airflow-dag-processor python /opt/airflow/check_dag.py
```

The DAG check requires a running Airflow environment. Unit tests use stubs and do not replace a real image build/import.
