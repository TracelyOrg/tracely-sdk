"""Django auto-instrumentation (Django middleware).

Provides a Django-style middleware that creates structured Span objects
for each HTTP request, with full trace hierarchy support via context
propagation. Captures full request/response data (FR6/FR7).
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


def _extract_django_headers(meta: dict[str, Any]) -> dict[str, str]:
    """Extract HTTP headers from Django request.META dict.

    Django stores headers as HTTP_<NAME> with underscores replacing hyphens.
    CONTENT_TYPE and CONTENT_LENGTH are special cases without HTTP_ prefix.
    """
    headers: dict[str, str] = {}
    for key, value in meta.items():
        if key.startswith("HTTP_"):
            header_name = key[5:].lower().replace("_", "-")
            headers[header_name] = str(value)
        elif key == "CONTENT_TYPE":
            headers["content-type"] = str(value)
        elif key == "CONTENT_LENGTH":
            headers["content-length"] = str(value)
    return headers


def _resolve_django_route(path: str) -> dict[str, str]:
    """Use Django's URL resolver to match the path and extract metadata.

    Returns a dict of span attributes if a matching route is found.
    """
    try:
        from django.urls import resolve

        match = resolve(path)
        attrs: dict[str, str] = {}
        if hasattr(match, "route") and match.route:
            attrs["http.route"] = match.route
        attrs["code.function"] = match.func.__name__
        try:
            attrs["code.filepath"] = inspect.getfile(match.func)
        except (TypeError, OSError):
            pass
        if match.url_name:
            attrs["django.url_name"] = match.url_name
        if match.app_name:
            attrs["django.app_name"] = match.app_name
        return attrs
    except Exception:
        logger.debug("Error resolving Django route", exc_info=True)
        return {}


class TracelyDjangoMiddleware:
    """Django middleware that creates root spans for HTTP requests.

    Follows Django's middleware protocol: __init__(get_response) + __call__(request).
    Creates a Span object with trace_id and span_id, sets it as the active span,
    and captures HTTP attributes including full request/response data.
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
        # Fall back to the SDK-configured service_name when not passed explicitly
        if service_name is None:
            from tracely.sdk import _sdk_instance
            inst = _sdk_instance()
            if inst is not None:
                service_name = inst.config.service_name
        self._service_name = service_name
        self._on_end = on_end

    def __call__(self, request: Any) -> Any:
        method = getattr(request, "method", "UNKNOWN")
        path = getattr(request, "path", "/")
        meta = getattr(request, "META", {})
        query = meta.get("QUERY_STRING", "")

        # Build full URL from Django request
        scheme = getattr(request, "scheme", "http")
        host = meta.get("HTTP_HOST", "localhost")
        full_url = build_url(scheme, host, path, query)

        # Extract request headers and body
        req_headers = _extract_django_headers(meta)
        req_content_type = req_headers.get("content-type", "")
        req_body = getattr(request, "body", b"")

        span = Span(
            name=f"{method} {path}",
            kind="SERVER",
            service_name=self._service_name,
            on_end=self._on_end or on_span_end,
        )
        span.set_attribute("http.route", path)
        span.set_attribute("http.query", query)

        # Standard OTEL attributes from request
        span.set_attribute("http.host", host)
        span.set_attribute("http.scheme", scheme)
        server_port = meta.get("SERVER_PORT")
        if server_port:
            span.set_attribute("net.host.port", server_port)
        user_agent = req_headers.get("user-agent", "")
        if user_agent:
            span.set_attribute("http.user_agent", user_agent)

        # AR3: Export pending_span immediately for real-time dashboard
        on_span_start(span)

        with _span_context(span):
            status_code = 0
            resp_headers_dict: dict[str, str] = {}
            resp_content_type = ""
            resp_body: bytes = b""
            response = None
            try:
                response = self.get_response(request)

                # Resolve Django route after response (resolver is available)
                route_attrs = _resolve_django_route(path)
                for key, value in route_attrs.items():
                    span.set_attribute(key, value)

                # Extract response data
                try:
                    for name, value in response.items():
                        resp_headers_dict[str(name).lower()] = str(value)
                except Exception:
                    pass
                resp_content_type = resp_headers_dict.get("content-type", "")
                resp_body = getattr(response, "content", b"")
                status_code = getattr(response, "status_code", 0)

                return response
            except Exception as exc:
                span.set_status("ERROR", str(exc))
                span.set_attribute("error", "true")
                span.set_attribute("error.type", type(exc).__name__)
                span.set_attribute("error.message", str(exc))
                span.set_attribute("exception.stacktrace", traceback.format_exc())
                # If the exception occurred before we got a response,
                # status_code is still 0. An unhandled exception means 500.
                if status_code == 0:
                    status_code = 500
                raise
            finally:
                # Capture request data (FR6) — always, even on error
                capture_request_data(
                    span,
                    method=method,
                    url=full_url,
                    headers=req_headers,
                    body=req_body,
                    content_type=req_content_type,
                    query_params=query,
                )
                # Capture response data (FR7) — always, even on error
                capture_response_data(
                    span,
                    status_code=status_code,
                    headers=resp_headers_dict,
                    body=resp_body,
                    content_type=resp_content_type,
                )
                span.end()
                if self._on_span is not None:
                    try:
                        self._on_span(span.to_dict())
                    except Exception:
                        logger.debug("Error in on_span callback", exc_info=True)


def instrument_django(*, service_name: str | None = None) -> None:
    """Instrument a Django application with Tracely tracing.

    Programmatically inserts TracelyDjangoMiddleware at the top of
    Django's MIDDLEWARE list. Call this after django.setup() or in
    AppConfig.ready().

    Args:
        service_name: Override the service name from tracely.init() config.
    """
    from django.conf import settings

    mw = "tracely.instrumentation.django_inst.TracelyDjangoMiddleware"
    if mw not in settings.MIDDLEWARE:
        settings.MIDDLEWARE.insert(0, mw)
