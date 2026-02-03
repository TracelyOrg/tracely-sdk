"""Span model and trace ID generation for structured tracing."""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Callable

logger = logging.getLogger("tracely")


def generate_trace_id() -> str:
    """Generate a unique trace ID (32 lowercase hex characters)."""
    return os.urandom(16).hex()


def generate_span_id() -> str:
    """Generate a unique span ID (16 lowercase hex characters)."""
    return os.urandom(8).hex()


class Span:
    """Represents a single span in a distributed trace.

    A root span has no parent. Child spans inherit trace_id from
    their parent and set parent_span_id accordingly.

    Args:
        name: Human-readable operation name (e.g., "GET /api/users").
        parent: Optional parent span — child inherits trace_id.
        span_type: "span" (default) or "pending_span" for AR3 pattern.
        kind: Span kind: INTERNAL, SERVER, CLIENT, PRODUCER, CONSUMER.
        service_name: Name of the service producing this span.
        on_end: Callback invoked when span ends, receiving the span.
    """

    __slots__ = (
        "trace_id",
        "span_id",
        "parent_span_id",
        "name",
        "span_type",
        "kind",
        "service_name",
        "start_time",
        "end_time",
        "duration_ms",
        "status_code",
        "status_message",
        "attributes",
        "_on_end",
        "_ended",
    )

    def __init__(
        self,
        name: str,
        *,
        parent: Span | None = None,
        span_type: str = "span",
        kind: str = "INTERNAL",
        service_name: str | None = None,
        on_end: Callable[[Span], None] | None = None,
    ) -> None:
        if parent is not None:
            self.trace_id = parent.trace_id
            self.parent_span_id = parent.span_id
        else:
            self.trace_id = generate_trace_id()
            self.parent_span_id: str | None = None

        self.span_id = generate_span_id()
        self.name = name
        self.span_type = span_type
        self.kind = kind
        self.service_name = service_name
        self.start_time: float = time.time()
        self.end_time: float | None = None
        self.duration_ms: float | None = None
        self.status_code: str = "UNSET"
        self.status_message: str = ""
        self.attributes: dict[str, str] = {}
        self._on_end = on_end
        self._ended = False

    def set_attribute(self, key: str, value: Any) -> None:
        """Attach a key-value attribute to the span.

        Values are converted to strings. No-op if span is already ended.
        """
        if self._ended:
            return
        self.attributes[key] = str(value)

    def set_status(self, code: str, message: str = "") -> None:
        """Set the span's status code and optional message.

        No-op if span is already ended.
        """
        if self._ended:
            return
        self.status_code = code
        self.status_message = message

    def end(self) -> None:
        """Finalize the span, computing duration and invoking on_end callback.

        Idempotent — second call is a no-op.
        """
        if self._ended:
            return
        self._ended = True
        self.end_time = time.time()
        self.duration_ms = (self.end_time - self.start_time) * 1000

        if self._on_end is not None:
            try:
                self._on_end(self)
            except Exception:
                logger.debug("Error in span on_end callback", exc_info=True)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the span to a dict suitable for transport."""
        return {
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "span_name": self.name,
            "span_type": self.span_type,
            "kind": self.kind,
            "service_name": self.service_name,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_ms": self.duration_ms,
            "status_code": self.status_code,
            "status_message": self.status_message,
            "attributes": dict(self.attributes),
        }
