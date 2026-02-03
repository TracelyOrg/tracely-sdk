"""Public logging API for adding events to the active span.

Provides debug(), info(), warning(), error() functions that attach
log events to the currently active span. All functions are fail-silent
and no-op when no span is active.
"""

from __future__ import annotations

from tracely.context import get_current_span


def debug(message: str, **attributes: str) -> None:
    """Add a DEBUG event to the active span."""
    span = get_current_span()
    if span is not None:
        span.add_event(message, level="DEBUG", attributes=attributes or None)


def info(message: str, **attributes: str) -> None:
    """Add an INFO event to the active span."""
    span = get_current_span()
    if span is not None:
        span.add_event(message, level="INFO", attributes=attributes or None)


def warning(message: str, **attributes: str) -> None:
    """Add a WARNING event to the active span."""
    span = get_current_span()
    if span is not None:
        span.add_event(message, level="WARNING", attributes=attributes or None)


def error(message: str, **attributes: str) -> None:
    """Add an ERROR event to the active span."""
    span = get_current_span()
    if span is not None:
        span.add_event(message, level="ERROR", attributes=attributes or None)
