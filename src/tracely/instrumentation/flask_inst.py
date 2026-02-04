"""Flask auto-instrumentation (WSGI middleware).

Provides a WSGI middleware that wraps Flask (or any WSGI) applications
to create structured Span objects for each HTTP request, with full trace
hierarchy support via context propagation. Captures full request/response
data (FR6/FR7).
"""

from __future__ import annotations

import inspect
import json
import logging
from typing import Any, Callable, Iterable

from tracely.capture import build_url, capture_request_data, capture_response_data
from tracely.context import _span_context
from tracely.span import Span
from tracely.span_processor import on_span_end, on_span_start

logger = logging.getLogger("tracely")


def _extract_wsgi_headers(environ: dict[str, Any]) -> dict[str, str]:
    """Extract HTTP headers from WSGI environ dict.

    WSGI stores headers as HTTP_<NAME> with underscores replacing hyphens.
    CONTENT_TYPE and CONTENT_LENGTH are special cases without HTTP_ prefix.
    """
    headers: dict[str, str] = {}
    for key, value in environ.items():
        if key.startswith("HTTP_"):
            header_name = key[5:].lower().replace("_", "-")
            headers[header_name] = str(value)
        elif key == "CONTENT_TYPE":
            headers["content-type"] = str(value)
        elif key == "CONTENT_LENGTH":
            headers["content-length"] = str(value)
    return headers


def _read_wsgi_body(environ: dict[str, Any]) -> bytes:
    """Read request body from WSGI environ's wsgi.input stream."""
    try:
        content_length = int(environ.get("CONTENT_LENGTH", 0) or 0)
    except (ValueError, TypeError):
        content_length = 0

    if content_length <= 0:
        return b""

    wsgi_input = environ.get("wsgi.input")
    if wsgi_input is None:
        return b""

    try:
        return wsgi_input.read(content_length)
    except Exception:
        logger.debug("Error reading WSGI body", exc_info=True)
        return b""


def _resolve_flask_route(app: Any, path: str, method: str) -> dict[str, str]:
    """Use Flask's URL map to resolve route pattern and handler metadata.

    Returns a dict of span attributes if a matching route is found.
    """
    try:
        adapter = app.url_map.bind("")
        endpoint, args = adapter.match(path, method)
        view_func = app.view_functions.get(endpoint)

        # Find the matching rule for the route pattern
        rule_str = ""
        for rule in app.url_map.iter_rules():
            if rule.endpoint == endpoint:
                rule_str = rule.rule
                break

        attrs: dict[str, str] = {}
        if rule_str:
            attrs["http.route"] = rule_str
        attrs["flask.endpoint"] = endpoint
        if args:
            attrs["flask.path_params"] = json.dumps(args)
        if view_func is not None:
            attrs["code.function"] = view_func.__name__
            try:
                attrs["code.filepath"] = inspect.getfile(view_func)
            except (TypeError, OSError):
                pass
        return attrs
    except Exception:
        logger.debug("Error resolving Flask route", exc_info=True)
        return {}


class TracelyWSGIMiddleware:
    """WSGI middleware that creates root spans for HTTP requests.

    Creates a Span object with trace_id and span_id, sets it as the
    active span via context propagation, and captures HTTP attributes
    including full request/response data (headers, body, URL).
    """

    def __init__(
        self,
        app: Callable[..., Iterable[bytes]],
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

    def __call__(
        self,
        environ: dict[str, Any],
        start_response: Callable[..., Any],
    ) -> Iterable[bytes]:
        method = environ.get("REQUEST_METHOD", "UNKNOWN")
        path = environ.get("PATH_INFO", "/")
        query = environ.get("QUERY_STRING", "")

        # Build full URL
        scheme = environ.get("wsgi.url_scheme", "http")
        host = environ.get("HTTP_HOST", "")
        if not host:
            server_name = environ.get("SERVER_NAME", "localhost")
            server_port = environ.get("SERVER_PORT", "80")
            if (scheme == "https" and server_port != "443") or (scheme == "http" and server_port != "80"):
                host = f"{server_name}:{server_port}"
            else:
                host = server_name
        full_url = build_url(scheme, host, path, query)

        # Read request headers and body
        req_headers = _extract_wsgi_headers(environ)
        req_content_type = req_headers.get("content-type", "")
        req_body = _read_wsgi_body(environ)

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
            route_attrs = _resolve_flask_route(self._app_ref, path, method)
            for key, value in route_attrs.items():
                span.set_attribute(key, value)

        # Standard OTEL attributes from request
        span.set_attribute("http.host", host)
        span.set_attribute("http.scheme", scheme)
        server_port = environ.get("SERVER_PORT")
        if server_port:
            span.set_attribute("net.host.port", server_port)
        user_agent = req_headers.get("user-agent", "")
        if user_agent:
            span.set_attribute("http.user_agent", user_agent)

        # AR3: Export pending_span immediately for real-time dashboard
        on_span_start(span)

        status_code = 0
        resp_headers_dict: dict[str, str] = {}
        resp_content_type = ""

        def wrapped_start_response(
            status: str, headers: list[Any], exc_info: Any = None
        ) -> Any:
            nonlocal status_code, resp_headers_dict, resp_content_type
            try:
                status_code = int(status.split(" ", 1)[0])
            except (ValueError, IndexError):
                status_code = 0
            # Convert response headers to dict
            for name, value in headers:
                resp_headers_dict[str(name).lower()] = str(value)
            resp_content_type = resp_headers_dict.get("content-type", "")
            return start_response(status, headers, exc_info)

        with _span_context(span):
            try:
                result = self.app(environ, wrapped_start_response)
                # Collect response body
                response_body_chunks: list[bytes] = []
                collected: list[bytes] = []
                for chunk in result:
                    collected.append(chunk)
                    response_body_chunks.append(chunk)
                response_body = b"".join(response_body_chunks)

                # Capture request data (FR6)
                capture_request_data(
                    span,
                    method=method,
                    url=full_url,
                    headers=req_headers,
                    body=req_body,
                    content_type=req_content_type,
                    query_params=query,
                )

                # Capture response data (FR7)
                capture_response_data(
                    span,
                    status_code=status_code,
                    headers=resp_headers_dict,
                    body=response_body,
                    content_type=resp_content_type,
                )

                return collected
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


def instrument_flask(app: Any, *, service_name: str | None = None) -> None:
    """Instrument a Flask application with Tracely tracing.

    Wraps the Flask app's WSGI app with TracelyWSGIMiddleware, providing
    full route resolution, handler metadata, and automatic config
    inheritance from tracely.init().

    Args:
        app: A Flask application instance.
        service_name: Override the service name from tracely.init() config.
    """
    from tracely.sdk import _sdk_instance

    inst = _sdk_instance()
    svc = service_name or (inst.config.service_name if inst else None)
    app.wsgi_app = TracelyWSGIMiddleware(
        app.wsgi_app, service_name=svc, app_ref=app,
    )
