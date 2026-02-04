"""FastAPI auto-instrumentation (ASGI middleware).

Wraps FastAPI (or any ASGI) applications with middleware that creates
structured Span objects for each HTTP request, with full trace hierarchy
support via context propagation. Captures full request/response data (FR6/FR7).
"""

from __future__ import annotations

import inspect
import json
import logging
import traceback
from typing import Any, Callable

from tracely.capture import build_url, capture_request_data, capture_response_data
from tracely.context import _span_context
from tracely.span import Span
from tracely.span_processor import on_span_end, on_span_start

logger = logging.getLogger("tracely")

# Type aliases for ASGI protocol
Scope = dict[str, Any]
Receive = Callable[..., Any]
Send = Callable[..., Any]
ASGIApp = Callable[..., Any]


def _extract_header_value(
    headers: list[tuple[bytes, bytes]], name: bytes,
) -> str:
    """Extract a single header value from ASGI header list (case-insensitive)."""
    name_lower = name.lower()
    for hdr_name, hdr_value in headers:
        if hdr_name.lower() == name_lower:
            return hdr_value.decode("utf-8", errors="replace")
    return ""


def _resolve_route(app: Any, scope: Scope) -> dict[str, str]:
    """Match ASGI scope against Starlette/FastAPI routes for rich metadata.

    Returns a dict of span attributes if a matching route is found.
    """
    try:
        from starlette.routing import Match

        routes = getattr(app, "routes", None)
        if routes is None:
            return {}

        for route in routes:
            match, child_scope = route.matches(scope)
            if match == Match.FULL:
                attrs: dict[str, str] = {"http.route": route.path}
                endpoint = getattr(route, "endpoint", None)
                if endpoint is not None:
                    attrs["code.function"] = endpoint.__name__
                    try:
                        attrs["code.filepath"] = inspect.getfile(endpoint)
                    except (TypeError, OSError):
                        pass
                tags = getattr(route, "tags", None)
                if tags:
                    attrs["fastapi.route.tags"] = ",".join(str(t) for t in tags)
                path_params = child_scope.get("path_params", {})
                if path_params:
                    attrs["fastapi.path_params"] = json.dumps(path_params)
                return attrs
    except Exception:
        logger.debug("Error resolving FastAPI route", exc_info=True)
    return {}


class TracelyASGIMiddleware:
    """ASGI middleware that creates root spans for HTTP requests.

    Creates a Span object with trace_id and span_id, sets it as the
    active span via context propagation, and captures HTTP attributes
    including full request/response data (headers, body, URL).
    Non-HTTP scopes (lifespan, websocket) pass through untouched.
    """

    def __init__(
        self,
        app: ASGIApp,
        on_span: Callable[[dict[str, Any]], None] | None = None,
        service_name: str | None = None,
        on_end: Callable[[Span], None] | None = None,
        app_ref: Any | None = None,
    ) -> None:
        self.app = app
        self._on_span = on_span
        # Fall back to the SDK-configured service_name when not passed explicitly
        if service_name is None:
            from tracely.sdk import _sdk_instance
            inst = _sdk_instance()
            if inst is not None:
                service_name = inst.config.service_name
        self._service_name = service_name
        self._on_end = on_end
        self._app_ref = app_ref

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "UNKNOWN")
        path = scope.get("path", "/")
        query = scope.get("query_string", b"").decode("utf-8", errors="replace")
        raw_headers: list[tuple[bytes, bytes]] = scope.get("headers", [])

        # Build full URL from ASGI scope
        scheme = scope.get("scheme", "http")
        server = scope.get("server")
        if server:
            host = server[0]
            port = server[1]
            # Include port only if non-standard
            if (scheme == "https" and port != 443) or (scheme == "http" and port != 80):
                host_str = f"{host}:{port}"
            else:
                host_str = host
        else:
            host_str = "localhost"
            port = 80
        full_url = build_url(scheme, host_str, path, query)

        # Extract content type from request headers
        req_content_type = _extract_header_value(raw_headers, b"content-type")

        span = Span(
            name=f"{method} {path}",
            kind="SERVER",
            service_name=self._service_name,
            on_end=self._on_end or on_span_end,
        )
        span.set_attribute("http.route", path)
        span.set_attribute("http.query", query)

        # Resolve route and enrich span when app_ref is available
        if self._app_ref is not None:
            route_attrs = _resolve_route(self._app_ref, scope)
            for key, value in route_attrs.items():
                span.set_attribute(key, value)

        # Standard OTEL attributes from request
        span.set_attribute("http.host", host_str)
        span.set_attribute("http.scheme", scheme)
        if server:
            span.set_attribute("net.host.port", str(server[1]))
        user_agent = _extract_header_value(raw_headers, b"user-agent")
        if user_agent:
            span.set_attribute("http.user_agent", user_agent)

        # AR3: Export pending_span immediately for real-time dashboard
        on_span_start(span)

        # Buffer request body so the app can still read it
        request_body = b""
        body_consumed = False

        async def receive_wrapper() -> dict[str, Any]:
            nonlocal request_body, body_consumed
            message = await receive()
            if message.get("type") == "http.request" and not body_consumed:
                chunk = message.get("body", b"")
                request_body += chunk
                if not message.get("more_body", False):
                    body_consumed = True
            return message

        # Capture response data via send wrapper
        status_code = 0
        response_headers: list[tuple[bytes, bytes]] = []
        response_body_chunks: list[bytes] = []
        resp_content_type = ""

        async def send_wrapper(message: dict[str, Any]) -> None:
            nonlocal status_code, response_headers, resp_content_type
            if message.get("type") == "http.response.start":
                status_code = message.get("status", 0)
                response_headers = message.get("headers", [])
                resp_content_type = _extract_header_value(response_headers, b"content-type")
            elif message.get("type") == "http.response.body":
                chunk = message.get("body", b"")
                if chunk:
                    response_body_chunks.append(chunk)
            await send(message)

        with _span_context(span):
            try:
                await self.app(scope, receive_wrapper, send_wrapper)
            except Exception as exc:
                span.set_status("ERROR", str(exc))
                span.set_attribute("error", "true")
                span.set_attribute("error.type", type(exc).__name__)
                span.set_attribute("error.message", str(exc))
                span.set_attribute("exception.stacktrace", traceback.format_exc())
                # If the exception occurred before the framework sent a
                # response (send_wrapper never called), status_code is still 0.
                # An unhandled server exception means 500.
                if status_code == 0:
                    status_code = 500
                raise
            finally:
                # Capture request data (FR6)
                capture_request_data(
                    span,
                    method=method,
                    url=full_url,
                    headers=raw_headers,
                    body=request_body,
                    content_type=req_content_type,
                    query_params=query,
                )

                # Capture response data (FR7)
                response_body = b"".join(response_body_chunks)
                capture_response_data(
                    span,
                    status_code=status_code,
                    headers=response_headers,
                    body=response_body,
                    content_type=resp_content_type,
                )

                span.end()
                if self._on_span is not None:
                    try:
                        self._on_span(span.to_dict())
                    except Exception:
                        logger.debug("Error in on_span callback", exc_info=True)


def instrument_fastapi(app: Any, *, service_name: str | None = None) -> None:
    """Instrument a FastAPI application with Tracely tracing.

    Adds TracelyASGIMiddleware to the app with full route resolution,
    handler metadata, and automatic config inheritance from tracely.init().

    Args:
        app: A FastAPI application instance.
        service_name: Override the service name from tracely.init() config.
    """
    from tracely.sdk import _sdk_instance

    inst = _sdk_instance()
    svc = service_name or (inst.config.service_name if inst else None)
    app.add_middleware(TracelyASGIMiddleware, service_name=svc, app_ref=app)
