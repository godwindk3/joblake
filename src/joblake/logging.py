"""Console logging shared by the CLI and standalone utility commands."""

import logging
import time


class UTCFormatter(logging.Formatter):
    converter = time.gmtime


def configure_logging(level: str | None = None) -> None:
    """Configure stderr once; keep embedding applications' handlers intact."""
    root = logging.getLogger()
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(UTCFormatter(
            "%(asctime)sZ %(levelname)s %(name)s: %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        ))
        root.addHandler(handler)
        root.setLevel(level or "INFO")
    elif level is not None:
        root.setLevel(level)
