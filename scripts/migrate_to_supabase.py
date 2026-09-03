#!/usr/bin/env python3
"""Safely migrate the JobLake application schemas with pg_dump/pg_restore.

Only ``core`` and ``ref`` are included.  The utility deliberately does not use
``--clean`` and refuses to run if either destination schema already exists.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import psycopg
from dotenv import load_dotenv


DEFAULT_SCHEMAS = ("ref", "core")


def require_environment(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ValueError(f"{name} is not set. Add it to your untracked .env file.")
    return value


def find_postgres_tool(name: str) -> str:
    env_name = f"{name.upper()}_BIN"
    configured = os.environ.get(env_name)
    if configured:
        return configured
    found = shutil.which(name)
    if found:
        return found
    if os.name == "nt":
        candidates = sorted(Path("C:/Program Files/PostgreSQL").glob(f"*/bin/{name}.exe"))
        if candidates:
            return str(candidates[-1])
    raise FileNotFoundError(
        f"Could not find {name}. Put it on PATH or set {env_name} to its full path."
    )


def assert_empty_destination_schemas(database_url: str, schemas: tuple[str, ...]) -> None:
    with psycopg.connect(database_url, connect_timeout=10) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT schema_name
                FROM information_schema.schemata
                WHERE schema_name = ANY(%s)
                ORDER BY schema_name
                """,
                (list(schemas),),
            )
            existing = [row[0] for row in cursor.fetchall()]
    if existing:
        joined = ", ".join(existing)
        raise RuntimeError(
            f"Refusing to restore because destination schema(s) already exist: {joined}. "
            "Use a newly created Supabase project or clean only these schemas manually "
            "after verifying they contain no required data."
        )


def run(command: list[str]) -> None:
    print("Running:", " ".join(command[:1] + ["<connection URLs redacted>"]))
    subprocess.run(command, check=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--schema",
        action="append",
        dest="schemas",
        help="Application schema to include; repeatable (default: ref and core).",
    )
    parser.add_argument(
        "--keep-dump",
        action="store_true",
        help="Keep the temporary custom-format dump and print its path.",
    )
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="Check configuration and an empty destination without changing either database.",
    )
    return parser.parse_args()


def main() -> int:
    load_dotenv()
    args = parse_args()
    schemas = tuple(args.schemas or DEFAULT_SCHEMAS)
    if not schemas or any(not schema.replace("_", "a").isalnum() for schema in schemas):
        print("FAIL: schema names must contain only letters, digits, and underscores.", file=sys.stderr)
        return 2

    try:
        local_url = require_environment("LOCAL_DATABASE_URL")
        supabase_url = require_environment("SUPABASE_DATABASE_URL")
        assert_empty_destination_schemas(supabase_url, schemas)
        pg_dump = find_postgres_tool("pg_dump")
        pg_restore = find_postgres_tool("pg_restore")
        if args.preflight_only:
            print("SUCCESS: preflight passed; destination application schemas do not exist.")
            return 0

        with tempfile.NamedTemporaryFile(
            prefix="joblake-supabase-", suffix=".dump", delete=False
        ) as dump_file:
            dump_path = Path(dump_file.name)
        try:
            dump_command = [
                pg_dump,
                f"--dbname={local_url}",
                "--format=custom",
                "--no-owner",
                "--no-privileges",
                "--verbose",
                f"--file={dump_path}",
                *[f"--schema={schema}" for schema in schemas],
            ]
            restore_command = [
                pg_restore,
                f"--dbname={supabase_url}",
                "--no-owner",
                "--no-privileges",
                "--single-transaction",
                "--exit-on-error",
                "--verbose",
                str(dump_path),
            ]
            print(f"Dumping only application schemas: {', '.join(schemas)}")
            run(dump_command)
            print("Restoring without ownership, privileges, or destructive cleanup.")
            run(restore_command)
        finally:
            if args.keep_dump:
                print(f"Temporary dump retained at: {dump_path}")
            elif 'dump_path' in locals() and dump_path.exists():
                dump_path.unlink()
        print("SUCCESS: restore completed. Run verify_supabase_migration.py next.")
        return 0
    except (OSError, RuntimeError, ValueError, psycopg.Error, subprocess.CalledProcessError) as exc:
        print(f"FAIL: migration did not complete: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
