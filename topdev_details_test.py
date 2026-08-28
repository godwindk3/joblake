from pathlib import Path

from cloakbrowser import launch


URL = "https://topdev.vn/detail-jobs/abap-developer-sap-technical-consultant-shift-rotation-laidon-group-2121474?src=topdev_home&medium=superhotjobs"
OUTPUT_DIR = Path("cloak_test_output")

OUTPUT_DIR.mkdir(exist_ok=True)

browser = launch(headless=False)

try:
    page = browser.new_page()
    page.goto(URL, wait_until="domcontentloaded", timeout=60_000)
    page.wait_for_timeout(5_000)

    for _ in range(10):
        page.mouse.wheel(0, 1200)
        page.wait_for_timeout(700)

    (OUTPUT_DIR / "topdev_job_detail.html").write_text(
        page.content(),
        encoding="utf-8",
    )

    (OUTPUT_DIR / "topdev_job_detail.txt").write_text(
        page.locator("body").inner_text(),
        encoding="utf-8",
    )

    page.screenshot(
        path=str(OUTPUT_DIR / "topdev_job_detail.png"),
        full_page=True,
    )

finally:
    browser.close()