import random
import time

from joblake.config import load_config
from joblake.discovery import discover_all_job_urls
from joblake.fetchers import create_fetcher
from joblake.models import (
    FetchError,
    SourceBlockedError,
)
from joblake.state import (
    append_crawled_url,
    load_crawled_urls,
    save_discovered_jobs,
)
from joblake.storage import save_raw_detail


def run_pipeline(config_path: str) -> None:
    config = load_config(config_path)
    state_config = config["state"]

    print("========== PHASE 1: DISCOVERY ==========")

    try:
        discovered_jobs = discover_all_job_urls(
            config
        )
    except SourceBlockedError as exc:
        print(f"Discovery stopped: {exc}")
        return
    except FetchError as exc:
        print(f"Discovery failed: {exc}")
        return

    save_discovered_jobs(
        path=state_config["discovered_jobs_file"],
        records=discovered_jobs,
    )

    print(
        f"Discovery completed: "
        f"{len(discovered_jobs)} unique jobs"
    )

    print("========== PHASE 2: DETAIL ==========")

    crawled_urls = load_crawled_urls(
        state_config["crawled_urls_file"]
    )

    pending_jobs = [
        record
        for url, record in discovered_jobs.items()
        if url not in crawled_urls
    ]

    print(f"Already crawled: {len(crawled_urls)}")
    print(f"Pending this run: {len(pending_jobs)}")

    detail_config = config["detail"]
    max_jobs = detail_config.get(
        "max_jobs_per_run"
    )

    if max_jobs is not None:
        pending_jobs = pending_jobs[:max_jobs]

    with create_fetcher(detail_config) as fetcher:
        for index, discovery_record in enumerate(
            pending_jobs,
            start=1,
        ):
            print(
                f"Detail {index}/{len(pending_jobs)}: "
                f"{discovery_record.url}"
            )

            try:
                fetch_result = fetcher.fetch(
                    url=discovery_record.url
                )

                html_path, metadata_path = (
                    save_raw_detail(
                        discovery_record=discovery_record,
                        fetch_result=fetch_result,
                        config=config,
                    )
                )

                # Chỉ đánh dấu sau khi lưu cả hai file.
                append_crawled_url(
                    path=state_config[
                        "crawled_urls_file"
                    ],
                    url=discovery_record.url,
                )

                crawled_urls.add(
                    discovery_record.url
                )

                print(f"HTML: {html_path}")
                print(f"Metadata: {metadata_path}")

            except SourceBlockedError as exc:
                print(f"Detail crawling blocked: {exc}")

                # Không tiếp tục gọi hàng loạt URL.
                break

            except FetchError as exc:
                print(
                    f"Detail failed, will retry "
                    f"next run: {exc}"
                )

            except Exception as exc:
                print(
                    f"Unexpected error for "
                    f"{discovery_record.url}: {exc}"
                )

            sleep_seconds = random.uniform(
                detail_config["delay"]["min_seconds"],
                detail_config["delay"]["max_seconds"],
            )

            time.sleep(sleep_seconds)