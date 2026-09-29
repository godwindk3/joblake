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

Airflow provides nine manual source DAGs with the shared three-slot `joblake_serial` pool. Each source runs discovery, detail and parse sequentially. Remote synchronization has a separate manual DAG and CLI command; enrichment is also a separate optional manual DAG. Data health and raw cleanup have daily schedules. Raw cleanup defaults to dry-run. The full CLI phase includes discovery and detail only.

## Data model authority

- src/joblake/parsing/models.py: ParsedJob, context and validation issues.
- src/joblake/parsing/validation.py: normalized-record validation.
- migrations/versions/: persisted schema history.
- src/joblake/postgres_state.py: PostgreSQL crawl state.

The parser model uses dataclasses. The [canonical field proposal](../archive/canonical-fields-v1.md) and older architecture diagram describe earlier proposals, not the implemented schema.

See [storage and state](storage-state.md), [location cities](location-cities.md) and [URL CDC](../operations/url-cdc.md).
