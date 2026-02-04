"""Tests for Django auto-instrumentation (Story 2.2 + 2.3 span hierarchy)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from tracely.context import get_current_span
from tracely.instrumentation.django_inst import (
    TracelyDjangoMiddleware,
)
from tracely.span import Span


class TestTracelyDjangoMiddleware:
    """Test the Django-style middleware that creates spans per request."""

    @pytest.fixture
    def captured_spans(self) -> list[dict]:
        return []

    def _make_request(
        self,
        method: str = "GET",
        path: str = "/api/users/",
        query: str = "",
    ) -> MagicMock:
        request = MagicMock()
        request.method = method
        request.path = path
        request.META = {"QUERY_STRING": query}
        return request

    def _make_response(self, status_code: int = 200) -> MagicMock:
        response = MagicMock()
        response.status_code = status_code
        return response

    def test_creates_span_for_request(self, captured_spans: list[dict]) -> None:
        """Middleware creates a span with method, path, status, duration."""
        response = self._make_response(200)

        def get_response(request: Any) -> Any:
            return response

        mw = TracelyDjangoMiddleware(
            get_response=get_response,
            on_span=lambda span: captured_spans.append(span),
            service_name="django-api",
        )
        request = self._make_request("GET", "/api/users/")
        result = mw(request)

        assert result is response
        assert len(captured_spans) == 1
        span = captured_spans[0]
        assert span["attributes"]["http.method"] == "GET"
        assert span["attributes"]["http.route"] == "/api/users/"
        assert span["attributes"]["http.status_code"] == "200"
        assert span["duration_ms"] >= 0
        assert span["span_type"] == "span"

    def test_span_has_trace_id_and_span_id(self, captured_spans: list[dict]) -> None:
        """Root span has unique trace_id and span_id (FR55)."""

        def get_response(req: Any) -> Any:
            return self._make_response(200)

        mw = TracelyDjangoMiddleware(get_response=get_response, on_span=lambda s: captured_spans.append(s))
        mw(self._make_request())
        span = captured_spans[0]
        assert len(span["trace_id"]) == 32
        assert len(span["span_id"]) == 16
        assert span["parent_span_id"] is None

    def test_captures_post_request(self, captured_spans: list[dict]) -> None:
        response = self._make_response(201)

        def get_response(req: Any) -> Any:
            return response

        mw = TracelyDjangoMiddleware(get_response=get_response, on_span=lambda s: captured_spans.append(s))
        mw(self._make_request("POST", "/api/items/"))
        assert captured_spans[0]["attributes"]["http.method"] == "POST"
        assert captured_spans[0]["attributes"]["http.status_code"] == "201"

    def test_captures_query_string(self, captured_spans: list[dict]) -> None:
        def get_response(req: Any) -> Any:
            return self._make_response(200)

        mw = TracelyDjangoMiddleware(get_response=get_response, on_span=lambda s: captured_spans.append(s))
        mw(self._make_request("GET", "/search/", query="q=hello"))
        assert captured_spans[0]["attributes"]["http.query"] == "q=hello"

    def test_captures_exception(self, captured_spans: list[dict]) -> None:
        """If get_response raises, middleware still records span with error."""

        def get_response(req: Any) -> Any:
            raise RuntimeError("db crashed")

        mw = TracelyDjangoMiddleware(get_response=get_response, on_span=lambda s: captured_spans.append(s))
        with pytest.raises(RuntimeError, match="db crashed"):
            mw(self._make_request("GET", "/crash/"))

        assert len(captured_spans) == 1
        assert captured_spans[0]["attributes"]["error"] == "true"
        assert captured_spans[0]["attributes"]["error.type"] == "RuntimeError"
        assert captured_spans[0]["status_code"] == "ERROR"
        # Unhandled exception should be recorded as HTTP 500
        assert captured_spans[0]["attributes"]["http.status_code"] == "500"
        assert "exception.stacktrace" in captured_spans[0]["attributes"]

    def test_captures_500_status(self, captured_spans: list[dict]) -> None:
        def get_response(req: Any) -> Any:
            return self._make_response(500)

        mw = TracelyDjangoMiddleware(get_response=get_response, on_span=lambda s: captured_spans.append(s))
        mw(self._make_request())
        assert captured_spans[0]["attributes"]["http.status_code"] == "500"

    def test_context_propagation_during_request(self) -> None:
        """Root span is active during request processing."""
        active_spans: list[Span | None] = []

        def get_response(req: Any) -> Any:
            active_spans.append(get_current_span())
            resp = MagicMock()
            resp.status_code = 200
            return resp

        mw = TracelyDjangoMiddleware(get_response=get_response)
        mw(self._make_request("GET", "/test/"))
        assert len(active_spans) == 1
        assert isinstance(active_spans[0], Span)
        assert active_spans[0].name == "GET /test/"


class TestDjangoRequestResponseCapture:
    """Test full request/response data capture in Django middleware (Story 2.4)."""

    def _make_request(
        self,
        method: str = "GET",
        path: str = "/",
        query: str = "",
        headers: dict[str, str] | None = None,
        body: bytes = b"",
        scheme: str = "https",
        host: str = "example.com",
    ) -> MagicMock:
        request = MagicMock()
        request.method = method
        request.path = path
        request.body = body
        request.scheme = scheme

        meta: dict[str, Any] = {"QUERY_STRING": query, "HTTP_HOST": host}
        if headers:
            for key, value in headers.items():
                if key.lower() == "content-type":
                    meta["CONTENT_TYPE"] = value
                else:
                    meta[f"HTTP_{key.upper().replace('-', '_')}"] = value
        request.META = meta

        # Django HttpRequest.headers property simulation
        request.headers = headers or {}
        return request

    def _make_response(
        self,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
        body: bytes = b"",
    ) -> MagicMock:
        response = MagicMock()
        response.status_code = status_code
        response.content = body

        resp_headers = headers or {}
        response.items.return_value = list(resp_headers.items())
        # Allow dict-like header access
        response.__getitem__ = lambda self_inner, key: resp_headers.get(key, "")
        response.get = lambda key, default="": resp_headers.get(key, default)
        return response

    def test_captures_request_headers(self) -> None:
        """AC1: request headers are captured."""
        captured: list[dict] = []
        response = self._make_response(200)

        def get_response(req: Any) -> Any:
            return response

        mw = TracelyDjangoMiddleware(get_response=get_response, on_span=lambda s: captured.append(s))
        request = self._make_request(headers={"content-type": "application/json", "accept": "text/html"})
        mw(request)

        import json
        hdrs = json.loads(captured[0]["attributes"]["http.request.headers"])
        assert hdrs["content-type"] == "application/json"

    def test_captures_request_body(self) -> None:
        """AC1: request body is captured."""
        captured: list[dict] = []
        response = self._make_response(200)

        def get_response(req: Any) -> Any:
            return response

        mw = TracelyDjangoMiddleware(get_response=get_response, on_span=lambda s: captured.append(s))
        request = self._make_request(
            method="POST",
            body=b'{"name": "test"}',
            headers={"content-type": "application/json"},
        )
        mw(request)

        assert captured[0]["attributes"]["http.request.body"] == '{"name": "test"}'

    def test_captures_full_url(self) -> None:
        """AC1: full URL is captured."""
        captured: list[dict] = []
        response = self._make_response(200)

        def get_response(req: Any) -> Any:
            return response

        mw = TracelyDjangoMiddleware(get_response=get_response, on_span=lambda s: captured.append(s))
        request = self._make_request(path="/api/users", query="page=1", scheme="https", host="example.com")
        mw(request)

        assert captured[0]["attributes"]["http.url"] == "https://example.com/api/users?page=1"

    def test_captures_response_headers(self) -> None:
        """AC2: response headers are captured."""
        captured: list[dict] = []
        response = self._make_response(200, headers={"content-type": "application/json", "x-request-id": "abc"})

        def get_response(req: Any) -> Any:
            return response

        mw = TracelyDjangoMiddleware(get_response=get_response, on_span=lambda s: captured.append(s))
        mw(self._make_request())

        import json
        resp_hdrs = json.loads(captured[0]["attributes"]["http.response.headers"])
        assert resp_hdrs["content-type"] == "application/json"

    def test_captures_response_body(self) -> None:
        """AC2: response body is captured."""
        captured: list[dict] = []
        response = self._make_response(200, headers={"content-type": "application/json"}, body=b'{"id": 1}')

        def get_response(req: Any) -> Any:
            return response

        mw = TracelyDjangoMiddleware(get_response=get_response, on_span=lambda s: captured.append(s))
        mw(self._make_request())

        assert captured[0]["attributes"]["http.response.body"] == '{"id": 1}'

    def test_truncates_large_request_body(self) -> None:
        """AC3: request body > 64KB is truncated."""
        captured: list[dict] = []
        large_body = b"x" * 70000
        response = self._make_response(200)

        def get_response(req: Any) -> Any:
            return response

        mw = TracelyDjangoMiddleware(get_response=get_response, on_span=lambda s: captured.append(s))
        request = self._make_request(method="POST", body=large_body, headers={"content-type": "text/plain"})
        mw(request)

        assert captured[0]["attributes"]["http.request.body"].endswith("[truncated]")

    def test_replaces_binary_request_body(self) -> None:
        """AC4: binary request body replaced with placeholder."""
        captured: list[dict] = []
        response = self._make_response(200)

        def get_response(req: Any) -> Any:
            return response

        mw = TracelyDjangoMiddleware(get_response=get_response, on_span=lambda s: captured.append(s))
        request = self._make_request(
            method="POST",
            body=b"\x89PNG" + b"\x00" * 100,
            headers={"content-type": "image/png"},
        )
        mw(request)

        assert captured[0]["attributes"]["http.request.body"].startswith("[binary:")

    def test_truncates_large_response_body(self) -> None:
        """AC3: response body > 64KB is truncated."""
        captured: list[dict] = []
        large_response = b"y" * 70000
        response = self._make_response(200, headers={"content-type": "text/plain"}, body=large_response)

        def get_response(req: Any) -> Any:
            return response

        mw = TracelyDjangoMiddleware(get_response=get_response, on_span=lambda s: captured.append(s))
        mw(self._make_request())

        assert captured[0]["attributes"]["http.response.body"].endswith("[truncated]")

    def test_replaces_binary_response_body(self) -> None:
        """AC4: binary response body replaced with placeholder."""
        captured: list[dict] = []
        response = self._make_response(200, headers={"content-type": "image/jpeg"}, body=b"\xff\xd8" + b"\x00" * 500)

        def get_response(req: Any) -> Any:
            return response

        mw = TracelyDjangoMiddleware(get_response=get_response, on_span=lambda s: captured.append(s))
        mw(self._make_request())

        assert captured[0]["attributes"]["http.response.body"].startswith("[binary:")
