# Location cities

`ParsedJob.location_cities` is derived automatically from `locations_raw` for all
nine sources and stored as `core.job_parse_results.location_cities text[]`.
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

Current serving sync explicitly exports `location_cities` into `serving.jobs`.
New serving setup includes this column and its GIN index. The script
`scripts/supabase_location_cities.sql` is only for the legacy `core` replica;
do not apply it to the compact serving deployment. Local backfill and remote sync
are separate actions. See [sync](../operations/supabase-cli.md).

## Website filtering

```sql
SELECT id, title, location_cities
FROM serving.jobs
WHERE location_cities @> ARRAY['Hà Nội']::text[];
```

V1 filters one city; v2 accepts multiple city labels and matches any overlap.
See the [website contract](../development/serving-contract.md) for exact semantics.
For local inspection, query current `core.job_parse_results` instead of serving.
