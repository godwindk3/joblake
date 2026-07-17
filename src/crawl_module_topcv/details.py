import logging
import random
import time
from dataclasses import dataclass
from collections.abc import Iterator

from playwright.sync_api import (
    BrowserContext,
    Error as PlaywrightError,
    Page,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)

logger = logging.getLogger(__name__)

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

@dataclass
class CrawlResult:
    url: str
    html: str | None
    success: bool
    error: str | None = None

def fetch_detail_html(
    page: Page,
    url: str,
    timeout_ms: int = 30_000,
) -> CrawlResult:
    try:
        response = page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=timeout_ms,
        )

        if response is not None and not response.ok:
            return CrawlResult(
                url=url,
                html=None,
                success=False,
                error=f"HTTP status: {response.status}",
            )
        
        html = page.content()

        if not html.strip():
            return CrawlResult(
                url=url,
                html=None,
                success=False,
                error="Empty HTML",
            )
        
        logger.info("Finished crawling %s", url)

        return CrawlResult(
            url=url,
            html=html,
            success=True,
        )
    
    except PlaywrightTimeoutError:
        logger.warning("Timeout while crawling %s", url)

        return CrawlResult(
            url=url,
            html=None,
            success=False,
            error="Timeout"
        )
    
    except PlaywrightError as exc:
        logger.exception("Playwright error while crawling %s", url)

        return CrawlResult(
            url=url,
            html=None,
            success=False,
            error=str(exc),
        )
    
def crawl_detail_pages(
    urls: list[str],
    min_delay: float = 4.0,
    max_delay: float = 6.0,
) -> Iterator[CrawlResult]:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled"
            ]
        )

        context: BrowserContext = browser.new_context(
            user_agent=DEFAULT_USER_AGENT,
        )

        page = context.new_page()

        try:
            for index, url in enumerate(urls):
                result = fetch_detail_html(
                    page=page,
                    url=url,
                )

                yield result

                if index < len(urls) - 1:
                    sleep_time = random.uniform(
                        min_delay,
                        max_delay,
                    )

                    logger.info(
                        "Waiting %.2f seconds",
                        sleep_time,
                    )

                    time.sleep(sleep_time)
        finally:
            context.close()
            browser.close()

urls = [
    "https://www.topcv.vn/viec-lam/ui-ux-designer/2228808.html",
    # "https://www.topcv.vn/viec-lam/system-engineer-crm-du-an-cntt/2184652.html",
]

def save_to_txt(html: str, filename: str) -> bool:
    """
    Save html to txt to check
    """
    try:
        with open(filename, "w", encoding="utf-8") as file:
            file.write(html)
        print("Done")
        return True
    except Exception as e:
        print("Error!!")
        return False


def process_crawled_details(urls: list[str]) -> None:
    for result in crawl_detail_pages(urls):
        if result.success:
            # save_to_txt(result.html, "html_test.txt")
            print(result.url, len(result.html or ""))
        else:
            print(result.url, result.error)

# process_crawled_details(urls)

