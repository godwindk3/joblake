from urllib.parse import urljoin

from cloakbrowser import launch


URL = "https://topdev.vn/jobs/search?job_categories_ids=2%2C3%2C4%2C5%2C6%2C7%2C8%2C9%2C10%2C11%2C12%2C13%2C67"
URL_PAGE_2 = "https://topdev.vn/jobs/search?job_categories_ids=2%2C3%2C4%2C5%2C6%2C7%2C8%2C9%2C10%2C11%2C12%2C13%2C67&page=2"
SELECTOR = 'a[href^="/detail-jobs/"]'

browser = launch(headless=False)

try:
    page = browser.new_page()
    page.goto(URL, wait_until="domcontentloaded", timeout=60_000)

    for _ in range(10):
        page.mouse.wheel(0, 1200)
        page.wait_for_timeout(1000)

    links = page.locator(SELECTOR)
    scraped_urls = set()

    for i in range(links.count()):
        link = links.nth(i)
        href = link.get_attribute("href")

        if href:
            full_url = urljoin(URL, href)

            if full_url not in scraped_urls:
                scraped_urls.add(full_url)
                print(link.inner_text().strip())
                print(full_url)
                print()

    print(f"Total URLs: {len(scraped_urls)}")

finally:
    browser.close()