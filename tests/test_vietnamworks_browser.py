import unittest
from unittest.mock import Mock, patch
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from joblake.models import FetchError

from joblake.fetchers import RetrySettings
from joblake.vietnamworks_browser import PAGINATION_BUTTON_XPATH, VietnamWorksDiscoveryFetcher


class VietnamWorksBrowserTests(unittest.TestCase):
    def make_fetcher(self):
        with patch("joblake.fetchers.CloakBrowserFetcher.__init__", return_value=None):
            fetcher = VietnamWorksDiscoveryFetcher({})
        fetcher.config = {"timeout_seconds": 10, "ready_selector": "h2 a[href*=\"-jv\"]"}
        fetcher.retry_settings = RetrySettings(max_attempts=1)
        fetcher.page = Mock()
        fetcher.page.url = "https://www.vietnamworks.com/viec-lam"
        fetcher.page.content.return_value = "<h2><a href='/job-1-jv'>Job</a></h2>"
        fetcher.page.goto.return_value = Mock(status=200)
        fetcher._links = Mock(return_value=["/job-1-jv"])
        fetcher._pagination_state = Mock(return_value="number")
        fetcher._wait_result = Mock(return_value="jobs")
        return fetcher

    def test_scroll_happens_before_waiting_for_first_jobs(self):
        fetcher = self.make_fetcher()
        events = []
        fetcher.page.mouse.wheel.side_effect = lambda *a: events.append("scroll")
        fetcher._wait_result.side_effect = lambda *a, **k: events.append("wait") or "jobs"
        fetcher.fetch(fetcher.page.url, {"page": 1})
        self.assertEqual(events[:2], ["scroll", "wait"])
        self.assertEqual(fetcher.last_page_number, 1)

    def test_next_page_clicks_without_navigation_and_checks_previous_links(self):
        fetcher = self.make_fetcher()
        fetcher.last_page_number = 1
        fetcher.last_links = ["/old-2-jv"]
        fetcher.page.locator.return_value.inner_text.return_value = "1"
        button = fetcher.page.locator.return_value
        button.count.return_value = 1
        button.is_disabled.return_value = False
        fetcher.fetch(fetcher.page.url, {"page": 2})
        fetcher.page.goto.assert_not_called()
        button.click.assert_called_once()
        button.get_by_role.assert_not_called()
        fetcher.page.locator.assert_any_call(PAGINATION_BUTTON_XPATH.format(label="'2'"))
        fetcher._wait_result.assert_called_once()

    def test_missing_controls_probe_url_and_timeout_is_not_end(self):
        fetcher = self.make_fetcher()
        fetcher.last_page_number = 9
        fetcher.last_links = ["/job-1-jv"]
        fetcher.page.locator.return_value.inner_text.return_value = "9"
        button = fetcher.page.locator.return_value
        button.count.return_value = 0
        fetcher._pagination_state.side_effect = PlaywrightTimeoutError("controls missing")
        fetcher._wait_result.side_effect = PlaywrightTimeoutError("results did not load")
        with self.assertRaises(FetchError):
            fetcher.fetch(fetcher.page.url, {"page": 10})
        fetcher.page.goto.assert_called_once()
        button.click.assert_not_called()

    def test_missing_number_uses_next_button(self):
        fetcher = self.make_fetcher()
        fetcher.last_page_number = 5
        fetcher.last_links = ["/old-jv"]
        active = Mock()
        active.inner_text.return_value = "5"
        numbered = Mock()
        numbered.count.return_value = 0
        next_button = Mock()
        next_button.count.return_value = 1
        next_button.is_disabled.return_value = False
        fetcher._pagination_state.return_value = "next"
        fetcher.page.locator.side_effect = {
            "ul.pagination li.active button": active,
            PAGINATION_BUTTON_XPATH.format(label="'6'"): numbered,
            PAGINATION_BUTTON_XPATH.format(label="'>'"): next_button,
        }.__getitem__
        fetcher.fetch(fetcher.page.url, {"page": 6})
        next_button.click.assert_called_once_with(timeout=10000)
        numbered.click.assert_not_called()
        self.assertEqual(fetcher.last_page_number, 6)

    def test_disabled_next_button_probes_url_before_ending(self):
        fetcher = self.make_fetcher()
        fetcher.last_page_number = 9
        fetcher.last_links = ["/job-1-jv"]
        button = fetcher.page.locator.return_value
        button.inner_text.return_value = "9"
        button.count.return_value = 1
        button.is_disabled.return_value = True
        fetcher._pagination_state.return_value = "probe"
        fetcher._wait_result.return_value = "empty"
        result = fetcher.fetch(fetcher.page.url, {"page": 10})
        self.assertIn("confirmed empty results", result.html)
        self.assertNotIn("job-1-jv", result.html)
        fetcher.page.goto.assert_called_once()
        button.click.assert_not_called()

    def covered_fetcher(self):
        fetcher = self.make_fetcher()
        fetcher.last_page_number = 11
        fetcher.last_links = ["/old-jv"]
        button = fetcher.page.locator.return_value
        button.inner_text.return_value = "11"
        error_type = type("ElementNotReceivingEventsError", (Exception,),
                          {"__module__": "cloakbrowser.human.actionability"})
        button.click.side_effect = error_type("covered by DIV")
        return fetcher

    def test_covered_click_falls_back_to_exact_url_and_preserves_filters(self):
        fetcher = self.covered_fetcher()
        result = fetcher.fetch(fetcher.page.url, {"g": 5, "page": 12})
        fetcher.page.goto.assert_called_once_with(
            "https://www.vietnamworks.com/viec-lam?g=5&page=12",
            wait_until="domcontentloaded", timeout=10000)
        self.assertEqual(fetcher.last_page_number, 12)
        self.assertIn("page=12", result.requested_url)
        fetcher._wait_result.assert_called_once_with(result.requested_url, 12, 30000)

    def test_covered_click_already_arrived_does_not_reload(self):
        fetcher = self.covered_fetcher()
        fetcher.page.locator.return_value.inner_text.side_effect = ["11", "12"]
        fetcher.fetch(fetcher.page.url, {"page": 12})
        fetcher.page.goto.assert_not_called()

    def test_fallback_wrong_active_page_fails_without_advancing(self):
        fetcher = self.covered_fetcher()
        fetcher._wait_result.side_effect = PlaywrightTimeoutError("still page 1")
        with self.assertRaises(FetchError):
            fetcher.fetch(fetcher.page.url, {"page": 12})
        self.assertEqual(fetcher.last_page_number, 11)

    def test_fallback_stale_jobs_fail_without_advancing(self):
        fetcher = self.covered_fetcher()
        fetcher._links.return_value = fetcher.last_links
        with self.assertRaises(FetchError):
            fetcher.fetch(fetcher.page.url, {"page": 12})
        self.assertEqual(fetcher.last_page_number, 11)

    def test_unrelated_click_error_does_not_trigger_url_fallback(self):
        fetcher = self.covered_fetcher()
        fetcher.page.locator.return_value.click.side_effect = ValueError("unrelated")
        with self.assertRaises(ValueError):
            fetcher.fetch(fetcher.page.url, {"page": 12})
        fetcher.page.goto.assert_not_called()

    def test_missing_next_button_still_discovers_page_16(self):
        fetcher = self.make_fetcher()
        fetcher.last_page_number = 15
        fetcher.last_links = ["/old-jv"]
        fetcher.page.locator.return_value.inner_text.return_value = "15"
        fetcher._pagination_state.return_value = "probe"
        result = fetcher.fetch(fetcher.page.url, {"g": 5, "page": 16})
        fetcher.page.goto.assert_called_once_with(
            "https://www.vietnamworks.com/viec-lam?g=5&page=16",
            wait_until="domcontentloaded", timeout=10000)
        self.assertEqual(fetcher.last_page_number, 16)
        self.assertIn("job-1-jv", result.html)

    def test_probe_retry_reloads_url_without_needing_pagination(self):
        fetcher = self.make_fetcher()
        fetcher.last_page_number = 16
        fetcher.last_links = ["/old-jv"]
        fetcher.page.locator.return_value.inner_text.return_value = "16"
        fetcher._pagination_state.return_value = "probe"
        fetcher.retry_settings = RetrySettings(max_attempts=2)
        fetcher._wait_result.side_effect = [PlaywrightTimeoutError("loading"), "empty"]
        with patch("joblake.vietnamworks_browser._sleep_before_retry"):
            result = fetcher.fetch(fetcher.page.url, {"g": 5, "page": 17})
        self.assertEqual(fetcher.page.goto.call_count, 2)
        self.assertIn("confirmed empty results", result.html)


if __name__ == "__main__":
    unittest.main()
