import json
import random
import time
from datetime import datetime, timezone
from typing import Iterator
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from joblake.fetchers import create_fetcher
from joblake.models import DiscoveryRecord
from joblake.storage import save_raw_discovery


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _walk_json(
    value,
) -> Iterator[dict]:
    if isinstance(value, dict):
        yield value

        for child in value.values():
            yield from _walk_json(child)

    elif isinstance(value, list):
        for child in value:
            yield from _walk_json(child)


def extract_urls_from_html(
    html: str,
    listing_url: str,
) -> list[str]:
    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    urls: list[str] = []

    scripts = soup.find_all(
        "script",
        attrs={"type": "application/ld+json"},
    )

    for script in scripts:
        raw_json = script.string or script.get_text()

        if not raw_json.strip():
            continue

        try:
            json_data = json.loads(raw_json)
        except json.JSONDecodeError:
            continue

        for item in _walk_json(json_data):
            if item.get("@type") != "ItemList":
                continue

            elements = item.get(
                "itemListElement",
                []
            )

            for element in elements:
                if not isinstance(element, dict):
                    continue

                job_url = element.get("url")

                nested_item = element.get("item")

                if (
                    not job_url
                    and isinstance(nested_item, dict)
                ):
                    job_url = nested_item.get("url")

                if not job_url:
                    continue

                absolute_url = urljoin(
                    listing_url,
                    job_url,
                )

                if "/viec-lam/" in absolute_url:
                    urls.append(absolute_url)

    # Loại trùng nhưng giữ thứ tự.
    return list(dict.fromkeys(urls))


def discover_all_job_urls(
    config: dict,
) -> dict[str, DiscoveryRecord]:
    source = config["source"]

    discovery_config = config["discovery"]
    pagination = discovery_config["pagination"]
    delay = discovery_config["delay"]

    page_param = pagination["page_param"]

    discovered_jobs: dict[
        str,
        DiscoveryRecord,
    ] = {}

    with create_fetcher(discovery_config) as fetcher:
        for target in discovery_config["targets"]:
            if not target.get("enabled", True):
                continue

            target_name = target["name"]
            base_url = target["base_url"]
            base_params = target.get("params", {})

            start_page = target.get(
                "start_page",
                pagination["start_page"],
            )

            total_pages = target.get(
                "total_pages",
                pagination["total_pages"],
            )

            print(f"Starting target: {target_name}")

            for page_number in range(
                start_page,
                start_page + total_pages,
            ):
                page_params = {
                    **base_params,
                    page_param: page_number,
                }

                fetch_result = fetcher.fetch(
                    url=base_url,
                    params=page_params,
                )

                # Lưu raw discovery trước khi parse.
                save_raw_discovery(
                    source=source,
                    target_name=target_name,
                    page_number=page_number,
                    fetch_result=fetch_result,
                    config=config,
                )

                page_urls = extract_urls_from_html(
                    html=fetch_result.html,
                    listing_url=fetch_result.final_url,
                )

                previous_count = len(
                    discovered_jobs
                )

                for job_url in page_urls:
                    if job_url in discovered_jobs:
                        continue

                    discovered_jobs[job_url] = (
                        DiscoveryRecord(
                            source=source,
                            url=job_url,
                            target_name=target_name,
                            listing_url=(
                                fetch_result.final_url
                            ),
                            listing_page=page_number,
                            discovered_at=_utc_now(),
                        )
                    )

                new_count = (
                    len(discovered_jobs)
                    - previous_count
                )

                print(
                    f"Target={target_name}, "
                    f"page={page_number}, "
                    f"found={len(page_urls)}, "
                    f"new={new_count}, "
                    f"total={len(discovered_jobs)}"
                )

                sleep_seconds = random.uniform(
                    delay["min_seconds"],
                    delay["max_seconds"],
                )

                time.sleep(sleep_seconds)

    return discovered_jobs