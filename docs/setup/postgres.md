# PostgreSQL setup

PostgreSQL stores parsed, curated job data. It remains separate from
MinIO (immutable raw HTML) and SQLite (the operational crawl/parse
queue).

## 1. Add PostgreSQL values to `.env`

Do not commit `.env`. Add these values to your existing local file, using
a strong password of your own:

```dotenv
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=joblake
POSTGRES_USER=joblake
POSTGRES_PASSWORD=replace-with-a-long-random-password
```

`.env.example` contains the same non-secret template. Docker Compose
uses `POSTGRES_DB`, `POSTGRES_USER`, and `POSTGRES_PASSWORD` to create
the initial database and login. The parser uses all five values.

## 2. Install parser and migration dependencies

The project declares Psycopg 3, SQLAlchemy, and Alembic. Install them
into the active project environment once:

```powershell
python -m pip install -r requirements.txt
```

## 3. Start and verify PostgreSQL

```powershell
docker compose up -d postgres
docker compose ps postgres
docker compose exec postgres pg_isready -U joblake -d joblake
docker compose exec postgres psql -U joblake -d joblake -c "SELECT version();"
```

If you use different values for `POSTGRES_USER` or `POSTGRES_DB`, replace
`joblake` in the two verification commands.

The database data is persisted in the named Docker volume
`postgres_data`. Stopping or recreating the container does not remove it.
For a future application service inside the same Docker Compose network,
use `POSTGRES_HOST=postgres`; when running Python directly on the host,
keep `POSTGRES_HOST=localhost`.

## 4. Apply the JobLake schema

```powershell
alembic upgrade head
alembic current
```

The first migration creates these tables:

- `ref.sources`: one source website per code.
- `core.source_job_postings`: one canonical URL per source, linked to
  the SQLite crawler job ID.
- `core.job_parse_results`: immutable parser output, raw-object
  provenance, quality metadata, and one `is_current` result per posting.

The unique identity of a parse result is `(source_posting_id,
raw_sha256, parser_name, parser_version)`. Re-running the same parser
against the same raw HTML is therefore idempotent. A newly inserted
parser version becomes current; prior result versions remain available
for audit.

## 5. Run and inspect parsing

```powershell
python -m joblake.main --config configs/itviec.yaml --phase parse
docker compose exec postgres psql -U joblake -d joblake -c "SELECT id, canonical_url, first_seen_at, last_seen_at FROM core.source_job_postings ORDER BY id DESC LIMIT 10;"
docker compose exec postgres psql -U joblake -d joblake -c "SELECT id, source_posting_id, parser_name, parser_version, quality_status, completeness_score, is_current FROM core.job_parse_results ORDER BY id DESC LIMIT 10;"
```

The parse command reads raw objects already recorded in SQLite and
stored in MinIO. It does not crawl the job website. SQLite remains the
queue and retry authority; PostgreSQL is the curated output store.
