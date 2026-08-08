"""Colorized, debug-friendly logging for the application.

Every runtime module should create its logger with
``logging.getLogger(__name__)``. Call :func:`configure_logging` once from
``app/main.py`` to configure the shared root logger.

Set ``LOG_LEVEL=DEBUG`` for source locations and detailed application logs.
Colors are enabled for interactive terminals and can be controlled explicitly
with ``LOG_COLOR=always`` or ``LOG_COLOR=never``.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Final, Literal, cast

_ColorMode = Literal["auto", "always", "never"]

_RESET: Final = "\033[0m"
_DIM: Final = "\033[2m"
_SOURCE_COLOR: Final = "\033[35m"  # magenta
_LEVEL_WIDTH: Final = 6
_LOGGER_WIDTH: Final = 16
_LEVEL_COLORS: Final[dict[int, str]] = {
    logging.DEBUG: "\033[36m",  # cyan
    logging.INFO: "\033[32m",  # green
    logging.WARNING: "\033[33m",  # yellow
    logging.ERROR: "\033[31m",  # red
    logging.CRITICAL: "\033[1;41m",  # bold white on red
}
_STANDARD_FORMAT: Final = (
    "%(timestamp_display)s │ %(level_display)s │ %(logger_display)s │ %(message)s"
)
_DEBUG_FORMAT: Final = (
    "%(timestamp_display)s │ %(level_display)s │ %(logger_display)s │ %(source_display)s │ "
    "%(message)s"
)
_DATE_FORMAT: Final = "%H:%M:%S"


class ColoredFormatter(logging.Formatter):
    """Format records with colored severity labels when output supports ANSI."""

    def __init__(self, *, use_color: bool, debug: bool) -> None:
        """Initialize the formatter.

        Args:
            use_color: Whether to wrap log levels in ANSI color codes.
            debug: Whether to include the source filename and line number.
        """
        super().__init__(
            fmt=_DEBUG_FORMAT if debug else _STANDARD_FORMAT,
            datefmt=_DATE_FORMAT,
        )
        self._use_color = use_color

    def format(self, record: logging.LogRecord) -> str:
        """Format one log record without mutating it for other handlers."""
        copied_record = logging.makeLogRecord(record.__dict__.copy())
        color = _LEVEL_COLORS.get(copied_record.levelno, _RESET)
        level = f"{copied_record.levelname:^{_LEVEL_WIDTH}}"
        logger_name = _fit_column(copied_record.name, _LOGGER_WIDTH)
        logger_left_padding, logger_right_padding = _center_padding(
            _LOGGER_WIDTH - len(logger_name)
        )

        timestamp = self.formatTime(copied_record, self.datefmt)
        copied_record.timestamp_display = _colorize(timestamp, _DIM, self._use_color)
        copied_record.level_display = _colorize(level, color, self._use_color)
        copied_record.logger_display = (
            f"[ {' ' * logger_left_padding}{_colorize(logger_name, color, self._use_color)}"
            f"{' ' * logger_right_padding} ]"
        )
        copied_record.source_display = (
            f"[ {_colorize(copied_record.filename, _SOURCE_COLOR, self._use_color)}:"
            f"{copied_record.lineno} ]"
        )
        return super().format(copied_record)


def _colorize(value: str, color: str, enabled: bool) -> str:
    """Wrap text in an ANSI color sequence when color output is enabled."""
    return f"{color}{value}{_RESET}" if enabled else value


def _fit_column(value: str, width: int) -> str:
    """Truncate a column value with an ellipsis when it exceeds its width."""
    return value if len(value) <= width else f"{value[: width - 1]}…"


def _center_padding(total: int) -> tuple[int, int]:
    """Split padding so a value is visually centered in its column."""
    return total // 2, total - total // 2


def configure_logging(level: str | None = None) -> None:
    """Configure the root logger once at process startup.

    Args:
        level: Log level name (``"DEBUG"``, ``"INFO"``, etc.). Defaults to
            ``LOG_LEVEL`` or ``"INFO"`` when neither is provided.

    Raises:
        ValueError: If the requested log level or color mode is invalid.
    """
    resolved_level = _resolve_level(level or os.getenv("LOG_LEVEL", "INFO"))
    color_mode = _resolve_color_mode(os.getenv("LOG_COLOR", "auto"))
    use_color = _should_use_color(color_mode)

    handler = logging.StreamHandler()
    handler.setFormatter(
        ColoredFormatter(use_color=use_color, debug=resolved_level <= logging.DEBUG)
    )
    logging.basicConfig(level=resolved_level, handlers=[handler])


def _resolve_level(level: str) -> int:
    """Return a validated numeric logging level for a user-provided name."""
    normalized_level = level.upper()
    resolved_level = logging.getLevelName(normalized_level)
    if not isinstance(resolved_level, int):
        valid_levels = ", ".join(logging.getLevelNamesMapping())
        raise ValueError(f"Invalid log level {level!r}; expected one of: {valid_levels}")
    return resolved_level


def _resolve_color_mode(value: str) -> _ColorMode:
    """Validate and normalize the ``LOG_COLOR`` environment value."""
    normalized_value = value.lower()
    if normalized_value not in {"auto", "always", "never"}:
        raise ValueError("Invalid LOG_COLOR value; expected 'auto', 'always', or 'never'")
    return cast(_ColorMode, normalized_value)


def _should_use_color(mode: _ColorMode) -> bool:
    """Decide whether terminal colors should be emitted."""
    if mode == "always":
        return True
    if mode == "never" or os.getenv("NO_COLOR") is not None:
        return False
    return sys.stderr.isatty()
