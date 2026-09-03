#!/usr/bin/env python3
"""Print a read-only inventory of JobLake PostgreSQL objects and sizes."""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Iterable
from typing import Any

import psycopg
from dotenv import load_dotenv


APP_SCHEMAS = ("core", "ref", "public")


def print_rows(title: str, cursor: psycopg.Cursor[Any]) -> None:
    columns = [column.name for column in cursor.description or ()]
    rows = [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]
    print(f"\n{title}")
    print(json.dumps(rows, default=str, ensure_ascii=False, indent=2))


def execute(cursor: psycopg.Cursor[Any], title: str, sql: str) -> None:
    cursor.execute(sql, (list(APP_SCHEMAS),))
    print_rows(title, cursor)


def main() -> int:
    load_dotenv()
    database_url = os.environ.get("LOCAL_DATABASE_URL")
    if not database_url:
        print(
            "FAIL: LOCAL_DATABASE_URL is not set. Add it to your untracked .env file.",
            file=sys.stderr,
        )
        return 2

    try:
        with psycopg.connect(database_url, connect_timeout=10) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT current_database() AS database_name,
                           current_user AS current_role,
                           version() AS server_version,
                           pg_size_pretty(pg_database_size(current_database()))
                               AS database_size
                    """
                )
                print_rows("Database", cursor)
                execute(
                    cursor,
                    "Tables and approximate sizes",
                    """
                    SELECT n.nspname AS schema_name,
                           c.relname AS table_name,
                           c.reltuples::bigint AS approximate_rows,
                           pg_size_pretty(pg_total_relation_size(c.oid)) AS total_size,
                           pg_get_userbyid(c.relowner) AS owner
                    FROM pg_class c
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE c.relkind IN ('r', 'p') AND n.nspname = ANY(%s)
                    ORDER BY n.nspname, c.relname
                    """,
                )
                execute(
                    cursor,
                    "Columns, defaults, identity, and generated columns",
                    """
                    SELECT table_schema, table_name, ordinal_position, column_name,
                           data_type, udt_schema, udt_name, is_nullable,
                           column_default, is_identity, identity_generation,
                           is_generated, generation_expression
                    FROM information_schema.columns
                    WHERE table_schema = ANY(%s)
                    ORDER BY table_schema, table_name, ordinal_position
                    """,
                )
                execute(
                    cursor,
                    "Constraints (primary, unique, foreign-key, and check)",
                    """
                    SELECT n.nspname AS schema_name, c.relname AS table_name,
                           con.conname AS constraint_name, con.contype AS constraint_type,
                           pg_get_constraintdef(con.oid, true) AS definition
                    FROM pg_constraint con
                    JOIN pg_class c ON c.oid = con.conrelid
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE n.nspname = ANY(%s)
                    ORDER BY n.nspname, c.relname, con.conname
                    """,
                )
                execute(
                    cursor,
                    "Indexes",
                    """
                    SELECT schemaname AS schema_name, tablename AS table_name,
                           indexname AS index_name, indexdef
                    FROM pg_indexes
                    WHERE schemaname = ANY(%s)
                    ORDER BY schemaname, tablename, indexname
                    """,
                )
                execute(
                    cursor,
                    "Sequences and identity state",
                    """
                    SELECT schemaname AS schema_name, sequencename AS sequence_name,
                           start_value, increment_by, min_value, max_value,
                           cache_size, last_value
                    FROM pg_sequences
                    WHERE schemaname = ANY(%s)
                    ORDER BY schemaname, sequencename
                    """,
                )
                execute(
                    cursor,
                    "Triggers",
                    """
                    SELECT n.nspname AS schema_name, c.relname AS table_name,
                           tg.tgname AS trigger_name,
                           pg_get_triggerdef(tg.oid, true) AS definition
                    FROM pg_trigger tg
                    JOIN pg_class c ON c.oid = tg.tgrelid
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE NOT tg.tgisinternal AND n.nspname = ANY(%s)
                    ORDER BY n.nspname, c.relname, tg.tgname
                    """,
                )
                execute(
                    cursor,
                    "Application functions",
                    """
                    SELECT n.nspname AS schema_name, p.proname AS function_name,
                           pg_get_function_identity_arguments(p.oid) AS arguments,
                           pg_get_userbyid(p.proowner) AS owner
                    FROM pg_proc p
                    JOIN pg_namespace n ON n.oid = p.pronamespace
                    WHERE n.nspname = ANY(%s)
                    ORDER BY n.nspname, p.proname
                    """,
                )
                cursor.execute(
                    """
                    SELECT extname AS extension, extversion,
                           n.nspname AS schema_name
                    FROM pg_extension e
                    JOIN pg_namespace n ON n.oid = e.extnamespace
                    ORDER BY extname
                    """
                )
                print_rows("Installed extensions", cursor)
    except psycopg.Error as exc:
        print(f"FAIL: local database inspection failed: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
