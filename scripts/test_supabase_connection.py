#!/usr/bin/env python3
"""Perform a read-only connectivity check against Supabase PostgreSQL."""

from __future__ import annotations

import os
import sys

import psycopg
from dotenv import load_dotenv


def main() -> int:
    load_dotenv()
    database_url = os.environ.get("SUPABASE_DATABASE_URL")

    if not database_url:
        print(
            "FAIL: SUPABASE_DATABASE_URL is not set. "
            "Add it to your untracked .env file.",
            file=sys.stderr,
        )
        return 2

    try:
        with psycopg.connect(database_url, connect_timeout=10) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT version()")
                version = cursor.fetchone()[0]
                cursor.execute("SELECT current_database(), current_schema()")
                database_name, schema_name = cursor.fetchone()
    except psycopg.Error as exc:
        print(
            "FAIL: could not connect to Supabase PostgreSQL: "
            f"{exc.__class__.__name__}: {exc}",
            file=sys.stderr,
        )
        return 1

    print("SUCCESS: connected to Supabase PostgreSQL (read-only check).")
    print(f"Database: {database_name}")
    print(f"Current schema: {schema_name}")
    print(f"Server: {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
