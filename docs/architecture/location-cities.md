# Location cities

`ParsedJob.location_cities` is derived automatically from `locations_raw` for all
four sources and stored as `core.job_parse_results.location_cities text[]`.
The original addresses are preserved. Unknown locations produce an empty array.
The derived field does not increase the raw-field completeness score.

Normalization recognizes accented/unaccented province names and common aliases
such as HCMC, TP.HCM, Ho Chi Minh City, Hanoi and Da Nang. It matches complete
comma/colon/semicolon/newline/slash-separated address components, avoiding city
names embedded in street names. Historical province names are preserved; this
is not an administrative-boundary migration or geocoding service. District-only
addresses and foreign cities remain unclassified. Extend `parsing/locations.py`
and its tests when a new source format is encountered.

## Rollout

Run from the repository root with its Python environment:

```powershell
python -m alembic upgrade head
python -m joblake.backfill_location_cities
python -m joblake.backfill_location_cities --apply
```

The first backfill command only reports the number of changes. The second
updates existing results from their stored locations without fetching websites
or replacing parse history. Empty old `locations_raw` still requires reparsing
saved HTML with the updated source parsers.

For an existing Supabase replica, apply `scripts/supabase_location_cities.sql`
to that database before the next sync. Do not use the full initial replica
migration against an existing replica. Sync already transfers every column and
therefore includes this new array; verification compares complete rows.

## Website filtering

```sql
SELECT id, title, location_cities
FROM core.job_parse_results
WHERE is_current
  AND location_cities @> ARRAY['Hà Nội']::text[];
```

The migration adds a GIN index for array containment queries. Supabase supports
[Postgres arrays](https://supabase.com/docs/guides/database/arrays).
