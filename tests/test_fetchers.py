import unittest
import json
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

from joblake.browser_actions import (
    run_browser_actions,
)
from joblake.fetchers import (
    RequestsFetcher,
    RetrySettings,
    _fetch_browser_page,
)
from joblake.models import FetchError, HttpStatusError, SourceBlockedError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError


class _FakeMouse:

    def __init__(self, events: list) -> None:
        self.events = events

    def wheel(self, delta_x: int, delta_y: int) -> None:
        self.events.append(
            ("wheel", delta_x, delta_y)
        )


class _FakeLocator:

    def __init__(
        self,
        selector: str,
        events: list,
        present: bool,
    ) -> None:
        self.selector = selector
        self.events = events
        self.present = present

    @property
    def first(self):
        return self

    def count(self) -> int:
        return 1 if self.present else 0

    def scroll_into_view_if_needed(self) -> None:
        self.events.append(
            ("scroll_into_view", self.selector)
        )

    def click(self) -> None:
        self.events.append(
            ("click", self.selector)
        )


class _FakePage:

    def __init__(self) -> None:
        self.events: list[tuple] = []
        self.mouse = _FakeMouse(self.events)

    def wait_for_timeout(self, milliseconds: int) -> None:
        self.events.append(("wait", milliseconds))

    def locator(self, selector: str) -> _FakeLocator:
        return _FakeLocator(
            selector,
            self.events,
            present=selector != "#missing",
        )


class BrowserActionsTests(unittest.TestCase):

    def test_runs_scroll_and_optional_clicks_in_order(
        self,
    ) -> None:
        page = _FakePage()
        config = {
            "browser_actions": [
                {
                    "action": "scroll",
                    "times": 2,
                    "delta_y": 1200,
                    "wait_after_ms": 700,
                },
                {
                    "action": "click",
                    "selector": "#expand",
                    "optional": True,
                    "scroll_into_view": True,
                    "wait_after_ms": 1000,
                },
                {
                    "action": "click",
                    "selector": "#missing",
                    "optional": True,
                },
            ]
        }

        run_browser_actions(page, config)

        self.assertEqual(
            page.events,
            [
                ("wheel", 0, 1200),
                ("wait", 700),
                ("wheel", 0, 1200),
                ("wait", 700),
                ("scroll_into_view", "#expand"),
                ("click", "#expand"),
                ("wait", 1000),
            ],
        )


class RequestsFetcherTests(unittest.TestCase):

    @patch("joblake.fetchers.requests.Session")
    def test_410_raises_structured_error_without_retry(
        self,
        session_class,
    ) -> None:
        response = Mock()
        response.status_code = 410
        response.url = "https://example.com/job/gone"
        response.text = "verify you are human"
        response.headers = {"content-type": "text/html"}
        response.request.url = response.url
        session_class.return_value.get.return_value = response
        fetcher = RequestsFetcher({
            "timeout_seconds": 10,
            "retry": {
                "max_attempts": 3,
                "base_delay_seconds": 0,
                "max_delay_seconds": 0,
            },
        })

        with self.assertRaises(HttpStatusError) as context:
            fetcher.fetch(response.url)

        self.assertEqual(context.exception.status_code, 410)
        self.assertEqual(
            context.exception.fetch_result.final_url,
            response.url,
        )
        session_class.return_value.get.assert_called_once()


class _GoneBrowserResponse:
    status = 410
    headers = {"content-type": "text/html"}


class _GoneBrowserPage:

    def __init__(self) -> None:
        self.url = "https://example.com/job/gone"
        self.goto_calls = 0

    def goto(self, url, **kwargs):
        self.goto_calls += 1
        self.url = url
        return _GoneBrowserResponse()

    def content(self) -> str:
        return "verify you are human"


class BrowserFetcherTests(unittest.TestCase):

    def test_timeout_evidence_and_listener_cleanup_on_retries(self):
        page = Mock()
        page.url = "https://example.com/jobs"
        page.goto.return_value = Mock(status=200, headers={})
        page.content.return_value = "<html>Loading</html>"
        page.wait_for_selector.side_effect = PlaywrightTimeoutError("selector timed out")
        page.screenshot.side_effect = RuntimeError("screenshot unavailable")
        with tempfile.TemporaryDirectory() as directory:
            with patch("joblake.fetchers.time.sleep"):
                with self.assertRaisesRegex(FetchError, "stage=ready_selector/settle"):
                    _fetch_browser_page(
                        page=page, url=page.url, params=None, referer=None,
                        config={"timeout_seconds": 60, "ready_selector": "a.job",
                                "diagnostics_dir": directory},
                        retry_settings=RetrySettings(max_attempts=2),
                    )
            evidence = list(Path(directory).glob("*/diagnostics.json"))
            self.assertEqual(len(evidence), 2)
            metadata = json.loads(evidence[0].read_text(encoding="utf-8"))
            self.assertEqual(metadata["status"], 200)
            self.assertEqual(metadata["error"], "selector timed out")
            self.assertIn("screenshot unavailable", metadata["screenshot_error"])
            self.assertEqual((evidence[0].parent / "page.html").read_text(),
                             "<html>Loading</html>")
        self.assertEqual(page.goto.call_count, 2)
        self.assertEqual(page.on.call_count, 12)
        self.assertEqual(page.remove_listener.call_count, 12)

    def test_success_baseline_identifies_missing_search_and_preserves_console(self):
        from joblake.browser_diagnostics import BrowserDiagnostics
        page = Mock()
        page.content.return_value = "<html></html>"
        with tempfile.TemporaryDirectory() as directory:
            success = BrowserDiagnostics(page, directory, capture_success=True)
            request = Mock(url="https://example.com/search", method="POST", resource_type="xhr")
            success._request(request)
            success.capture(outcome="success", requested_url="https://example.com/jobs?page=1")
            success.close()
            failed = BrowserDiagnostics(page, directory)
            failed._console(Mock(type="error", text="Search initialization failed",
                                 location={"url": "https://example.com/app.js", "lineNumber": 12}))
            failed.capture(outcome="timeout")
            failed.close()
            records = [json.loads(p.read_text(encoding="utf-8"))
                       for p in Path(directory).glob("*/diagnostics.json")]
            record = next(r for r in records if r["outcome"] == "timeout")
            self.assertEqual(record["comparison"]["api_urls_only_in_success"],
                             ["https://example.com/search"])
            self.assertEqual(record["console_events"][0]["message"], "Search initialization failed")

    def test_diagnostics_distinguishes_pending_body_and_completed_api(self):
        from joblake.browser_diagnostics import BrowserDiagnostics
        page = Mock()
        page.content.return_value = "<html>Loading</html>"
        with tempfile.TemporaryDirectory() as directory:
            diagnostics = BrowserDiagnostics(page, directory)
            waiting = Mock(url="https://example.com/search", method="POST", resource_type="xhr")
            receiving = Mock(url="https://example.com/slow", method="GET", resource_type="fetch")
            done = Mock(url="https://example.com/done", method="POST", resource_type="xhr")
            for request in (waiting, receiving, done):
                diagnostics._request(request)
            diagnostics._response(Mock(request=receiving, status=200))
            response = Mock(request=done, status=200, headers={"content-type": "application/json", "content-length": "43"})
            response.body.return_value = b'{"error":"quota exceeded","token":"secret"}'
            done.response.return_value = response
            diagnostics._response(response)
            diagnostics._finished(done)
            diagnostics.capture(stage="ready_selector")
            evidence = next(Path(directory).glob("*/diagnostics.json"))
            data = json.loads(evidence.read_text(encoding="utf-8"))
            self.assertEqual([r["state"] for r in data["pending_requests"]],
                             ["pending_response", "pending_body"])
            preview = data["completed_api_responses"][0]["json_preview"]
            self.assertIn("quota exceeded", preview)
            self.assertNotIn("secret", preview)
            waiting.response.assert_not_called()
            receiving.response.assert_not_called()
            diagnostics.close()

    def test_diagnostics_network_events_are_bounded_and_strip_query(self):
        from joblake.browser_diagnostics import BrowserDiagnostics
        page = Mock()
        diagnostics = BrowserDiagnostics(page, "unused")
        response = Mock(status=429, url="https://example.com/api?token=secret")
        response.request.resource_type = "xhr"
        for _ in range(60):
            diagnostics._response(response)
        self.assertEqual(len(diagnostics.events), 50)
        self.assertEqual(diagnostics.events[-1]["url"], "https://example.com/api")
        diagnostics.close()

    def challenge_page(self, resolves):
        page = Mock()
        page.url = "https://example.com/jobs"
        challenge = Mock(status=403, headers={"content-type": "text/html"})
        success = Mock(status=200, headers={"content-type": "text/html"})
        success.frame = page.main_frame
        success.request.is_navigation_request.return_value = True
        page.goto.return_value = challenge
        page.content.return_value = "<title>Just a moment...</title>"

        def wait(milliseconds):
            if resolves:
                page.on.call_args.args[1](success)
                page.content.return_value = "<h1>Jobs</h1>"

        page.wait_for_timeout.side_effect = wait
        return page

    def test_transient_challenge_uses_new_document_status(self):
        page = self.challenge_page(resolves=True)
        result = _fetch_browser_page(
            page=page, url=page.url, params=None, referer=None,
            config={"timeout_seconds": 10, "challenge_wait_seconds": 30},
            retry_settings=RetrySettings(max_attempts=3),
        )
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.html, "<h1>Jobs</h1>")
        page.goto.assert_called_once()
        page.remove_listener.assert_called_once()

    @patch("joblake.fetchers.time.monotonic", side_effect=[0, 0, 31])
    def test_persistent_challenge_still_blocks_after_bounded_wait(self, clock):
        page = self.challenge_page(resolves=False)
        with self.assertRaises(SourceBlockedError):
            _fetch_browser_page(
                page=page, url=page.url, params=None, referer=None,
                config={"timeout_seconds": 10, "challenge_wait_seconds": 30},
                retry_settings=RetrySettings(max_attempts=3),
            )
        page.goto.assert_called_once()
        page.remove_listener.assert_called_once()

    def test_410_raises_structured_error_without_retry(
        self,
    ) -> None:
        page = _GoneBrowserPage()

        with self.assertRaises(HttpStatusError) as context:
            _fetch_browser_page(
                page=page,
                url=page.url,
                params=None,
                referer=None,
                config={"timeout_seconds": 10},
                retry_settings=RetrySettings(max_attempts=3),
            )

        self.assertEqual(context.exception.status_code, 410)
        self.assertEqual(
            context.exception.fetch_result.final_url,
            page.url,
        )
        self.assertEqual(page.goto_calls, 1)


if __name__ == "__main__":
    unittest.main()
