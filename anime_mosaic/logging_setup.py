"""Rotating file logging shared by the UI and the CLI."""

from __future__ import annotations

import logging
import logging.handlers
import sys

from .core.settings import LOG_PATH

_LOGGER_NAME = "anime_mosaic"
_configured = False


def setup_logging(console: bool = False) -> logging.Logger:
    """Configure a rotating log file once; optionally mirror to the console."""
    global _configured
    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(logging.INFO)
    if not _configured:
        formatter = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s")
        try:
            file_handler = logging.handlers.RotatingFileHandler(
                LOG_PATH, maxBytes=2 * 1024 * 1024, backupCount=2, encoding="utf-8"
            )
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
        except OSError:
            pass
        _configured = True
    if console and not any(isinstance(h, logging.StreamHandler) and h.stream is sys.stderr for h in logger.handlers):
        stream = logging.StreamHandler(sys.stderr)
        stream.setFormatter(logging.Formatter("%(levelname)-7s %(message)s"))
        logger.addHandler(stream)
    return logger


def get_logger() -> logging.Logger:
    return logging.getLogger(_LOGGER_NAME)
