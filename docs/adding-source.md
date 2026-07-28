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

Override `build_listing_request()` when pagination is encoded in the URL
path or requires custom parameters. Override `build_detail_request()` when
detail pages need different parameters or a custom referrer.

Detail responses use the generic validation rules under
`detail.validation`. Override `validate_detail_html()` in the adapter
when a source needs stronger identity or completeness checks. Only a
validated response is accepted into `raw_objects` and prevents that URL
from being fetched again.

No changes to `discovery.py`, `pipeline.py`, storage, or state management
are required when adding another adapter.
