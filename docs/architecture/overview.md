# Current architecture

Each source has a YAML configuration, adapter and parser. The CLI dispatches to the pipeline:

```text
Source listings -> discovery -> PostgreSQL crawl_state
                                    |
                               detail fetch -> MinIO HTML
                                                   |
                                                 parse
                                                   |
                                   PostgreSQL normalized records
```

Airflow provides four manual source DAGs with a shared one-slot pool. Remote synchronization is a separate CLI operation. The full CLI phase includes discovery and detail only.

## Data model authority

- src/joblake/parsing/models.py: ParsedJob, context and validation issues.
- src/joblake/parsing/validation.py: normalized-record validation.
- migrations/versions/: persisted schema history.
- src/joblake/postgres_state.py: PostgreSQL crawl state.

The parser model uses dataclasses. The [canonical field proposal](../archive/canonical-fields-v1.md) and older architecture diagram describe earlier proposals, not the implemented schema.

See [storage and state](storage-state.md), [location cities](location-cities.md) and [URL CDC](../operations/url-cdc.md).
