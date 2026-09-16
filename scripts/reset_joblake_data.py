"""Explicit data-only reset. Stop all crawlers first; schemas/lifecycle are kept.

Run audit_retention.py first. This deletes JobLake local AND Supabase rows and
raw/detail objects. SQLite and Airflow history must be reset separately before
starting a fresh ingestion. There is no transaction across the three services.
"""
import argparse
import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from minio.deleteobjects import DeleteObject
from urllib3 import PoolManager, Timeout

from joblake.config import load_config
from joblake.postgres import PostgresSettings
from joblake.storage import MinioRawStorage
from joblake.supabase_verify import app_tables


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply-local-and-supabase", action="store_true", required=True)
    parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    load_dotenv(root / ".env", override=False)
    config = load_config(str(root / "configs/itviec.yaml"))
    config["storage"]["ensure_bucket"] = False
    storage = MinioRawStorage.from_config(config)
    if storage.bucket_name != "joblake" or storage.prefix != "raw":
        raise ValueError("Unexpected storage scope")
    storage.client._http = PoolManager(timeout=Timeout(connect=5, read=30), retries=False)
    expected = {("core", "job_parse_results"), ("core", "source_job_postings"), ("ref", "sources")}
    local = psycopg.connect(**PostgresSettings.from_config(config).connection_kwargs())
    remote = psycopg.connect(os.environ["SUPABASE_DATABASE_URL"], connect_timeout=10)
    try:
        for label, connection in (("local", local), ("supabase", remote)):
            connection.execute("SET LOCAL lock_timeout = '10s'")
            connection.execute("SET LOCAL statement_timeout = '30s'")
            if set(app_tables(connection)) != expected:
                raise ValueError(f"Unexpected tables in {label}")
            connection.execute("LOCK TABLE ref.sources, core.source_job_postings, core.job_parse_results IN ACCESS EXCLUSIVE MODE")
            triggers = connection.execute("SELECT 1 FROM pg_trigger WHERE tgrelid IN ('ref.sources'::regclass,'core.source_job_postings'::regclass,'core.job_parse_results'::regclass) AND NOT tgisinternal LIMIT 1").fetchone()
            if triggers:
                raise ValueError(f"Unexpected trigger in {label}")
        for label, connection in (("supabase", remote), ("local", local)):
            # No CASCADE: external foreign keys cause failure, not wider deletion.
            connection.execute("TRUNCATE TABLE core.job_parse_results, core.source_job_postings, ref.sources RESTART IDENTITY")
            connection.commit()
            print(f"Cleared {label}: exactly three JobLake tables; schema retained", flush=True)
        count = 0
        def objects():
            nonlocal count
            for obj in storage.client.list_objects("joblake", prefix="raw/detail/", recursive=True, include_version=True):
                count += 1
                yield DeleteObject(obj.object_name, version_id=obj.version_id)
        errors = list(storage.client.remove_objects("joblake", objects()))
        if errors:
            raise RuntimeError(f"{len(errors)} object deletion failures")
        remaining = next(storage.client.list_objects("joblake", prefix="raw/detail/", recursive=True, include_version=True), None)
        if remaining is not None:
            raise RuntimeError("Objects remain after reset")
        print(f"Deleted {count} raw/detail objects; bucket and lifecycle retained", flush=True)
    finally:
        local.close()
        remote.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"RESET INCOMPLETE: {type(exc).__name__}; inspect each store before retrying", flush=True)
        raise SystemExit(1)
