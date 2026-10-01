# Adding a job source

A source needs a listing/detail adapter, parser, YAML config, offline fixtures
and a DAG if it will run in Airflow. Generic fetching, state and storage should
remain source-independent.

## Adapter and parser

Implement `JobSource` from `joblake.sources.base`. Return absolute canonical job
URLs from `extract_job_urls`, preserving order and removing tracking/duplicates.
Implement `extract_last_page_number` where the site exposes a total. Override
listing/detail request construction for path-based pagination or custom headers.
Validation must reject redirects to another job, challenge pages and empty shells.

Implement `JobParser` from `joblake.parsing.base`, with `source`, `version` and
`parse(html, context) -> ParserOutput`. Return `ParsedJob` plus extraction issues;
let shared `assess_parsed_job` determine accepted/partial/rejected quality. Preserve
raw values and leave unavailable optional fields empty. Do not infer skills,
industry or dates merely from the listing category. Location cities are derived
by the shared parsed model.

Register defaults in `sources/factory.py` and `parsing/registry.py`, or use explicit
adapter paths in YAML:

```yaml
source: example
source_adapter: joblake.sources.example.ExampleSource
parse:
  parser_adapter: joblake.parsing.parsers.example.ExampleParser
  max_jobs_per_run: null
  max_attempts: 3
  stale_after_seconds: 3600
state:
  provider: postgres
```

This is an excerpt, not a complete runnable config. Copy the nearest existing
source config, then replace source-specific paths, targets, validation, proxy
environment names and browser-state filenames. Keep MinIO/PostgreSQL configuration
consistent with the deployment. Bump parser version after changing extraction
behavior so retained raw can be reparsed.

## Pagination and CDC

Choose `detect_last_page` or `until_empty` from existing working sources. A fixed
`total_pages`, page cap, repeated page, partial target failure or unconfirmed empty
page cannot prove full coverage. Never infer expiry from such runs. CDC requires
PostgreSQL state and explicitly enabled `cdc.enabled`; see [CDC](../operations/url-cdc.md).

Return a trustworthy terminal-page signal for sources using browser-driven
pagination. `max_auto_pages` is a safety cap, not evidence that every listing was
visited. Bump `cdc.scope_version` when adapter changes alter the business scope.

Prefer requests when the configured site returns complete HTML. Browser actions
such as scrolling/clicking belong in source configuration where supported; avoid
hard-coding site selectors into the generic fetcher. Configure diagnostics for
failure evidence and use source-specific browser sessions.

## Verification and operation

1. Add reduced real HTML fixtures and offline tests for pagination, URL identity,
   redirects, challenge/shell pages, optional fields and valid parser output.
2. Validate discovery coverage and a bounded detail batch against the source;
   document the date and distinguish live tests from fixture tests.
3. Run discovery, detail and parse separately with `--strict`. `full` omits parse.
   Accepted partial results are not parse failures; inspect saved health reports.
4. Add a manual source DAG following the existing phase/watcher pattern, update
   `orchestration/airflow/check_dag.py`, and verify it in the real Airflow image.
5. Update [source operations](../operations/airflow-sources.md), this documentation
   index and the source-specific guide. Shared health defaults apply automatically
   to source YAMLs; add an override in `configs/data_health.yaml` if justified.
6. Review the explicit source list in `log_cleanup.py` if the new DAG's logs should
   join that retention policy. Confirm serving publication only after a complete
   CDC baseline and a usable parse.

See [testing and CI](testing.md). Unit tests alone do not validate a website's
current layout, production credentials or browser behavior.
