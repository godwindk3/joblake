"""Offline SQLite state migration. Stop all writers before snapshot/import.

Import refuses nonempty destinations. Verify is read-only. Credentials are never logged.
"""
import argparse
import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

import psycopg
from psycopg import sql
from dotenv import load_dotenv

from joblake.postgres import PostgresSettings

TABLES = ("crawl_runs", "discovery_targets", "jobs", "fetch_attempts", "raw_objects", "parse_attempts")
ROOT = Path(__file__).resolve().parents[1]


def normalize(value, column):
    if value is not None and column.endswith("_at"):
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)  # SQLite CURRENT_TIMESTAMP is UTC.
        return parsed.astimezone(timezone.utc).isoformat()
    return value


def sqlite_open(path):
    return sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)


def check_sqlite(connection):
    if connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
        raise RuntimeError("SQLite integrity check failed")
    if connection.execute("PRAGMA foreign_key_check").fetchall():
        raise RuntimeError("SQLite has invalid foreign keys")


def source_rows(connection, table):
    columns = [r[1] for r in connection.execute(f"PRAGMA table_info({table})")]
    if not columns:
        raise RuntimeError(f"Missing SQLite table: {table}")
    rows = connection.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()
    return columns, [tuple(normalize(v, c) for c, v in zip(columns, row)) for row in rows]


def verify(source, target):
    report = {}
    for table in TABLES:
        columns, expected = source_rows(source, table)
        query = sql.SQL("SELECT {} FROM {} ORDER BY id").format(
            sql.SQL(",").join(map(sql.Identifier, columns)), sql.Identifier("crawl_state", table))
        actual = [tuple(normalize(v, c) for c, v in zip(columns, row))
                  for row in target.execute(query).fetchall()]
        if actual != expected:
            raise RuntimeError(f"Row comparison failed: {table}, source={len(expected)}, target={len(actual)}")
        digest = hashlib.sha256(json.dumps(expected, ensure_ascii=False).encode()).hexdigest()
        report[table] = {"rows": len(expected), "sha256": digest}
    return report


def import_state(source, target):
    # Entire import and verification commit together. No partial resume/overwrite.
    with target.transaction():
        for table in TABLES:
            target.execute(sql.SQL("LOCK TABLE {} IN ACCESS EXCLUSIVE MODE").format(sql.Identifier("crawl_state", table)))
            if target.execute(sql.SQL("SELECT EXISTS (SELECT 1 FROM {})").format(sql.Identifier("crawl_state", table))).fetchone()[0]:
                raise RuntimeError(f"Destination is not empty: {table}")
        for table in TABLES:
            columns, rows = source_rows(source, table)
            query = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
                sql.Identifier("crawl_state", table), sql.SQL(",").join(map(sql.Identifier, columns)),
                sql.SQL(",").join(sql.Placeholder() for _ in columns))
            with target.cursor() as cursor:
                cursor.executemany(query, rows)
        report = verify(source, target)
        for table in TABLES:
            target.execute(sql.SQL("SELECT setval(pg_get_serial_sequence(%s, 'id'), COALESCE(MAX(id), 1), MAX(id) IS NOT NULL) FROM {}").format(sql.Identifier("crawl_state", table)), (f"crawl_state.{table}",))
        return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("snapshot", "import", "verify"))
    parser.add_argument("--sqlite", required=True, type=Path)
    parser.add_argument("--output", type=Path, help="New snapshot file, must not exist")
    args = parser.parse_args()
    load_dotenv(ROOT / ".env", override=False)
    with closing(sqlite_open(args.sqlite)) as source:
        check_sqlite(source)
        if args.mode == "snapshot":
            if args.output is None or args.output.exists():
                raise RuntimeError("Specify a new --output snapshot path")
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with closing(sqlite3.connect(args.output)) as destination:
                source.backup(destination)
                check_sqlite(destination)
            print(json.dumps({"snapshot": str(args.output.resolve())}))
            return
        with psycopg.connect(**PostgresSettings.from_config({}).connection_kwargs()) as target:
            if args.mode == "verify":
                target.execute("SET TRANSACTION READ ONLY")
            report = import_state(source, target) if args.mode == "import" else verify(source, target)
            print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
