# PostgreSQL setup

PostgreSQL is the future database for parsed, curated job data. It is
intentionally separate from MinIO (raw HTML) and the current SQLite
crawler state/queue. This setup creates no application tables yet.

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
the initial database and login. The Python application will later use
all five values when the parse writer is implemented.

## 2. Install the Python PostgreSQL driver

The project declares Psycopg 3 in both dependency manifests. Install it
into the active project environment once:

```powershell
python -m pip install -r requirements.txt
```

No application code connects to PostgreSQL yet, so this only prepares
the dependency for the upcoming parse phase.

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

## Scope of this step

- No PostgreSQL tables, schemas, ORM models, or migrations are created.
- SQLite remains the crawler's operational state database.
- MinIO remains the raw HTML store.

The next implementation step is to decide the parsed-data schema and
then add versioned migrations plus a dedicated parse-to-PostgreSQL
writer.
