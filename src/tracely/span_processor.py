"""Span processor for pending span pattern (AR3).

Exports spans to SpanBuffer on both start (pending_span) and end (span),
enabling real-time dashboard updates for in-progress requests.

All operations are fail-silent — never crashes the host application.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tracely.span import Span
    from tracely.transport import SpanBuffer

logger = logging.getLogger("tracely")


class SpanProcessor:
    """Processes span lifecycle events and enqueues them to SpanBuffer.

    Args:
        buffer: SpanBuffer to enqueue span dicts into.
    """

    def __init__(self, buffer: SpanBuffer) -> None:
        self._buffer = buffer

    def on_start(self, span: Span) -> None:
        """Export a pending_span when a span starts.

        Enqueues a snapshot of the span with span_type="pending_span"
        so the dashboard can show in-progress requests.
        """
        try:
            d = span.to_dict()
            d["span_type"] = "pending_span"
            self._buffer.enqueue(d)
        except Exception:
            logger.debug("Error in SpanProcessor.on_start", exc_info=True)

    def on_end(self, span: Span) -> None:
        """Export the final span when a span ends.

        Enqueues the completed span with span_type="span".
        Suitable as Span's on_end callback.
        """
        try:
            d = span.to_dict()
            d["span_type"] = "span"
            self._buffer.enqueue(d)
        except Exception:
            logger.debug("Error in SpanProcessor.on_end", exc_info=True)
