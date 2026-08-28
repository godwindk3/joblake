import unittest

from joblake.browser_actions import (
    run_browser_actions,
)


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


if __name__ == "__main__":
    unittest.main()
