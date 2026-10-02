# Gemini: several jobs in one API request

Gemini supports `batch_size: 1`, `2` or `3` in `configs/enrichment.yaml`.
This groups JDs into one normal `generateContent` call, not the provider's
asynchronous Batch API. Groq and OpenRouter accept only `batch_size: 1` here.

The default remains **1 pending a successful paired live benchmark**. No quality
or token-saving claim should be inferred from local unit/SQL tests alone.

## Configuration and rollout

```yaml
calibrate_input_tokens: true
providers:
  - name: gemini
    # Keep the existing model, credentials and quotas.
    batch_size: 3
    batch_max_input_tokens: 12000
```

1. Finish any active enrichment worker, then run `python -m alembic upgrade head`.
   Revision `0006_enrichment_batches` is additive and preserves prior quota totals.
   It refuses to migrate while an enrichment worker holds the session lock.
2. Run the paired benchmark below and review validation, field differences and tokens.
3. Set Gemini `batch_size: 3` only when the results are acceptable; return it to 1
   at any time for subsequent worker runs. Source/config are mounted by Airflow.
4. Preview with the backfill DAG before processing a bounded group of jobs.

Both ordinary enrichment and backfill use the same worker. Backfill `max_jobs`
still limits distinct selected jobs. Its `max_api_attempts` and normal enrichment's
`max_jobs` count API requests, so one request can now attempt up to three jobs.

## Dispatch and validation

- Only never-attempted jobs are grouped. Jobs with previous attempts retry singly,
  using the existing 15-minute cooldown and maximum attempts per content version.
- Jobs carry explicit IDs in input/output. Results are matched by ID, never position.
- Evidence is validated against that job's original input only. Missing/duplicate
  IDs fail the affected job; unknown IDs or malformed top-level responses fail the group.
- A valid job in a partly invalid response is saved immediately in the same transaction
  as the other members' retry states. It is not sent again with the failed member.
- Shared prompt/schema appear once. Output cap is the per-job cap times group size
  (normally 2048/4096/6144). No JD is truncated to make a group fit.
- Long inputs stay single. Groups shrink if remaining quota cannot fit the full group;
  provider fallback applies if even the single request cannot be reserved.
- Content/activity is checked again for every member before reserving a request.
  One stale member prevents that reservation; the next dispatch rebuilds the selection.

## Quota and recovery

`core.enrichment_attempts` remains one row per HTTP/model request, including failed
requests. For a grouped request, `enrichment_id` is null and `item_count` is 2 or 3.
`core.enrichment_attempt_jobs` links that request to each enrichment and records
its status/error. Existing singleton history is linked during migration.

Request tokens are reserved/reconciled once, never once per member. Per-job attempt
counts still increment once for each API call containing that job. A mixed response
has request status `partial`; member rows identify the actual successes/failures.
The shared advisory lock protects both workers and the benchmark.

Interrupted requests retain reservations. Their processing members recover to
`retry_wait` without resetting attempts. Daily and minute budgets remain shared
across regular jobs, backfill and benchmark calls.

Logs distinguish `api_requests`, `attempted_jobs`, `succeeded` and `errors`; a request
log includes the request ID and number of jobs, and member logs include posting ID.

## Token estimates

The fallback remains UTF-8 input bytes / 2 plus the **full** output cap. Provider
responses now retain input/output token counts separately. With at least 20 measured
requests for the same provider/model and shape (single vs group), the worker uses
the recent 95th-percentile input-tokens/byte ratio with 25% headroom and a 0.25 floor.
Up to 100 samples from the last 30 days are considered. Old requests without separate
input usage cannot calibrate this estimator; total usage is never treated as input.

Calibration affects reservations and dispatch speed; it does not reduce actual
provider usage. It remains an estimate, and HTTP 429/cooldown is authoritative.

Backfill preview reports `planned_requests`, grouped `selected_estimated_tokens`,
`single_job_estimated_tokens` and calibration ratios for each enabled provider.
It assumes the given provider handles the whole selected set; actual dispatch may
shrink groups, use another provider, or stop when quota/time is exhausted.

## Paired benchmark

```powershell
# Read-only sample planning, no API calls.
python scripts/benchmark_enrichment_batches.py

# Explicit live test: 12 active JDs, 12 single calls and 4 grouped calls.
python scripts/benchmark_enrichment_batches.py --execute --jobs 12 --output output/enrichment-batch-benchmark.json
```

The sample is deterministic and spread across sources. Both arms use identical
inputs/model/output budget per job. Calls respect the persistent quota ledger and
are tagged `purpose='benchmark'`; production job results and attempts are untouched.
The report contains local copies of extraction results/evidence, IDs, validation
failures, charged tokens, API duration and field differences. It must remain local.

The script recommends review for activation only if both arms validate all 12 jobs,
field agreement is at least 95%, and the grouped arm uses fewer tokens. Lists are
compared without order/case differences. Agreement with a single-call baseline is
not ground-truth accuracy; inspect differences before expanding use.

Quota/cooldown can stop an experiment early. Such a report is explicitly incomplete
and cannot justify activation. Network failures retain conservative reservations.

## Verification

```powershell
$env:JOBLAKE_TEST_ENRICHMENT='1'
python -m unittest discover -s tests -p 'test_enrichment*.py'
```

Tests use fake models and disposable databases for request/member accounting,
partial failures, ID isolation, shared quota, retry, stale content, crash recovery,
grouped previews, full worker dispatch and calibration fallback.
