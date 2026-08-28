# Adding a job source

JobLake separates generic crawling from website-specific behavior.
`DiscoveryCrawler` handles fetching, delays, raw storage, metrics, and
cross-page de-duplication. A `JobSource` adapter owns URL extraction and
any source-specific request construction.

## 1. Create an adapter

Create `src/joblake/sources/example.py`:

```python
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from joblake.sources import JobSource


class ExampleSource(JobSource):

    def extract_job_urls(
        self,
        html: str,
        listing_url: str,
    ) -> list[str]:
        soup = BeautifulSoup(html, "html.parser")
        urls = [
            urljoin(listing_url, link["href"])
            for link in soup.select("a.job-card[href]")
        ]

        return list(dict.fromkeys(urls))
```

The method must return absolute URLs and should remove duplicates while
preserving order.

## 2. Add a source config

Create `configs/example.yaml`:

```yaml
source: example
source_adapter: joblake.sources.example.ExampleSource
enabled: true

discovery:
  transport: requests
  timeout_seconds: 30

  pagination:
    page_param: page
    start_page: 1
    max_auto_pages: 200

  delay:
    min_seconds: 5
    max_seconds: 10

  targets:
    - name: engineering
      base_url: https://example.com/jobs
      params:
        category: engineering

detail:
  transport: requests
  timeout_seconds: 30
  max_jobs_per_run: 50
  delay:
    min_seconds: 10
    max_seconds: 20

storage:
  provider: local
  raw_directory: data/raw

state:
  discovered_jobs_file: data/state/example_jobs.jsonl
  crawled_urls_file: data/state/example_crawled_urls.txt
```

Run it with:

```powershell
python -m joblake.main --config configs/example.yaml
```

## Optional overrides

When `total_pages` is omitted, `DiscoveryCrawler` fetches the first page
once and calls the adapter's `extract_last_page_number()` method. Add the
method when creating a source that supports automatic pagination:

```python
def extract_last_page_number(
    self,
    html: str,
    listing_url: str,
) -> int | None:
    # Parse the source-specific pagination HTML here.
    # Return the absolute last page number, for example 29.
    return last_page
```

Set `max_auto_pages` as a safety limit. To force a fixed number of pages,
configure `total_pages`; it takes precedence and skips automatic detection.
A target can also define its own `total_pages`.

For a source that does not expose its last page, use content-driven
pagination:

```yaml
pagination:
  page_param: page
  start_page: 1
  strategy: until_empty
  max_auto_pages: 200
  stop_after_empty_pages: 1
  stop_after_stale_pages: 2
```

The crawler stops after the configured number of empty pages. The stale
page limit is a second safety mechanism for sites that ignore `page` and
keep returning the same URLs. Reaching `max_auto_pages` without either
condition marks the discovery run as suspicious.

Override `build_listing_request()` when pagination is encoded in the URL
path or requires custom parameters. Override `build_detail_request()` when
detail pages need different parameters or a custom referrer.

Browser transports can run post-navigation actions without putting
website-specific behavior in the generic fetcher:

```yaml
browser_actions:
  - action: scroll
    times: 10
    delta_y: 1200
    wait_after_ms: 1000

  - action: click
    selector: 'button[aria-label="Show more"]'
    optional: true
    scroll_into_view: true
    wait_after_ms: 1000
```

Actions run in order after the ready selector and settle delay, but before
the final HTML is captured and validated.

Detail responses use the generic validation rules under
`detail.validation`. Override `validate_detail_html()` in the adapter
when a source needs stronger identity or completeness checks. Only a
validated response is accepted into `raw_objects` and prevents that URL
from being fetched again.

No changes to `discovery.py`, `pipeline.py`, storage, or state management
are required when adding another adapter.
