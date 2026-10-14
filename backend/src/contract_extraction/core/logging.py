"""Logging setup shared by every entry point (CLI now; API and worker later)."""

from __future__ import annotations

import logging

FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
_NOISY = ("httpx", "httpcore", "urllib3", "sqlalchemy.engine")


def setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(level=level, format=FORMAT, force=True)
    for name in _NOISY:
        logging.getLogger(name).setLevel(max(logging.WARNING, logging.getLevelName(level)))
