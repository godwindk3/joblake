import unittest
from unittest.mock import Mock, patch

from joblake.browser_actions import (
    run_browser_actions,
)
from joblake.fetchers import (
    RequestsFetcher,
    RetrySettings,
    _fetch_browser_page,
)
from joblake.models import HttpStatusError


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
