from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


URL = "https://topdev.vn/jobs/search?job_categories_ids=2%2C3%2C4%2C5%2C6%2C7%2C8%2C9%2C10%2C11%2C12%2C13%2C67"
SELECTOR = 'a[href^="/detail-jobs/"]'


def fetch(url: str) -> str:
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    return response.text


def parse(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")

    return list({
        urljoin(URL, tag["href"])
        for tag in soup.select(SELECTOR)
    })


html = fetch(URL)
urls = parse(html)

for url in urls:
    print(url)

print(f"Total URLs: {len(urls)}")