import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock

from joblake.browser_diagnostics import BrowserDiagnostics


class DiagnosticsRetentionTests(unittest.TestCase):
    def test_disabled_does_not_attach_or_write(self):
        with tempfile.TemporaryDirectory() as directory:
            page = Mock()
            diagnostics = BrowserDiagnostics.from_config(page, {
                "diagnostics_dir": directory, "diagnostics_enabled": False,
                "diagnostics_capture_success": True,
            })
            diagnostics.capture(outcome="error")
            diagnostics.close()
            page.on.assert_not_called()
            page.content.assert_not_called()
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_default_skips_success_and_caps_error_captures(self):
        with tempfile.TemporaryDirectory() as directory:
            page = Mock()
            page.content.return_value = "<html>error</html>"
            diagnostics = BrowserDiagnostics(page, directory, max_captures=2)
            diagnostics.capture(outcome="success")
            self.assertEqual(list(Path(directory).iterdir()), [])
            for _ in range(4):
                diagnostics.capture(outcome="error")
            self.assertEqual(len(list(Path(directory).glob("*/diagnostics.json"))), 2)
            diagnostics.close()
            self.assertEqual(diagnostics.requests, {})
            self.assertEqual(diagnostics.listeners, [])
            self.assertIsNone(diagnostics.page)

    def test_cleanup_expires_owned_files_and_preserves_unrelated_data(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old = root / "20200101T000000-123456789abc"
            old.mkdir()
            (old / "page.html").write_text("old")
            os.utime(old, (time.time() - 10 * 86400,) * 2)
            unrelated = root / "20200101T000000-abcdef123456"
            unrelated.mkdir()
            (unrelated / "keep.txt").write_text("user data")
            os.utime(unrelated, (time.time() - 10 * 86400,) * 2)
            diagnostics = BrowserDiagnostics(Mock(), directory)
            self.assertFalse(old.exists())
            self.assertEqual((unrelated / "keep.txt").read_text(), "user data")
            diagnostics.close()

    def test_unknown_length_response_body_is_not_loaded(self):
        with tempfile.TemporaryDirectory() as directory:
            page = Mock()
            page.content.return_value = "html"
            diagnostics = BrowserDiagnostics(page, directory)
            request = Mock(resource_type="xhr", url="https://example.com/api", method="GET")
            response = Mock(headers={"content-type": "application/json"})
            request.response.return_value = response
            diagnostics._request(request)
            diagnostics._finished(request)
            diagnostics.capture(outcome="error")
            response.body.assert_not_called()
            diagnostics.close()

    def test_invalid_limits_rejected(self):
        for options in ({"retention_days": 0}, {"retention_days": float("nan")},
                        {"max_captures": 0}, {"max_captures": 1.5}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                BrowserDiagnostics(Mock(), None, **options)
