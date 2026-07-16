import time
import random
import requests


def fetch(base_url: str, payload: dict) -> str:
    response = requests.get(base_url, params=payload, timeout=10)
    response.raise_for_status
    return response.text


# This return a list of page that using for extract urls 
def fetch_all_it_jobs_page(base_url: str, page_number: int = 5) -> list:

    htmls = []

    for i in range(1, page_number):
        payload = {
            "type_keyword": 1,
            "category_family": "r257",
            "saturday_status": 0,
            "page": i,
        }

        page_html = fetch(base_url=base_url, payload=payload)
        htmls.append(page_html)
        print(f"Finish page {i}")

        sleep_time = random.uniform(4.0, 6)

        print(f"Waiting: {sleep_time:.2f} seconds....")

        time.sleep(sleep_time)

        
    return htmls