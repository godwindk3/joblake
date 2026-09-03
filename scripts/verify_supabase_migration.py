#!/usr/bin/env python3
"""Compare JobLake application data in local PostgreSQL and Supabase."""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass
from typing import Any

import psycopg
from dotenv import load_dotenv


APP_SCHEMAS = ("ref", "core")
IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
UNIQUE_KEYS = {
    ("ref", "sources"): ("code",),
    ("core", "source_job_postings"): ("source_id", "canonical_url"),
    ("core", "job_parse_results"): (
        "source_posting_id",
        "raw_sha256",
        "parser_name",
        "parser_version",
    ),
}
IMPORTANT_NULL_COLUMNS = {
    ("ref", "sources"): ("code", "display_name"),
    ("core", "source_job_postings"): ("source_id", "canonical_url", "crawler_job_id"),
    ("core", "job_parse_results"): (
        "source_posting_id",
        "raw_sha256",
        "title",
        "description_text",
        "parsed_at",
    ),
}


@dataclass(frozen=True)
class TableComparison:
    schema: str
    table: str
    local_count: int
    remote_count: int
    local_min_id: int | None
    remote_min_id: int | None
    local_max_id: int | None
    remote_max_id: int | None


def quoted(identifier: str) -> str:
    if not IDENTIFIER.fullmatch(identifier):
        raise ValueError(f"Unsafe database identifier: {identifier!r}")
    return f'"{identifier}"'


def qualified(schema: str, table: str) -> str:
    return f"{quoted(schema)}.{quoted(table)}"


def app_tables(connection: psycopg.Connection[Any]) -> list[tuple[str, str]]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT table_schema, table_name
            FROM information_schema.tables
            WHERE table_type = 'BASE TABLE' AND table_schema = ANY(%s)
            ORDER BY table_schema, table_name
            """,
            (list(APP_SCHEMAS),),
        )
        return [(str(schema), str(table)) for schema, table in cursor.fetchall()]


def row(connection: psycopg.Connection[Any], query: str) -> tuple[Any, ...]:
    with connection.cursor() as cursor:
        cursor.execute(query)
        result = cursor.fetchone()
    if result is None:
        raise RuntimeError("Expected a row from verification query")
    return result


def scalar(connection: psycopg.Connection[Any], query: str) -> Any:
    return row(connection, query)[0]


def compare_table(
    local: psycopg.Connection[Any], remote: psycopg.Connection[Any], schema: str, table: str
) -> TableComparison:
    relation = qualified(schema, table)
    query = f"SELECT count(*), min(id), max(id) FROM {relation}"
    local_count, local_min_id, local_max_id = row(local, query)
    remote_count, remote_min_id, remote_max_id = row(remote, query)
    return TableComparison(
        schema=schema,
        table=table,
        local_count=int(local_count),
        remote_count=int(remote_count),
        local_min_id=local_min_id,
        remote_min_id=remote_min_id,
        local_max_id=local_max_id,
        remote_max_id=remote_max_id,
    )


def null_counts(connection: psycopg.Connection[Any], schema: str, table: str) -> dict[str, int]:
    columns = IMPORTANT_NULL_COLUMNS.get((schema, table), ())
    if not columns:
        return {}
    relation = qualified(schema, table)
    fields = ", ".join(
        f"count(*) FILTER (WHERE {quoted(column)} IS NULL) AS {quoted(column)}"
        for column in columns
    )
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT {fields} FROM {relation}")
        values = cursor.fetchone()
    return dict(zip(columns, values, strict=True))


def duplicate_count(connection: psycopg.Connection[Any], schema: str, table: str) -> int:
    columns = UNIQUE_KEYS.get((schema, table))
    if not columns:
        return 0
    fields = ", ".join(quoted(column) for column in columns)
    relation = qualified(schema, table)
    return int(
        scalar(
            connection,
            f"SELECT count(*) FROM (SELECT {fields} FROM {relation} "
            f"GROUP BY {fields} HAVING count(*) > 1) AS duplicates",
        )
    )


def non_ascii_row_count(
    connection: psycopg.Connection[Any], schema: str, table: str
) -> int:
    relation = qualified(schema, table)
    return int(
        scalar(
            connection,
            f"SELECT count(*) FROM {relation} AS row_data "
            "WHERE to_jsonb(row_data)::text ~ '[^[:ascii:]]'",
        )
    )


def sample_rows(connection: psycopg.Connection[Any], schema: str, table: str) -> list[str]:
    relation = qualified(schema, table)
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT to_jsonb(row_data) FROM {relation} AS row_data "
            "ORDER BY md5(id::text) LIMIT 5"
        )
        return [json.dumps(row[0], sort_keys=True, ensure_ascii=False, default=str) for row in cursor.fetchall()]


def constraint_definitions(
    connection: psycopg.Connection[Any], schema: str, table: str
) -> list[tuple[str, str, str]]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT con.conname, con.contype, pg_get_constraintdef(con.oid, true)
            FROM pg_constraint con
            JOIN pg_class c ON c.oid = con.conrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = %s AND c.relname = %s
            ORDER BY con.conname
            """,
            (schema, table),
        )
        return [(str(name), str(kind), str(definition)) for name, kind, definition in cursor.fetchall()]


def index_definitions(
    connection: psycopg.Connection[Any], schema: str, table: str
) -> list[tuple[str, str]]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT indexname, indexdef
            FROM pg_indexes
            WHERE schemaname = %s AND tablename = %s
            ORDER BY indexname
            """,
            (schema, table),
        )
        return [(str(name), str(definition)) for name, definition in cursor.fetchall()]


def sequence_last_value(
    connection: psycopg.Connection[Any], schema: str, table: str
) -> int | None:
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_get_serial_sequence(%s, 'id')", (f"{schema}.{table}",))
        sequence_name = cursor.fetchone()[0]
        if sequence_name is None:
            return None
        cursor.execute(f"SELECT last_value FROM {sequence_name}")
        value = cursor.fetchone()[0]
        return int(value) if value is not None else None


def main() -> int:
    load_dotenv()
    local_url = os.environ.get("LOCAL_DATABASE_URL")
    remote_url = os.environ.get("SUPABASE_DATABASE_URL")
    if not local_url or not remote_url:
        print("FAIL: LOCAL_DATABASE_URL and SUPABASE_DATABASE_URL are both required.", file=sys.stderr)
        return 2

    failures: list[str] = []
    try:
        with psycopg.connect(local_url, connect_timeout=10) as local, psycopg.connect(
            remote_url, connect_timeout=10
        ) as remote:
            local_tables = app_tables(local)
            remote_tables = app_tables(remote)
            if local_tables != remote_tables:
                failures.append(
                    f"table sets differ: local={local_tables}, supabase={remote_tables}"
                )
            tables = sorted(set(local_tables) & set(remote_tables))
            print("schema.table | local rows | Supabase rows | local id range | Supabase id range")
            print("-" * 88)
            for schema, table in tables:
                comparison = compare_table(local, remote, schema, table)
                print(
                    f"{schema}.{table} | {comparison.local_count} | {comparison.remote_count} | "
                    f"{comparison.local_min_id}..{comparison.local_max_id} | "
                    f"{comparison.remote_min_id}..{comparison.remote_max_id}"
                )
                if (
                    comparison.local_count != comparison.remote_count
                    or comparison.local_min_id != comparison.remote_min_id
                    or comparison.local_max_id != comparison.remote_max_id
                ):
                    failures.append(f"row count or id range differs for {schema}.{table}")
                local_nulls = null_counts(local, schema, table)
                remote_nulls = null_counts(remote, schema, table)
                if local_nulls != remote_nulls:
                    failures.append(f"important null counts differ for {schema}.{table}")
                if duplicate_count(remote, schema, table) != 0:
                    failures.append(f"duplicate values found for unique key on {schema}.{table}")
                if constraint_definitions(local, schema, table) != constraint_definitions(
                    remote, schema, table
                ):
                    failures.append(f"constraints differ for {schema}.{table}")
                if index_definitions(local, schema, table) != index_definitions(remote, schema, table):
                    failures.append(f"indexes differ for {schema}.{table}")
                local_non_ascii = non_ascii_row_count(local, schema, table)
                remote_non_ascii = non_ascii_row_count(remote, schema, table)
                if local_non_ascii != remote_non_ascii:
                    failures.append(f"non-ASCII row count differs for {schema}.{table}")
                if sample_rows(local, schema, table) != sample_rows(remote, schema, table):
                    failures.append(f"sample rows differ for {schema}.{table}")
                local_sequence = sequence_last_value(local, schema, table)
                remote_sequence = sequence_last_value(remote, schema, table)
                if (
                    local_sequence is not None
                    and remote_sequence is not None
                    and remote_sequence < comparison.remote_max_id
                ):
                    failures.append(f"Supabase sequence is behind max(id) for {schema}.{table}")
                print(
                    f"  nulls local={local_nulls} Supabase={remote_nulls}; "
                    f"sequence local={local_sequence} Supabase={remote_sequence}; "
                    f"non-ASCII rows local={local_non_ascii} Supabase={remote_non_ascii}; "
                    "constraints/indexes compared"
                )
    except psycopg.Error as exc:
        print(f"FAIL: verification query failed: {exc}", file=sys.stderr)
        return 1

    if failures:
        print("FAIL: migration verification found:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1
    print(
        "SUCCESS: all checked table counts, ID ranges, null counts, unique keys, "
        "constraints, indexes, samples, and sequences match."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
