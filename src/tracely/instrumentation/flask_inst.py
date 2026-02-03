"""Flask auto-instrumentation (WSGI middleware).

Provides a WSGI middleware that wraps Flask (or any WSGI) applications
to create spans for each HTTP request, capturing method, path, status
code, and duration.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Iterable

from tracely.instrumentation.base import BaseInstrumentor

logger = logging.getLogger("tracely")


class TracelyWSGIMiddleware:
    """WSGI middleware that creates spans for HTTP requests.

    Captures: method, route, query string, status code, duration, errors.
    """

    def __init__(
        self,
        app: Callable[..., Iterable[bytes]],
        on_span: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.app = app
        self._on_span = on_span

    def __call__(
        self,
        environ: dict[str, Any],
        start_response: Callable[..., Any],
    ) -> Iterable[bytes]:
        method = environ.get("REQUEST_METHOD", "UNKNOWN")
        path = environ.get("PATH_INFO", "/")
        query = environ.get("QUERY_STRING", "")

        span_data: dict[str, Any] = {
            "span_type": "http",
            "http.method": method,
            "http.route": path,
            "http.query": query,
            "http.status_code": 0,
            "duration_ms": 0,
            "error": False,
        }

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

        start = time.perf_counter()
        try:
            result = self.app(environ, wrapped_start_response)
            return result
        except Exception as exc:
            span_data["error"] = True
            span_data["error.type"] = type(exc).__name__
            span_data["error.message"] = str(exc)
            raise
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000
            span_data["duration_ms"] = round(elapsed_ms, 3)
            span_data["http.status_code"] = status_code
            if self._on_span is not None:
                try:
                    self._on_span(span_data)
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
    ) -> TracelyWSGIMiddleware:
        """Wrap a WSGI app with TRACELY middleware."""
        return TracelyWSGIMiddleware(app=app, on_span=on_span)
