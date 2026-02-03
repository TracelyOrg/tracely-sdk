"""Context propagation for active span tracking.

Uses Python's contextvars for async-safe, per-task span tracking.
Each async task or thread gets its own active span, preventing
cross-request contamination.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import TYPE_CHECKING, Generator

if TYPE_CHECKING:
    from tracely.span import Span

_current_span: ContextVar[Span | None] = ContextVar("_current_span", default=None)


def get_current_span() -> Span | None:
    """Return the currently active span, or None if no span is active."""
    return _current_span.get()


def set_current_span(span: Span | None, token: Token[Span | None] | None = None) -> Token[Span | None]:
    """Set the currently active span.

    Args:
        span: The span to set as active, or None to clear.
        token: Optional token from a previous set_current_span call
               to restore the prior value.

    Returns:
        A token that can be used to restore the previous value.
    """
    if token is not None:
        _current_span.reset(token)
        return token
    return _current_span.set(span)


@contextmanager
def _span_context(span: Span) -> Generator[Span, None, None]:
    """Context manager that sets span as active and restores the previous span on exit.

    Usage:
        with _span_context(my_span):
            # my_span is the active span here
        # previous span (or None) is restored
    """
    token = _current_span.set(span)
    try:
        yield span
    finally:
        _current_span.reset(token)
