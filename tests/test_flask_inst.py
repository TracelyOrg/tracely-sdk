"""Tests for Flask auto-instrumentation (Story 2.2 + 2.3 span hierarchy)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from tracely.context import get_current_span
from tracely.instrumentation.flask_inst import (
    TracelyWSGIMiddleware,
    instrument_flask,
)
from tracely.span import Span


class TestTracelyWSGIMiddleware:
    """Test the WSGI middleware that wraps Flask apps."""

    @pytest.fixture
    def captured_spans(self) -> list[dict]:
        return []

    def _make_environ(
        self,
        method: str = "GET",
        path: str = "/",
        query: str = "",
    ) -> dict[str, Any]:
        return {
            "REQUEST_METHOD": method,
            "PATH_INFO": path,
            "QUERY_STRING": query,
            "SERVER_NAME": "localhost",
            "SERVER_PORT": "5000",
        }

    def _make_start_response(self) -> tuple[MagicMock, list[str]]:
        captured_status: list[str] = []

        def start_response(status: str, headers: list, exc_info: Any = None) -> None:
            captured_status.append(status)

        return MagicMock(side_effect=start_response), captured_status

    def test_creates_span_for_request(self, captured_spans: list[dict]) -> None:
        """Middleware creates a span with method, path, status, duration."""

        def app(environ: dict, start_response: Any) -> list[bytes]:
            start_response("200 OK", [])
            return [b"Hello"]

        mw = TracelyWSGIMiddleware(
            app=app,
            on_span=lambda s: captured_spans.append(s),
            service_name="flask-api",
        )
        environ = self._make_environ("GET", "/api/users")
        start_resp, _ = self._make_start_response()
        result = list(mw(environ, start_resp))

        assert result == [b"Hello"]
        assert len(captured_spans) == 1
        span = captured_spans[0]
        assert span["attributes"]["http.method"] == "GET"
        assert span["attributes"]["http.route"] == "/api/users"
        assert span["attributes"]["http.status_code"] == "200"
        assert span["duration_ms"] >= 0
        assert span["span_type"] == "span"

    def test_span_has_trace_id_and_span_id(self, captured_spans: list[dict]) -> None:
        """Root span has unique trace_id and span_id (FR55)."""

        def app(environ: dict, start_response: Any) -> list[bytes]:
            start_response("200 OK", [])
            return [b"OK"]

        mw = TracelyWSGIMiddleware(app=app, on_span=lambda s: captured_spans.append(s))
        list(mw(self._make_environ(), MagicMock()))
        span = captured_spans[0]
        assert len(span["trace_id"]) == 32
        assert len(span["span_id"]) == 16
        assert span["parent_span_id"] is None

    def test_captures_post_404(self, captured_spans: list[dict]) -> None:
        def app(environ: dict, start_response: Any) -> list[bytes]:
            start_response("404 Not Found", [])
            return [b"Not Found"]

        mw = TracelyWSGIMiddleware(app=app, on_span=lambda s: captured_spans.append(s))
        list(mw(self._make_environ("POST", "/missing"), MagicMock()))
        assert captured_spans[0]["attributes"]["http.method"] == "POST"
        assert captured_spans[0]["attributes"]["http.status_code"] == "404"

    def test_captures_query_string(self, captured_spans: list[dict]) -> None:
        def app(environ: dict, start_response: Any) -> list[bytes]:
            start_response("200 OK", [])
            return [b"OK"]

        mw = TracelyWSGIMiddleware(app=app, on_span=lambda s: captured_spans.append(s))
        environ = self._make_environ("GET", "/search", query="q=test")
        list(mw(environ, MagicMock()))
        assert captured_spans[0]["attributes"]["http.query"] == "q=test"

    def test_captures_exception(self, captured_spans: list[dict]) -> None:
        """If app raises, middleware records span with error info."""

        def app(environ: dict, start_response: Any) -> list[bytes]:
            raise ValueError("boom")

        mw = TracelyWSGIMiddleware(app=app, on_span=lambda s: captured_spans.append(s))
        with pytest.raises(ValueError, match="boom"):
            list(mw(self._make_environ(), MagicMock()))

        assert len(captured_spans) == 1
        assert captured_spans[0]["attributes"]["error"] == "true"
        assert captured_spans[0]["attributes"]["error.type"] == "ValueError"
        assert captured_spans[0]["status_code"] == "ERROR"
        # Unhandled exception should be recorded as HTTP 500
        assert captured_spans[0]["attributes"]["http.status_code"] == "500"
        assert "exception.stacktrace" in captured_spans[0]["attributes"]

    def test_captures_500_status(self, captured_spans: list[dict]) -> None:
        def app(environ: dict, start_response: Any) -> list[bytes]:
            start_response("500 Internal Server Error", [])
            return [b"error"]

        mw = TracelyWSGIMiddleware(app=app, on_span=lambda s: captured_spans.append(s))
        list(mw(self._make_environ(), MagicMock()))
        assert captured_spans[0]["attributes"]["http.status_code"] == "500"

    def test_context_propagation_during_request(self) -> None:
        """Root span is active during request processing."""
        active_spans: list[Span | None] = []

        def app(environ: dict, start_response: Any) -> list[bytes]:
            active_spans.append(get_current_span())
            start_response("200 OK", [])
            return [b"OK"]

        mw = TracelyWSGIMiddleware(app=app)
        list(mw(self._make_environ("GET", "/test"), MagicMock()))
        assert len(active_spans) == 1
        assert isinstance(active_spans[0], Span)
        assert active_spans[0].name == "GET /test"


class TestInstrumentFlask:
    """Test the instrument_flask() convenience function."""

    def test_instrument_flask_wraps_wsgi_app(self) -> None:
        """instrument_flask() wraps app.wsgi_app with TracelyWSGIMiddleware."""

        class FakeApp:
            def __init__(self):
                self.wsgi_app = lambda environ, start_response: []

        app = FakeApp()
        instrument_flask(app, service_name="flask-svc")
        assert isinstance(app.wsgi_app, TracelyWSGIMiddleware)
        assert app.wsgi_app._service_name == "flask-svc"
        assert app.wsgi_app._app_ref is app


class TestWSGIRequestResponseCapture:
    """Test full request/response data capture in WSGI middleware (Story 2.4)."""

    def _make_environ(
        self,
        method: str = "GET",
        path: str = "/",
        query: str = "",
        headers: dict[str, str] | None = None,
        body: bytes = b"",
        scheme: str = "https",
        host: str = "example.com",
    ) -> dict[str, Any]:
        import io
        environ: dict[str, Any] = {
            "REQUEST_METHOD": method,
            "PATH_INFO": path,
            "QUERY_STRING": query,
            "SERVER_NAME": host.split(":")[0],
            "SERVER_PORT": host.split(":")[1] if ":" in host else ("443" if scheme == "https" else "80"),
            "wsgi.url_scheme": scheme,
            "wsgi.input": io.BytesIO(body),
            "CONTENT_LENGTH": str(len(body)),
        }
        if headers:
            for key, value in headers.items():
                wsgi_key = f"HTTP_{key.upper().replace('-', '_')}"
                environ[wsgi_key] = value
            if "content-type" in headers:
                environ["CONTENT_TYPE"] = headers["content-type"]
        return environ

    def test_captures_request_headers(self) -> None:
        """AC1: request headers are captured as span attribute."""
        captured: list[dict] = []

        def app(environ: dict, start_response: Any) -> list[bytes]:
            start_response("200 OK", [("content-type", "text/plain")])
            return [b"OK"]

        mw = TracelyWSGIMiddleware(app=app, on_span=lambda s: captured.append(s))
        environ = self._make_environ(headers={"content-type": "application/json", "accept": "text/html"})
        list(mw(environ, MagicMock()))

        import json
        hdrs = json.loads(captured[0]["attributes"]["http.request.headers"])
        assert hdrs["content-type"] == "application/json"

    def test_captures_request_body(self) -> None:
        """AC1: request body is captured as span attribute."""
        captured: list[dict] = []

        def app(environ: dict, start_response: Any) -> list[bytes]:
            start_response("200 OK", [])
            return [b"OK"]

        mw = TracelyWSGIMiddleware(app=app, on_span=lambda s: captured.append(s))
        environ = self._make_environ(
            method="POST",
            body=b'{"name": "test"}',
            headers={"content-type": "application/json"},
        )
        list(mw(environ, MagicMock()))

        assert captured[0]["attributes"]["http.request.body"] == '{"name": "test"}'

    def test_captures_full_url(self) -> None:
        """AC1: full URL is captured."""
        captured: list[dict] = []

        def app(environ: dict, start_response: Any) -> list[bytes]:
            start_response("200 OK", [])
            return [b"OK"]

        mw = TracelyWSGIMiddleware(app=app, on_span=lambda s: captured.append(s))
        environ = self._make_environ(path="/api/users", query="page=1", scheme="https", host="example.com")
        list(mw(environ, MagicMock()))

        assert captured[0]["attributes"]["http.url"] == "https://example.com/api/users?page=1"

    def test_captures_response_headers(self) -> None:
        """AC2: response headers are captured."""
        captured: list[dict] = []

        def app(environ: dict, start_response: Any) -> list[bytes]:
            start_response("200 OK", [("content-type", "application/json"), ("x-request-id", "abc")])
            return [b'{"ok": true}']

        mw = TracelyWSGIMiddleware(app=app, on_span=lambda s: captured.append(s))
        list(mw(self._make_environ(), MagicMock()))

        import json
        resp_hdrs = json.loads(captured[0]["attributes"]["http.response.headers"])
        assert resp_hdrs["content-type"] == "application/json"

    def test_captures_response_body(self) -> None:
        """AC2: response body is captured."""
        captured: list[dict] = []

        def app(environ: dict, start_response: Any) -> list[bytes]:
            start_response("200 OK", [("content-type", "application/json")])
            return [b'{"id": 1}']

        mw = TracelyWSGIMiddleware(app=app, on_span=lambda s: captured.append(s))
        list(mw(self._make_environ(), MagicMock()))

        assert captured[0]["attributes"]["http.response.body"] == '{"id": 1}'

    def test_truncates_large_request_body(self) -> None:
        """AC3: request body > 64KB is truncated."""
        captured: list[dict] = []
        large_body = b"x" * 70000

        def app(environ: dict, start_response: Any) -> list[bytes]:
            start_response("200 OK", [])
            return [b"OK"]

        mw = TracelyWSGIMiddleware(app=app, on_span=lambda s: captured.append(s))
        environ = self._make_environ(method="POST", body=large_body, headers={"content-type": "text/plain"})
        list(mw(environ, MagicMock()))

        assert captured[0]["attributes"]["http.request.body"].endswith("[truncated]")

    def test_replaces_binary_request_body(self) -> None:
        """AC4: binary request body replaced with placeholder."""
        captured: list[dict] = []

        def app(environ: dict, start_response: Any) -> list[bytes]:
            start_response("200 OK", [])
            return [b"OK"]

        mw = TracelyWSGIMiddleware(app=app, on_span=lambda s: captured.append(s))
        environ = self._make_environ(
            method="POST",
            body=b"\x89PNG" + b"\x00" * 100,
            headers={"content-type": "image/png"},
        )
        list(mw(environ, MagicMock()))

        assert captured[0]["attributes"]["http.request.body"].startswith("[binary:")

    def test_truncates_large_response_body(self) -> None:
        """AC3: response body > 64KB is truncated."""
        captured: list[dict] = []
        large_response = b"y" * 70000

        def app(environ: dict, start_response: Any) -> list[bytes]:
            start_response("200 OK", [("content-type", "text/plain")])
            return [large_response]

        mw = TracelyWSGIMiddleware(app=app, on_span=lambda s: captured.append(s))
        list(mw(self._make_environ(), MagicMock()))

        assert captured[0]["attributes"]["http.response.body"].endswith("[truncated]")

    def test_replaces_binary_response_body(self) -> None:
        """AC4: binary response body replaced with placeholder."""
        captured: list[dict] = []

        def app(environ: dict, start_response: Any) -> list[bytes]:
            start_response("200 OK", [("content-type", "image/jpeg")])
            return [b"\xff\xd8\xff" + b"\x00" * 500]

        mw = TracelyWSGIMiddleware(app=app, on_span=lambda s: captured.append(s))
        list(mw(self._make_environ(), MagicMock()))

        assert captured[0]["attributes"]["http.response.body"].startswith("[binary:")
