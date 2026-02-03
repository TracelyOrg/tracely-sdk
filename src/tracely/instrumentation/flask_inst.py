"""Flask auto-instrumentation (WSGI middleware).

Provides a WSGI middleware that wraps Flask (or any WSGI) applications
to create structured Span objects for each HTTP request, with full trace
hierarchy support via context propagation.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Iterable

from tracely.context import _span_context
from tracely.instrumentation.base import BaseInstrumentor
from tracely.span import Span

logger = logging.getLogger("tracely")


class TracelyWSGIMiddleware:
    """WSGI middleware that creates root spans for HTTP requests.

    Creates a Span object with trace_id and span_id, sets it as the
    active span via context propagation, and captures HTTP attributes.
    """

    def __init__(
        self,
        app: Callable[..., Iterable[bytes]],
        on_span: Callable[[dict[str, Any]], None] | None = None,
        service_name: str | None = None,
        on_end: Callable[[Span], None] | None = None,
    ) -> None:
        self.app = app
        self._on_span = on_span
        self._service_name = service_name
        self._on_end = on_end

    def __call__(
        self,
        environ: dict[str, Any],
        start_response: Callable[..., Any],
    ) -> Iterable[bytes]:
        method = environ.get("REQUEST_METHOD", "UNKNOWN")
        path = environ.get("PATH_INFO", "/")
        query = environ.get("QUERY_STRING", "")

        span = Span(
            name=f"{method} {path}",
            kind="SERVER",
            service_name=self._service_name,
            on_end=self._on_end,
        )
        span.set_attribute("http.method", method)
        span.set_attribute("http.route", path)
        span.set_attribute("http.query", query)

        status_code = 0

        def wrapped_start_response(
            status: str, headers: list[Any], exc_info: Any = None
        ) -> Any:
            nonlocal status_code
            try:
                status_code = int(status.split(" ", 1)[0])
            except (ValueError, IndexError):
                status_code = 0
            return start_response(status, headers, exc_info)

        with _span_context(span):
            try:
                result = self.app(environ, wrapped_start_response)
                return result
            except Exception as exc:
                span.set_status("ERROR", str(exc))
                span.set_attribute("error", "true")
                span.set_attribute("error.type", type(exc).__name__)
                span.set_attribute("error.message", str(exc))
                raise
            finally:
                span.set_attribute("http.status_code", str(status_code))
                span.end()
                if self._on_span is not None:
                    try:
                        self._on_span(span.to_dict())
                    except Exception:
                        logger.debug("Error in on_span callback", exc_info=True)


class FlaskInstrumentor(BaseInstrumentor):
    """Instruments Flask applications with WSGI middleware wrapping."""

    def __init__(self, framework_info: Any) -> None:
        super().__init__(framework_info)
        self._active = False

    def activate(self) -> None:
        self._active = True
        logger.info("TRACELY: Flask instrumentation activated")

    def deactivate(self) -> None:
        self._active = False
        logger.debug("TRACELY: Flask instrumentation deactivated")

    @property
    def is_active(self) -> bool:
        return self._active

    @staticmethod
    def wrap_app(
        app: Callable[..., Iterable[bytes]],
        on_span: Callable[[dict[str, Any]], None] | None = None,
        service_name: str | None = None,
        on_end: Callable[[Span], None] | None = None,
    ) -> TracelyWSGIMiddleware:
        """Wrap a WSGI app with TRACELY middleware."""
        return TracelyWSGIMiddleware(
            app=app, on_span=on_span, service_name=service_name, on_end=on_end,
        )
