import time
import random
import requests
from typing import Any
from collections.abc import Iterator


def fetch(
        session: requests.Session,
        base_url: str,
        params: dict[str, Any],
        timeout: float = 10.0,
) -> str:
    response = session.get(
        base_url,
        params=params,
        timeout=timeout,
    )
    response.raise_for_status()
    
    return response.text


# This return a list of page that using for extract urls 
def fetch_all_it_jobs_pages(
    base_url: str,
    total_pages: int = 5,
    min_delay: float = 4.0,
    max_delay: float = 6.0,
) -> Iterator[str]:
    
    html_pages: list[str] = []

    with requests.Session() as session:
        for page in range(1, total_pages + 1):
            params = {
                "type_keyword": 1,
                "category_family": "r257",
                "saturday_status": 0,
                "page": page,
            }

            try:
                page_html = fetch(
                    session=session,
                    base_url=base_url, 
                    params=params,
                )
            except requests.RequestException as exc:
                print(f"Failed to fetch page {page}: {exc}")
                continue


            print(f"Finished fetching page {page}")

            yield page_html

            if page < total_pages:
                sleep_time = random.uniform(
                    min_delay,
                    max_delay,
                )

                print(f"Waiting {sleep_time:.2f} seconds...")
                time.sleep(sleep_time)

        
    

# base_url = "https://www.topcv.vn/tim-viec-lam-cong-nghe-thong-tin-cr257"
# html_pages = fetch_all_it_jobs_pages(base_url=base_url, total_pages=1)
# print(html_pages)