"""Django auto-instrumentation (Django middleware).

Provides a Django-style middleware that creates structured Span objects
for each HTTP request, with full trace hierarchy support via context
propagation. Captures full request/response data (FR6/FR7).
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from tracely.capture import build_url, capture_request_data, capture_response_data
from tracely.context import _span_context
from tracely.instrumentation.base import BaseInstrumentor
from tracely.span import Span

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
            on_end=self._on_end,
        )
        span.set_attribute("http.route", path)
        span.set_attribute("http.query", query)

        with _span_context(span):
            try:
                response = self.get_response(request)

                # Extract response data
                resp_headers_dict: dict[str, str] = {}
                try:
                    for name, value in response.items():
                        resp_headers_dict[str(name).lower()] = str(value)
                except Exception:
                    pass
                resp_content_type = resp_headers_dict.get("content-type", "")
                resp_body = getattr(response, "content", b"")

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
                    status_code=getattr(response, "status_code", 0),
                    headers=resp_headers_dict,
                    body=resp_body,
                    content_type=resp_content_type,
                )

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
