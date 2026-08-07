"""Shared logging configuration.

Every module gets its own logger the standard way -
``logger = logging.getLogger(__name__)`` at module level - that's already
"shared" behavior, since it's the stdlib's global logger hierarchy. What
actually needs to be centralized, and lives here, is the one-time
*configuration* of that hierarchy (format, level, handler): call
``configure_logging()`` exactly once, from ``app/main.py``, before
anything else runs - never per-request, never per-module.
"""

from __future__ import annotations

import logging
import os

_LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s - %(message)s"


def configure_logging(level: str | None = None) -> None:
    """Configure the root logger once, at process startup.

    Args:
        level: Log level name (``"DEBUG"``, ``"INFO"``, ...). Defaults to
            the ``LOG_LEVEL`` env var, or ``"INFO"`` if that's unset too.
    """
    resolved_level = (level or os.getenv("LOG_LEVEL", "INFO")).upper()
    logging.basicConfig(level=resolved_level, format=_LOG_FORMAT)
