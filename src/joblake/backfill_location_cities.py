"""Populate city labels from stored raw locations without recrawling/reparsing HTML."""
import argparse
import os

import psycopg
from dotenv import load_dotenv

from joblake.parsing.locations import location_cities
from joblake.supabase_sync import configure


def backfill(connection, *, apply=False):
    changed = 0
    with connection.cursor(name="city_backfill") as reader:
        reader.execute("SELECT id, locations_raw, location_cities FROM core.job_parse_results ORDER BY id")
        while rows := reader.fetchmany(500):
            for row_id, raw, existing in rows:
                cities = list(location_cities(raw))
                if cities != existing:
                    changed += 1
                    if apply:
                        connection.execute(
                            "UPDATE core.job_parse_results SET location_cities = %s "
                            "WHERE id = %s AND locations_raw = %s",
                            (cities, row_id, raw),
                        )
    return changed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Commit updates; default only counts changes")
    args = parser.parse_args()
    load_dotenv()
    configure()
    with psycopg.connect(os.environ["LOCAL_DATABASE_URL"], connect_timeout=5) as connection:
        if not args.apply:
            connection.execute("SET TRANSACTION READ ONLY")
        changed = backfill(connection, apply=args.apply)
    print(f"{'Updated' if args.apply else 'Would update'} {changed} rows")


if __name__ == "__main__":
    main()
