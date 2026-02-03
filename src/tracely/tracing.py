"""Public tracing API for custom spans (FR58, FR59).

Provides the `span()` context manager for developers to create
custom spans within their application code.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Callable, Generator

from tracely.context import get_current_span, _span_context
from tracely.span import Span


@contextmanager
def span(
    name: str,
    *,
    kind: str = "INTERNAL",
    service_name: str | None = None,
    on_end: Callable[[Span], None] | None = None,
) -> Generator[Span, None, None]:
    """Create a custom span as a child of the currently active span.

    If no span is active, creates a root span. The span is automatically
    ended when the context exits (including on exception).

    Usage::

        with tracely.span("my-operation") as s:
            s.set_attribute("key", "value")
            # do work
        # span is ended here

    Args:
        name: Human-readable operation name.
        kind: Span kind (INTERNAL, CLIENT, PRODUCER, CONSUMER).
        service_name: Optional service name override.
        on_end: Optional callback invoked when span ends.
    """
    parent = get_current_span()
    s = Span(
        name=name,
        parent=parent,
        kind=kind,
        service_name=service_name,
        on_end=on_end,
    )

    with _span_context(s):
        try:
            yield s
        finally:
            s.end()
