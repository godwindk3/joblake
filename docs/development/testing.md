# Development and verification

After [local setup](../setup/local.md), run from the repository root:

```powershell
python -m unittest discover -s tests
python -m pip check
python -m joblake.main --help
```

Database integration tests are opt-in. Read their environment requirements and use a dedicated test database. Skipped tests do not verify live storage.

## Continuous integration

`.github/workflows/ci.yml` runs on pushes, pull requests and manual dispatch:

- Unit tests and clean dependency installation on Windows/Linux, Python 3.11/3.12.
- PostgreSQL 16 service with disposable credentials, full Alembic upgrade, CDC,
  serving/search and enrichment integration tests, and real data-health queries.
- Build the production Airflow Dockerfile and import/check all DAGs in that image.

The PostgreSQL job needs no repository secrets and never connects to Supabase.
Tests create uniquely named temporary databases and remove them afterward.
`scripts/run_ci_tests.py` requires all integration flags and fails if any test
is skipped or no tests are discovered. Unit-only jobs intentionally skip SQL tests.

To run the integration gate locally, first configure PostgreSQL environment
variables and `LOCAL_DATABASE_URL` for a test server with `CREATEDB` permission:

```powershell
$env:JOBLAKE_TEST_POSTGRES = '1'
$env:JOBLAKE_TEST_SERVING = '1'
$env:JOBLAKE_TEST_ENRICHMENT = '1'
python scripts/run_ci_tests.py
```

The CI migration command targets only the disposable CI database; do not copy
that command into an operational environment without checking its target.

Service-container setup follows the [GitHub Actions PostgreSQL guide](https://docs.github.com/en/actions/tutorials/use-containerized-services/create-postgresql-service-containers).

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

The Compose command above requires a running Airflow container. CI instead starts
a disposable container from the built image and runs the same script without
executing ingestion tasks. Unit tests use stubs and do not replace real image
build/import verification.

## Verification records

Keep test counts and live smoke results in dated reports rather than treating them
as permanent guarantees. The [2026-10-01 record](../archive/verification-2026-10-01.md)
separates the successful local SQL suite/migration test from pending GitHub/Docker
verification. Documentation-only changes can be checked with local-link validation
and code/config comparison; they do not require rerunning live crawls.
