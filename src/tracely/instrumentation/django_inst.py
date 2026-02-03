"""Django auto-instrumentation (Django middleware).

Provides a Django-style middleware that creates spans for each HTTP
request, capturing method, path, status code, and duration.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable

from tracely.instrumentation.base import BaseInstrumentor

logger = logging.getLogger("tracely")


class TracelyDjangoMiddleware:
    """Django middleware that creates spans for HTTP requests.

    Follows Django's middleware protocol: __init__(get_response) + __call__(request).
    Captures: method, route, query string, status code, duration, errors.
    """

    def __init__(
        self,
        get_response: Callable[..., Any],
        on_span: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.get_response = get_response
        self._on_span = on_span

    def __call__(self, request: Any) -> Any:
        method = getattr(request, "method", "UNKNOWN")
        path = getattr(request, "path", "/")
        meta = getattr(request, "META", {})
        query = meta.get("QUERY_STRING", "")

        span_data: dict[str, Any] = {
            "span_type": "http",
            "http.method": method,
            "http.route": path,
            "http.query": query,
            "http.status_code": 0,
            "duration_ms": 0,
            "error": False,
        }

        start = time.perf_counter()
        try:
            response = self.get_response(request)
            span_data["http.status_code"] = getattr(response, "status_code", 0)
            return response
        except Exception as exc:
            span_data["error"] = True
            span_data["error.type"] = type(exc).__name__
            span_data["error.message"] = str(exc)
            raise
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000
            span_data["duration_ms"] = round(elapsed_ms, 3)
            if self._on_span is not None:
                try:
                    self._on_span(span_data)
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
