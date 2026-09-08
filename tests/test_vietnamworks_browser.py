import unittest
from unittest.mock import Mock, patch

from joblake.fetchers import RetrySettings
from joblake.vietnamworks_browser import VietnamWorksDiscoveryFetcher


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
        return fetcher

    def test_scroll_happens_before_waiting_for_first_jobs(self):
        fetcher = self.make_fetcher()
        events = []
        fetcher.page.mouse.wheel.side_effect = lambda *a: events.append("scroll")
        fetcher.page.wait_for_function.side_effect = lambda *a, **k: events.append("wait")
        fetcher.fetch(fetcher.page.url, {"page": 1})
        self.assertEqual(events[:2], ["scroll", "wait"])
        self.assertEqual(fetcher.last_page_number, 1)

    def test_next_page_clicks_without_navigation_and_checks_previous_links(self):
        fetcher = self.make_fetcher()
        fetcher.last_page_number = 1
        fetcher.last_links = ["/old-2-jv"]
        fetcher.page.locator.return_value.inner_text.return_value = "1"
        button = fetcher.page.locator.return_value.get_by_role.return_value
        button.count.return_value = 1
        button.is_disabled.return_value = False
        fetcher.fetch(fetcher.page.url, {"page": 2})
        fetcher.page.goto.assert_not_called()
        button.click.assert_called_once()
        args = fetcher.page.wait_for_function.call_args.kwargs["arg"]
        self.assertEqual(args["previous"], ["/old-2-jv"])

    def test_last_page_returns_empty_without_reusing_old_jobs(self):
        fetcher = self.make_fetcher()
        fetcher.last_page_number = 9
        fetcher.last_links = ["/job-1-jv"]
        fetcher.page.locator.return_value.inner_text.return_value = "9"
        button = fetcher.page.locator.return_value.get_by_role.return_value
        button.count.return_value = 0
        result = fetcher.fetch(fetcher.page.url, {"page": 10})
        self.assertNotIn("job-1-jv", result.html)
        fetcher.page.goto.assert_not_called()
        button.click.assert_not_called()


if __name__ == "__main__":
    unittest.main()
