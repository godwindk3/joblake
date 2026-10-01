# PostgreSQL setup

Local PostgreSQL is authoritative for crawl/parse state and normalized data.
MinIO stores raw HTML. The Airflow stack has its own metadata database; Supabase
receives only the compact website-serving projection.

## Configure and start

Copy `.env.example` to `.env` if needed and supply your own credentials:

```dotenv
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=joblake
POSTGRES_USER=joblake
POSTGRES_PASSWORD=replace-with-a-long-random-password
```

Keep `LOCAL_DATABASE_URL` consistent with these settings; sync utilities prefer
that URL, while crawler state, parsing and Alembic use `POSTGRES_*` settings.
Never commit `.env`. From the root with the Python environment active:

```powershell
python -m pip install -r requirements.txt
docker compose up -d postgres
docker compose ps postgres
docker compose exec postgres pg_isready -U joblake -d joblake
python -m alembic upgrade head
python -m alembic current
```

Replace the example user/database names in `pg_isready` if customized. The core
Compose stack uses the `postgres_data` volume. Stopping containers preserves it;
volume reset commands do not. Airflow's separate network uses the host-published
database port through `host.docker.internal`, not the core service name.

## Schema ownership

| Schema | Purpose |
| --- | --- |
| `crawl_state` | Runs, discovery targets, URL state, fetch/raw/parse history, CDC and purge journal |
| `ref` | Source catalog |
| `core` | Source postings, versioned parse results, enrichment queue/results/quota ledger |
| `public.alembic_version` | Local migration revision |

The current Alembic head is `62e1356fadde` (enrichment), following
`0005_raw_cleanup`. Apply the entire chain on a new database. Airflow does not
automatically migrate these business schemas. Supabase SQL migrations are a
separate history and do not initialize local PostgreSQL.

`core.source_job_postings.crawler_job_id` references the PostgreSQL crawl identity.
Each parse result is unique by `(source_posting_id, raw_sha256, parser_name,
parser_version)`. Prior versions remain available; one result per posting is
current. Replaying the same parser/raw input is idempotent.

## Run and inspect

```powershell
python -m joblake.main --config configs/itviec.yaml --phase parse
python scripts/inspect_local_postgres.py
python -m joblake.data_health
python -m joblake.health_policy
```

Parse consumes existing raw metadata from `crawl_state` and content from MinIO;
it never crawls websites. On a fresh empty database the health gate reports
missing inventory/success history; that is not a schema installation failure.

Use [local setup](local.md) for discovery/detail, [state migration](../operations/postgres-state-migration.md)
only for legacy cutovers, and [testing](../development/testing.md) for isolated
integration databases. Do not downgrade operational schemas to clear an error:
CDC, raw cleanup and enrichment history require preservation.
