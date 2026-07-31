from urllib.parse import urljoin

from cloakbrowser import launch


URL = "https://www.vietnamworks.com/viec-lam?g=5"
SELECTORS = [
    "a.img_job_card[href]",
    'h2 a[href*="-jv"]',
]

browser = launch(headless=False)

try:
    page = browser.new_page()
    page.goto(URL, wait_until="domcontentloaded", timeout=60_000)

    for _ in range(10):
        page.mouse.wheel(0, 1200)
        page.wait_for_timeout(1000)

    for selector in SELECTORS:
        links = page.locator(selector)
        if links.count() > 0:
            break
    else:
        raise RuntimeError("Không tìm thấy job link")

    scraped_urls = set()

    for i in range(links.count()):
        link = links.nth(i)
        href = link.get_attribute("href")
        title = link.get_attribute("title") or link.inner_text().strip()

        if href:
            full_url = urljoin(URL, href)
            scraped_urls.add(full_url)

            print(title)
            print(full_url)
            print()

    print(f"Total urls: {len(scraped_urls)}")

finally:
    browser.close()