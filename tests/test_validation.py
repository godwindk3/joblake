import unittest

from joblake.models import FetchResult
from joblake.validation import validate_detail_html


class RawValidationTests(unittest.TestCase):

    def _fetch_result(
        self,
        *,
        html: str,
        final_url: str = (
            "https://itviec.com/it-jobs/backend-123"
        ),
    ) -> FetchResult:
        return FetchResult(
            requested_url=final_url,
            final_url=final_url,
            status_code=200,
            content_type="text/html; charset=utf-8",
            fetched_at="2026-01-01T00:00:00+00:00",
            html=html,
        )

    def test_accepts_valid_source_specific_html(self) -> None:
        result = validate_detail_html(
            fetch_result=self._fetch_result(
                html=(
                    "<html><body><h1>Backend</h1>"
                    "<main>Long enough description</main>"
                    "</body></html>"
                )
            ),
            detail_url=(
                "https://itviec.com/it-jobs/backend-123"
            ),
            validation_config={
                "min_html_bytes": 20,
                "min_text_chars": 10,
                "required_selectors": ["h1"],
            },
            validation_version="itviec-v1",
            required_path_prefixes=("/it-jobs/",),
        )

        self.assertTrue(result.is_valid)
        self.assertEqual(result.errors, [])

    def test_rejects_missing_required_selector(self) -> None:
        result = validate_detail_html(
            fetch_result=self._fetch_result(
                html=(
                    "<html><body>"
                    "<main>Description only</main>"
                    "</body></html>"
                )
            ),
            detail_url=(
                "https://itviec.com/it-jobs/backend-123"
            ),
            validation_config={
                "required_selectors": ["h1"],
            },
            validation_version="itviec-v1",
            required_path_prefixes=("/it-jobs/",),
        )

        self.assertFalse(result.is_valid)
        self.assertIn(
            "missing_required_selector:h1",
            result.errors,
        )

    def test_rejects_redirect_to_another_host(self) -> None:
        result = validate_detail_html(
            fetch_result=self._fetch_result(
                html="<html><body><h1>Login</h1></body></html>",
                final_url="https://evil.example/login",
            ),
            detail_url=(
                "https://itviec.com/it-jobs/backend-123"
            ),
            validation_config={
                "required_selectors": ["h1"],
            },
            validation_version="itviec-v1",
            required_path_prefixes=("/it-jobs/",),
        )

        self.assertFalse(result.is_valid)
        self.assertIn(
            "unexpected_final_host",
            result.errors,
        )
        self.assertIn(
            "unexpected_final_path",
            result.errors,
        )


if __name__ == "__main__":
    unittest.main()
