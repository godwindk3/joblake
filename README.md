# joblake

Website-specific crawling is implemented through source adapters. See
[Adding a job source](docs/adding-source.md) for the extension workflow.

Raw detail HTML is stored in MinIO, crawl and parse state is stored in
SQLite, and accepted normalized records are stored in PostgreSQL. See
[MinIO raw storage and SQLite state](docs/storage-state.md) for the
runtime flow and [PostgreSQL setup](docs/postgres-setup.md) for schema
migration and querying parsed results.

PostgreSQL is deliberately separate from the SQLite crawler queue. It
is only written after a raw object passes parser validation.

Available source configs:

- `configs/topcv.yaml`
- `configs/itviec.yaml`
- `configs/topdev.yaml`
- `configs/vietnamworks.yaml`

Run a complete source pipeline with:

```powershell
python -m joblake.main --config configs/topdev.yaml
python -m joblake.main --config configs/vietnamworks.yaml
python -m joblake.main --config configs/vietnamworks.yaml --phase detail
python -m joblake.main --config configs/vietnamworks.yaml --phase discovery
python -m joblake.main --config configs/vietnamworks.yaml --phase full
python -m joblake.main --config configs/vietnamworks.yaml --phase parse
```

Before the first parse run, install dependencies and apply the versioned
PostgreSQL schema:

```powershell
python -m pip install -r requirements.txt
alembic upgrade head
```

`full` intentionally remains discovery + detail. Running `parse` is a
separate, restartable step that reads existing raw HTML from MinIO; it
does not contact the source website.

## Airflow source pipelines

The local Airflow environment includes four manual DAGs: `joblake_itviec`,
`joblake_vietnamworks`, `joblake_topdev`, and `joblake_topcv`. Each runs
`discovery -> detail -> parse`. Tasks call the existing CLI with `--strict`,
read the mounted YAML at startup, and share the existing SQLite/MinIO/PostgreSQL
data. Supabase sync remains a separate manual CLI operation covering all sources.

All four share the one-slot `joblake_serial` pool. New DAGs start paused;
unpause and trigger the desired source in the UI. No image rebuild is needed
for DAG or YAML changes.

See [four-source Airflow operation](docs/airflow-sources.md) for configs and
run limits. See [Airflow setup and operation](docs/airflow-itviec.md) for build,
initialization, validation, triggering, and rerun instructions.

See [the Airflow plan](docs/airflow-plan.md) for setup commands, design
decisions, integration boundaries, and the staged adoption roadmap.

Use the project-level management script to control both the JobLake data
services and Airflow with one command:

```powershell
.\scripts\docker.ps1 help
.\scripts\docker.ps1 start
.\scripts\docker.ps1 status
.\scripts\docker.ps1 stop
```

Pass `core` or `airflow` as the second argument to operate on only one
stack, for example `.\scripts\docker.ps1 logs airflow`.
