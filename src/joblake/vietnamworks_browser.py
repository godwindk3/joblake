"""VietnamWorks discovery through its client-side pagination controls."""

import logging

from playwright.sync_api import Error as PlaywrightError, TimeoutError as PlaywrightTimeoutError

from joblake.browser_diagnostics import BrowserDiagnostics
from joblake.fetchers import (
    CloakBrowserFetcher, _build_url, _detect_block_reason,
    _run_browser_actions, _settle_page, _sleep_before_retry, _utc_now,
)
from joblake.models import FetchError, FetchResult, SourceBlockedError


LOGGER = logging.getLogger(__name__)

PAGINATION_BUTTON_XPATH = (
    "xpath=//ul[contains(concat(' ', normalize-space(@class), ' '), ' pagination ')]"
    "//button[normalize-space(.)={label}]"
)
EMPTY_RESULTS_TEXT = "Hiện chưa có công việc nào theo tiêu chí bạn tìm"


class VietnamWorksDiscoveryFetcher(CloakBrowserFetcher):
    def __init__(self, config):
        super().__init__(config)
        self.last_page_number = None
        self.last_links = []

    def _links(self):
        return self.page.locator(self.config["ready_selector"]).evaluate_all(
            "nodes => [...new Set(nodes.map(n => new URL(n.href).pathname))].sort()"
        )

    def _navigate(self, requested, timeout):
        response = self.page.goto(requested, wait_until="domcontentloaded", timeout=timeout)
        status = response.status if response else None
        reason = _detect_block_reason(status, self.page.content())
        if reason:
            self.blocked = True
            raise SourceBlockedError(f"{reason}: {requested}")
        if status is not None and status >= 400:
            raise FetchError(f"HTTP {status}: {requested}")

    def _pagination_state(self, number, timeout):
        # Missing/disabled controls require a URL probe, not an end-of-list guess.
        return self.page.wait_for_function(
            """({number, previous, selector}) => {
                const root = document.querySelector('ul.pagination');
                const active = root?.querySelector('li.active button')?.textContent.trim();
                const buttons = root ? [...root.querySelectorAll('button')] : [];
                const target = buttons.find(b => b.textContent.trim() === String(number));
                const next = buttons.find(b => b.textContent.trim() === '>');
                const disabled = b => b.disabled || b.getAttribute('aria-disabled') === 'true';
                let state = null;
                if (active === String(number)) state = 'arrived';
                else if (active === String(previous) && document.querySelector(selector)
                         && !document.querySelector('[aria-busy="true"]')) {
                    if (target && !disabled(target)) state = 'number';
                    else if (next && !disabled(next)) state = 'next';
                    else state = 'probe';
                }
                const key = `${number}:${active}:${state}`;
                const now = performance.now();
                if (window.__joblakePagination?.key !== key)
                    window.__joblakePagination = {key, since: now};
                const delay = state === 'probe' ? 5000 : 1500;
                return state && now - window.__joblakePagination.since >= delay ? state : false;
            }""",
            arg={"number": number, "previous": self.last_page_number,
                 "selector": self.config["ready_selector"]}, timeout=timeout,
        ).json_value()

    def _wait_result(self, requested, number, timeout):
        return self.page.wait_for_function(
            """({requested, number, selector, previous, emptyText}) => {
                if (document.querySelector('[aria-busy="true"]')) return false;
                const active = document.querySelector('ul.pagination li.active button')?.textContent.trim();
                const links = [...document.querySelectorAll(selector)].map(n => new URL(n.href).pathname);
                const expected = new URL(requested), actual = new URL(location.href);
                const sameRequest = expected.origin === actual.origin && expected.pathname === actual.pathname
                    && [...expected.searchParams].every(([k,v]) => actual.searchParams.get(k) === v);
                const empty = sameRequest && !document.querySelector('ul.pagination')
                    && document.body.innerText.includes(emptyText);
                let state = null;
                if (empty) state = 'empty';
                else if (active === String(number) && links.length
                         && (!previous.length || links.some(u => !previous.includes(u)))) state = 'jobs';
                const key = `${number}:${state}`;
                const now = performance.now();
                if (window.__joblakeResult?.key !== key) window.__joblakeResult = {key, since: now};
                return state && now - window.__joblakeResult.since >= 2000 ? state : false;
            }""",
            arg={"requested": requested, "number": number, "selector": self.config["ready_selector"],
                 "previous": self.last_links, "emptyText": EMPTY_RESULTS_TEXT}, timeout=timeout,
        ).json_value()

    def fetch(self, url, params=None, referer=None):
        requested = _build_url(url, params)
        number = int((params or {}).get("page", 1))
        timeout = self.config["timeout_seconds"] * 1000
        reload_requested = False
        for attempt in range(1, self.retry_settings.max_attempts + 1):
            diagnostics = BrowserDiagnostics.from_config(self.page, self.config)
            stage = "navigation"
            try:
                if self.last_page_number is None or reload_requested:
                    self._navigate(requested, timeout)
                else:
                    stage = "pagination"
                    active = self.page.locator("ul.pagination li.active button")
                    try:
                        active_number = active.inner_text(timeout=timeout).strip()
                    except PlaywrightTimeoutError:
                        active_number = None
                    if active_number != str(number):
                        if number != self.last_page_number + 1 or active_number not in (None, str(self.last_page_number)):
                            raise FetchError(f"Unexpected pagination state: active={active_number}, requested={number}")
                        # Humanized clicks require one supported selector, not
                        # chained locators or get_by_role. Match button text exactly.
                        try:
                            state = self._pagination_state(number, timeout) if active_number else "probe"
                        except PlaywrightTimeoutError:
                            state = "probe"
                        if state == "probe":
                            stage = "pagination_url_probe"
                            reload_requested = True
                            LOGGER.info("VietnamWorks pagination controls unavailable; URL probe: page=%s url=%s", number, requested)
                            self._navigate(requested, timeout)
                        elif state != "arrived":
                            label = "'>'" if state == "next" else f"'{number}'"
                            target = self.page.locator(PAGINATION_BUTTON_XPATH.format(label=label))
                            try:
                                target.click(timeout=timeout)
                            except Exception as exc:
                                # Older CloakBrowser versions do not export this
                                # exception. Recognize only its exact library type.
                                if not any(c.__name__ == "ElementNotReceivingEventsError"
                                           and c.__module__ == "cloakbrowser.human.actionability"
                                           for c in type(exc).__mro__):
                                    raise
                                diagnostics.capture(outcome="error", stage="pagination_click_covered",
                                                    attempt=attempt, requested_url=requested, error=str(exc))
                                active_number = active.inner_text(timeout=timeout).strip()
                                if active_number != str(number):
                                    if active_number != str(self.last_page_number):
                                        raise FetchError(f"Unexpected page after covered click: {active_number}") from exc
                                    stage = "pagination_url_fallback"
                                    reload_requested = True
                                    LOGGER.warning("VietnamWorks covered click; URL fallback: page=%s url=%s", number, requested)
                                    self._navigate(requested, timeout)
                # Kick lazy rendering before waiting for job anchors.
                stage = "scroll_before_ready"
                self.page.evaluate("window.scrollTo(0, 0)")
                self.page.mouse.wheel(0, 700)
                self.page.wait_for_timeout(500)
                stage = "ready_new_jobs"
                result_state = self._wait_result(requested, number, self.config.get("ready_timeout_seconds", 30) * 1000)
                if result_state == "empty":
                    reason = _detect_block_reason(None, self.page.content())
                    if reason:
                        self.blocked = True
                        raise SourceBlockedError(f"{reason}: {requested}")
                    diagnostics.capture(outcome="success", stage="confirmed_empty_results", attempt=attempt,
                                        requested_url=requested, final_url=self.page.url, job_count=0)
                    LOGGER.info("VietnamWorks confirmed empty results: page=%s; pagination ended", number)
                    # The empty page contains unrelated recommendations. Do not ingest them.
                    return FetchResult(requested_url=requested, final_url=self.page.url,
                                       status_code=None, content_type="text/html", fetched_at=_utc_now(),
                                       html="<html><body><!-- confirmed empty results --></body></html>")
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
            except (FetchError, SourceBlockedError, PlaywrightError) as exc:
                diagnostics.capture(outcome="error", stage=stage, attempt=attempt,
                                    requested_url=requested, error=str(exc))
                raise
            finally:
                diagnostics.close()
