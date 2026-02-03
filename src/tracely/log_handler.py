"""Log event handler for span association (FR60).

Captures log events and associates them with the currently active
span's span_id and trace_id. Only captures events when a span is
active — otherwise silently discards them.

All operations are fail-silent to avoid crashing the host application.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from tracely.context import get_current_span

_logger = logging.getLogger("tracely")


class TracelyLogHandler(logging.Handler):
    """Logging handler that associates log events with active spans.

    Args:
        on_event: Callback invoked with a dict for each captured log event.
                  If None, events are silently discarded.
    """

    def __init__(self, on_event: Callable[[dict[str, Any]], None] | None = None) -> None:
        super().__init__()
        self._on_event = on_event

    def emit(self, record: logging.LogRecord) -> None:
        try:
            span = get_current_span()
            if span is None:
                return

            event: dict[str, Any] = {
                "trace_id": span.trace_id,
                "span_id": span.span_id,
                "level": record.levelname,
                "message": record.getMessage(),
                "timestamp": record.created,
                "logger_name": record.name,
            }

            if record.exc_info and record.exc_info[1] is not None:
                exc = record.exc_info[1]
                event["exception_type"] = type(exc).__name__
                event["exception_message"] = str(exc)

            if self._on_event is not None:
                self._on_event(event)
        except Exception:
            _logger.debug("Error in TracelyLogHandler.emit", exc_info=True)
