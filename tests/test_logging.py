import io
import logging
import unittest
from unittest.mock import patch

from joblake.logging import configure_logging


class LoggingTests(unittest.TestCase):
    def test_stderr_filters_debug_and_does_not_duplicate_handlers(self):
        root = logging.RootLogger(logging.WARNING)
        root.manager = logging.Manager(root)
        output = io.StringIO()
        with patch("joblake.logging.logging.getLogger", return_value=root), patch("sys.stderr", output):
            configure_logging()
            configure_logging()
            root.debug("hidden")
            root.info("visible")
            configure_logging("DEBUG")
            root.debug("detail")
        self.assertEqual(len(root.handlers), 1)
        self.assertNotIn("hidden", output.getvalue())
        self.assertEqual(output.getvalue().count("visible"), 1)
        self.assertIn("DEBUG root: detail", output.getvalue())
        self.assertRegex(output.getvalue(), r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z INFO")

    def test_standalone_setup_preserves_existing_handler_and_level(self):
        root = logging.RootLogger(logging.DEBUG)
        handler = logging.NullHandler()
        root.addHandler(handler)
        with patch("joblake.logging.logging.getLogger", return_value=root):
            configure_logging()
        self.assertEqual(root.handlers, [handler])
        self.assertEqual(root.level, logging.DEBUG)
