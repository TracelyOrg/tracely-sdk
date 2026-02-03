"""Flask auto-instrumentation (WSGI middleware).

Provides a WSGI middleware that wraps Flask (or any WSGI) applications
to create structured Span objects for each HTTP request, with full trace
hierarchy support via context propagation. Captures full request/response
data (FR6/FR7).
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Iterable

from tracely.capture import build_url, capture_request_data, capture_response_data
from tracely.context import _span_context
from tracely.instrumentation.base import BaseInstrumentor
from tracely.span import Span

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
            on_end=self._on_end,
        )
        span.set_attribute("http.route", path)
        span.set_attribute("http.query", query)

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
