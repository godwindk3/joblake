#!/usr/bin/env python3
"""Perform a read-only connectivity check against Supabase PostgreSQL."""

from __future__ import annotations

import logging
import os

import psycopg
from dotenv import load_dotenv

from joblake.logging import configure_logging


LOGGER = logging.getLogger(__name__)


def main() -> int:
    configure_logging()
    load_dotenv()
    database_url = os.environ.get("SUPABASE_DATABASE_URL")

    if not database_url:
        LOGGER.error(
            "FAIL: SUPABASE_DATABASE_URL is not set. "
            "Add it to your untracked .env file.",
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
        LOGGER.error(
            "FAIL: could not connect to Supabase PostgreSQL: "
            f"{exc.__class__.__name__} (check endpoint, network and credentials)",
        )
        return 1

    LOGGER.info("SUCCESS: connected to Supabase PostgreSQL (read-only check).")
    LOGGER.info(f"Database: {database_name}")
    LOGGER.info(f"Current schema: {schema_name}")
    LOGGER.info(f"Server: {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
