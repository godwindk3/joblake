"""VietnamWorks discovery through its client-side pagination controls."""

import logging

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from joblake.browser_diagnostics import BrowserDiagnostics
from joblake.fetchers import (
    CloakBrowserFetcher, _build_url, _detect_block_reason,
    _run_browser_actions, _settle_page, _sleep_before_retry, _utc_now,
)
from joblake.models import FetchError, FetchResult, SourceBlockedError


LOGGER = logging.getLogger(__name__)


class VietnamWorksDiscoveryFetcher(CloakBrowserFetcher):
    def __init__(self, config):
        super().__init__(config)
        self.last_page_number = None
        self.last_links = []

    def _links(self):
        return self.page.locator(self.config["ready_selector"]).evaluate_all(
            "nodes => [...new Set(nodes.map(n => new URL(n.href).pathname))].sort()"
        )

    def fetch(self, url, params=None, referer=None):
        requested = _build_url(url, params)
        number = int((params or {}).get("page", 1))
        timeout = self.config["timeout_seconds"] * 1000
        selector = self.config["ready_selector"]
        for attempt in range(1, self.retry_settings.max_attempts + 1):
            diagnostics = BrowserDiagnostics(self.page, self.config.get("diagnostics_dir"))
            stage = "navigation"
            try:
                if self.last_page_number is None:
                    response = self.page.goto(requested, wait_until="domcontentloaded", timeout=timeout)
                    status = response.status if response else None
                    reason = _detect_block_reason(status, self.page.content())
                    if reason:
                        self.blocked = True
                        raise SourceBlockedError(f"{reason}: {requested}")
                    if status is not None and status >= 400:
                        raise FetchError(f"HTTP {status}: {requested}")
                else:
                    stage = "pagination"
                    active = self.page.locator("ul.pagination li.active button")
                    active_number = active.inner_text(timeout=timeout).strip()
                    if active_number != str(number):
                        if number != self.last_page_number + 1 or active_number != str(self.last_page_number):
                            raise FetchError(f"Unexpected pagination state: active={active_number}, requested={number}")
                        next_button = self.page.locator("ul.pagination").get_by_role("button", name=">", exact=True)
                        target = self.page.locator("ul.pagination").get_by_role("button", name=str(number), exact=True)
                        if target.count() == 0:
                            target = next_button
                        if target.count() == 0 or target.is_disabled():
                            LOGGER.info("VietnamWorks pagination ended at page %s", self.last_page_number)
                            return FetchResult(requested_url=requested, final_url=self.page.url,
                                               status_code=None, content_type="text/html", fetched_at=_utc_now(),
                                               html="<html><body><!-- pagination exhausted --></body></html>")
                        target.click(timeout=timeout)
                    self.page.wait_for_function(
                        "n => document.querySelector('ul.pagination li.active button')?.textContent.trim() === String(n)",
                        arg=number, timeout=timeout,
                    )
                # Kick lazy rendering before waiting for job anchors.
                stage = "scroll_before_ready"
                self.page.evaluate("window.scrollTo(0, 0)")
                self.page.mouse.wheel(0, 700)
                self.page.wait_for_timeout(500)
                stage = "ready_new_jobs"
                self.page.wait_for_function(
                    """({selector, previous}) => {
                        const links = [...document.querySelectorAll(selector)]
                            .map(n => new URL(n.href).pathname);
                        return links.length > 0 && (!previous.length || links.some(u => !previous.includes(u)));
                    }""",
                    arg={"selector": selector, "previous": self.last_links},
                    timeout=self.config.get("ready_timeout_seconds", 30) * 1000,
                )
                stage = "scroll_remaining_jobs"
                _run_browser_actions(self.page, self.config)
                _settle_page(self.page, self.config)
                html = self.page.content()
                reason = _detect_block_reason(None, html)
                if reason:
                    self.blocked = True
                    raise SourceBlockedError(f"{reason}: {requested}")
                links = self._links()
                if not links or (self.last_links and not set(links).difference(self.last_links)):
                    raise FetchError(f"Job list did not change for page {number}")
                if self.config.get("diagnostics_capture_success"):
                    diagnostics.capture(outcome="success", stage=stage, attempt=attempt,
                                        requested_url=requested, final_url=self.page.url,
                                        job_count=len(links))
                self.last_page_number = number
                self.last_links = links
                return FetchResult(requested_url=requested, final_url=self.page.url,
                                   status_code=None, content_type="text/html", fetched_at=_utc_now(), html=html)
            except PlaywrightTimeoutError as exc:
                LOGGER.warning("VietnamWorks timeout: stage=%s page=%s attempt=%s error=%s",
                               stage, number, attempt, exc)
                diagnostics.capture(stage=stage, attempt=attempt, requested_url=requested,
                                    final_url=self.page.url, error=str(exc))
                if attempt == self.retry_settings.max_attempts:
                    raise FetchError(f"VietnamWorks timeout: stage={stage}; {requested}; {exc}") from exc
                _sleep_before_retry(attempt=attempt, settings=self.retry_settings,
                                    url=requested, reason=f"VietnamWorks {stage}")
            finally:
                diagnostics.close()
