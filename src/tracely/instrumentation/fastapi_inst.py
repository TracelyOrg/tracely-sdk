"""FastAPI auto-instrumentation (ASGI middleware).

Wraps FastAPI (or any ASGI) applications with middleware that creates
structured Span objects for each HTTP request, with full trace hierarchy
support via context propagation.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from tracely.context import _span_context
from tracely.instrumentation.base import BaseInstrumentor
from tracely.span import Span

logger = logging.getLogger("tracely")

# Type aliases for ASGI protocol
Scope = dict[str, Any]
Receive = Callable[..., Any]
Send = Callable[..., Any]
ASGIApp = Callable[..., Any]


class TracelyASGIMiddleware:
    """ASGI middleware that creates root spans for HTTP requests.

    Creates a Span object with trace_id and span_id, sets it as the
    active span via context propagation, and captures HTTP attributes.
    Non-HTTP scopes (lifespan, websocket) pass through untouched.
    """

    def __init__(
        self,
        app: ASGIApp,
        on_span: Callable[[dict[str, Any]], None] | None = None,
        service_name: str | None = None,
        on_end: Callable[[Span], None] | None = None,
    ) -> None:
        self.app = app
        self._on_span = on_span
        self._service_name = service_name
        self._on_end = on_end

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "UNKNOWN")
        path = scope.get("path", "/")
        query = scope.get("query_string", b"").decode("utf-8", errors="replace")

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

        async def send_wrapper(message: dict[str, Any]) -> None:
            nonlocal status_code
            if message.get("type") == "http.response.start":
                status_code = message.get("status", 0)
            await send(message)

        with _span_context(span):
            try:
                await self.app(scope, receive, send_wrapper)
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
        service_name: str | None = None,
        on_end: Callable[[Span], None] | None = None,
    ) -> TracelyASGIMiddleware:
        """Wrap an ASGI app with TRACELY middleware."""
        return TracelyASGIMiddleware(
            app=app, on_span=on_span, service_name=service_name, on_end=on_end,
        )
