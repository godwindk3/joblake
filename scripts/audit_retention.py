"""Read-only inventory of JobLake storage and retention (no credentials printed)."""
import json
import os
import sqlite3
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from minio.xml import marshal
from minio.error import S3Error
from urllib3 import PoolManager, Timeout

from joblake.config import load_config
from joblake.postgres import PostgresSettings
from joblake.storage import MinioRawStorage
from joblake.supabase_verify import app_tables


ROOT = Path(__file__).resolve().parents[1]


def main():
    load_dotenv(ROOT / ".env", override=False)
    config = load_config(str(ROOT / "configs/itviec.yaml"))
    config["storage"]["ensure_bucket"] = False
    storage = MinioRawStorage.from_config(config)
    storage.client._http = PoolManager(timeout=Timeout(connect=5, read=15), retries=False)
    result = {}
    bucket = storage.bucket_name
    result["minio_bucket"] = bucket
    result["versioning"] = marshal(storage.client.get_bucket_versioning(bucket)).decode()
    try:
        result["lifecycle"] = marshal(storage.client.get_bucket_lifecycle(bucket)).decode()
    except S3Error as exc:
        if exc.code != "NoSuchLifecycleConfiguration":
            raise
        result["lifecycle"] = None
    counts = {}
    versions = 0
    total_bytes = 0
    for obj in storage.client.list_objects(bucket, recursive=True, include_version=True):
        versions += 1
        total_bytes += obj.size or 0
        prefix = "/".join(obj.object_name.split("/")[:3])
        counts[prefix] = counts.get(prefix, 0) + 1
    result["minio"] = dict(versions=versions, bytes=total_bytes, prefixes=counts)
    print(json.dumps(result, ensure_ascii=False), flush=True)
    for name, settings in (
        ("local", PostgresSettings.from_config(config).connection_kwargs()),
        ("supabase", {"conninfo": os.environ["SUPABASE_DATABASE_URL"], "connect_timeout": 10}),
    ):
        with psycopg.connect(**settings) as connection:
            connection.execute("SET TRANSACTION READ ONLY")
            connection.execute("SET LOCAL statement_timeout = '20s'")
            tables = app_tables(connection)
            counts = {f"{s}.{t}": connection.execute(
                psycopg.sql.SQL("SELECT count(*) FROM {}").format(psycopg.sql.Identifier(s, t))
            ).fetchone()[0] for s, t in tables}
            triggers = connection.execute("SELECT event_object_schema,event_object_table,trigger_name FROM information_schema.triggers WHERE event_object_schema IN ('core','ref')").fetchall()
            result = {"database": name, "tables": counts, "triggers": triggers}
            print(json.dumps(result), flush=True)
    path = ROOT / config["state"]["database_path"]
    if not path.exists():
        print(json.dumps({"sqlite": "absent; fresh ingestion will initialize it"}), flush=True)
        return
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as connection:
        counts = {table: connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                  for table in ("jobs", "crawl_runs", "fetch_attempts", "raw_objects", "parse_attempts")}
        print(json.dumps({"sqlite": counts}), flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Audit failed: {type(exc).__name__}", flush=True)
        raise SystemExit(1)
