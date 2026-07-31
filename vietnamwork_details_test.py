from pathlib import Path

from cloakbrowser import launch


URL = "https://www.vietnamworks.com/ai-engineer-agentic-ai-2085611-jv"
OUTPUT_DIR = Path("cloak_test_output")

OUTPUT_DIR.mkdir(exist_ok=True)

browser = launch(headless=False)

try:
    page = browser.new_page()
    page.goto(URL, wait_until="domcontentloaded", timeout=60_000)
    page.wait_for_timeout(5_000)

    selectors = [
        'button[aria-label="Xem đầy đủ mô tả công việc"]',
        '#vnwLayout__col button[aria-label="Xem thêm"]',
    ]

    for selector in selectors:
        button = page.locator(selector)

        if button.count() > 0:
            button.first.scroll_into_view_if_needed()
            button.first.click()
            page.wait_for_timeout(1_000)

    (OUTPUT_DIR / "job_detail.html").write_text(
        page.content(),
        encoding="utf-8",
    )

    (OUTPUT_DIR / "job_detail.txt").write_text(
        page.locator("body").inner_text(),
        encoding="utf-8",
    )

    page.screenshot(
        path=str(OUTPUT_DIR / "job_detail.png"),
        full_page=True,
    )

finally:
    browser.close()