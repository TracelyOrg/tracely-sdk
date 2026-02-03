"""FastAPI auto-instrumentation (ASGI middleware).

Wraps FastAPI (or any ASGI) applications with middleware that creates
spans for each HTTP request, capturing method, route, status code,
and duration.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable

from tracely.instrumentation.base import BaseInstrumentor

logger = logging.getLogger("tracely")

# Type aliases for ASGI protocol
Scope = dict[str, Any]
Receive = Callable[..., Any]
Send = Callable[..., Any]
ASGIApp = Callable[..., Any]


class TracelyASGIMiddleware:
    """ASGI middleware that creates spans for HTTP requests.

    Captures: method, route, query string, status code, duration, errors.
    Non-HTTP scopes (lifespan, websocket) pass through untouched.
    """

    def __init__(
        self,
        app: ASGIApp,
        on_span: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.app = app
        self._on_span = on_span

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "UNKNOWN")
        path = scope.get("path", "/")
        query = scope.get("query_string", b"").decode("utf-8", errors="replace")

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

        async def send_wrapper(message: dict[str, Any]) -> None:
            nonlocal status_code
            if message.get("type") == "http.response.start":
                status_code = message.get("status", 0)
            await send(message)

        start = time.perf_counter()
        try:
            await self.app(scope, receive, send_wrapper)
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


class FastAPIInstrumentor(BaseInstrumentor):
    """Instruments FastAPI applications with ASGI middleware.

    On activate(), registers the middleware factory so it can be applied
    to FastAPI apps. The actual wrapping happens when the user's app
    is detected or when middleware is explicitly applied.
    """

    def __init__(self, framework_info: Any) -> None:
        super().__init__(framework_info)
        self._active = False

    def activate(self) -> None:
        self._active = True
        logger.info("TRACELY: FastAPI instrumentation activated")

    def deactivate(self) -> None:
        self._active = False
        logger.debug("TRACELY: FastAPI instrumentation deactivated")

    @property
    def is_active(self) -> bool:
        return self._active

    @staticmethod
    def wrap_app(
        app: ASGIApp,
        on_span: Callable[[dict[str, Any]], None] | None = None,
    ) -> TracelyASGIMiddleware:
        """Wrap an ASGI app with TRACELY middleware."""
        return TracelyASGIMiddleware(app=app, on_span=on_span)
