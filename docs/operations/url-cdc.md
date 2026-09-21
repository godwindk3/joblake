# Listing URL CDC

CDC detects absence from the configured listing scope, not deletion of the detail
page or a verified employer deadline. It runs after successful discovery and
before detail. It never deletes HTML or parsed output, or changes raw retry state.
It uses local PostgreSQL `crawl_state`. Manual Supabase sync reads this state
and reconciles a compact `serving.jobs` table: active jobs are published;
expired/unknown jobs are removed remotely. Crawl state and events stay local.
See [Supabase sync](supabase-cli.md).

## Enable and baseline

Apply `alembic upgrade head` and configure:

```yaml
cdc:
  enabled: true
  scope_version: 1
```

CDC requires `state.provider: postgres`. A source's first qualifying discovery
creates a baseline: observed URLs become `active`; historical unseen URLs remain
`unknown`. No expiration events are emitted for baseline creation. Later complete
scans expire active URLs missing from that scan immediately (one qualifying scan,
not a two-day threshold). An expired URL seen again becomes active and emits
`REAPPEARED`. Repeated absence emits nothing further. Existing `NEW` counting is
unchanged; an old expired URL is not counted as new when it reappears.

Changing enabled targets, their listing URLs/business filters, source adapter or
`scope_version` creates a new baseline on the next complete scan. Prior statuses
become unknown without expiration events. Delay, proxy, page caps and start-page
controls do not change the business scope; partial traversal still cannot qualify.
Bump `scope_version` when changing adapter logic in a way that changes URL scope.

## Coverage gate

Every expected target must finish with confirmed complete coverage. A URL observed
in any target is present for the source. The following scans skip CDC:

- A missing, failed, blocked or suspicious target.
- A fixed `total_pages` override or starting after page 1.
- Hitting the page safety limit, repeated pages or stale-page termination.
- An unconfirmed empty page, invalid HTTP response, or zero URLs across the source.

Automatic pagination can qualify after reaching its detected last page without
empty/invalid/repeated pages. VietnamWorks can qualify after its browser explicitly
confirms the empty result page; a typed `listing_end_confirmed` flag carries this
evidence. The HTML marker alone is not trusted. Whole-source zero-result scans are
conservatively skipped even when the terminal page is confirmed.

## Transactions, recovery and scheduling

The pipeline holds the existing source lock through discovery and finalization.
Finalization stores status changes, events, counts and its completion marker in
one transaction. Retry of an already finalized run returns its stored result;
an older unfinalized run cannot overwrite a newer discovery. A later pipeline run
marks interrupted pending CDC runs as skipped. Detail/parse failures do not undo
an already committed discovery result. Detail-only and parse-only phases never
perform reconciliation.

Schedules and DAG pause flags are unchanged. CDC executes whenever discovery runs;
daily scheduling can be enabled separately. The SQLite backend remains available
for legacy use but cannot enable CDC.

## Inspect results

Discovery logs include `CDC: run_id=... status=baseline|applied|skipped expired=...
reappeared=... reason=...`. Events are persisted locally; no email/Telegram sender
or external notification delivery is configured.

```powershell
.venv/Scripts/python.exe scripts/cdc_report.py --source topdev
.venv/Scripts/python.exe scripts/cdc_report.py --source topdev --run-id 123
```

The report is read-only. Its counts reflect current state; run/event filters do
not reconstruct a historical snapshot. To inspect incomplete targets directly:

```sql
SELECT run_id, target_name, status, coverage_complete, termination_reason
FROM crawl_state.discovery_targets
WHERE run_id = 123;

SELECT e.run_id, j.source, j.url, e.event_type, e.created_at
FROM crawl_state.url_events e
JOIN crawl_state.jobs j ON j.id = e.job_id
ORDER BY e.id DESC LIMIT 100;
```

`jobs.expired_at` is the time absence was detected, while `last_seen_at` remains
the actual observation time. Event history survives reappearance and scope resets.

To pause CDC, set `cdc.enabled: false`. This retains existing statuses/history;
it does not refresh presence until enabled again. Back up the whole JobLake DB
before schema changes. Avoid schema downgrade as an operational rollback because
it removes CDC status/history.

Historical results: [cdc-validation-2026-09-13.md](../archive/cdc-validation-2026-09-13.md).
