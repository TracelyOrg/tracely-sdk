"""Django auto-instrumentation (Django middleware).

Provides a Django-style middleware that creates structured Span objects
for each HTTP request, with full trace hierarchy support via context
propagation.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from tracely.context import _span_context
from tracely.instrumentation.base import BaseInstrumentor
from tracely.span import Span

logger = logging.getLogger("tracely")


class TracelyDjangoMiddleware:
    """Django middleware that creates root spans for HTTP requests.

    Follows Django's middleware protocol: __init__(get_response) + __call__(request).
    Creates a Span object with trace_id and span_id, sets it as the active span,
    and captures HTTP attributes.
    """

    def __init__(
        self,
        get_response: Callable[..., Any],
        on_span: Callable[[dict[str, Any]], None] | None = None,
        service_name: str | None = None,
        on_end: Callable[[Span], None] | None = None,
    ) -> None:
        self.get_response = get_response
        self._on_span = on_span
        self._service_name = service_name
        self._on_end = on_end

    def __call__(self, request: Any) -> Any:
        method = getattr(request, "method", "UNKNOWN")
        path = getattr(request, "path", "/")
        meta = getattr(request, "META", {})
        query = meta.get("QUERY_STRING", "")

        span = Span(
            name=f"{method} {path}",
            kind="SERVER",
            service_name=self._service_name,
            on_end=self._on_end,
        )
        span.set_attribute("http.method", method)
        span.set_attribute("http.route", path)
        span.set_attribute("http.query", query)

        with _span_context(span):
            try:
                response = self.get_response(request)
                span.set_attribute("http.status_code", str(getattr(response, "status_code", 0)))
                return response
            except Exception as exc:
                span.set_status("ERROR", str(exc))
                span.set_attribute("error", "true")
                span.set_attribute("error.type", type(exc).__name__)
                span.set_attribute("error.message", str(exc))
                raise
            finally:
                span.end()
                if self._on_span is not None:
                    try:
                        self._on_span(span.to_dict())
                    except Exception:
                        logger.debug("Error in on_span callback", exc_info=True)


class DjangoInstrumentor(BaseInstrumentor):
    """Instruments Django applications with middleware."""

    def __init__(self, framework_info: Any) -> None:
        super().__init__(framework_info)
        self._active = False

    def activate(self) -> None:
        self._active = True
        logger.info("TRACELY: Django instrumentation activated")

    def deactivate(self) -> None:
        self._active = False
        logger.debug("TRACELY: Django instrumentation deactivated")

    @property
    def is_active(self) -> bool:
        return self._active
