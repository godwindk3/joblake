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
