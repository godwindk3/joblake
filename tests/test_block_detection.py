import unittest

from joblake.block_detection import detect_block_reason


class BlockDetectionTests(unittest.TestCase):

    def test_allows_valid_itviec_page_with_turnstile(self) -> None:
        html = """
        <html>
          <head>
            <title>IT Jobs</title>
            <script src="https://challenges.cloudflare.com/turnstile/v0/api.js"></script>
          </head>
          <body>
            <h3 data-search--job-selection-target="jobTitle"
                data-url="https://itviec.com/it-jobs/backend-1">
              Backend Engineer
            </h3>
          </body>
        </html>
        """

        self.assertIsNone(
            detect_block_reason(200, html)
        )

    def test_detects_cloudflare_challenge_title(self) -> None:
        html = """
        <html><head><title>Just a moment...</title></head></html>
        """

        self.assertEqual(
            detect_block_reason(200, html),
            "Cloudflare challenge",
        )

    def test_detects_cloudflare_challenge_form(self) -> None:
        html = """
        <form id="challenge-form">
          <input name="cf-chl-token">
        </form>
        """

        self.assertEqual(
            detect_block_reason(200, html),
            "Cloudflare challenge",
        )

    def test_detects_plain_http_403(self) -> None:
        self.assertEqual(
            detect_block_reason(403, "Access denied"),
            "HTTP 403 access denied",
        )


if __name__ == "__main__":
    unittest.main()
