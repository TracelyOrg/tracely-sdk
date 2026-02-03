"""Tests for Flask auto-instrumentation (Story 2.2 + 2.3 span hierarchy)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from tracely.context import get_current_span
from tracely.detection import FrameworkInfo
from tracely.instrumentation.flask_inst import (
    FlaskInstrumentor,
    TracelyWSGIMiddleware,
)
from tracely.span import Span


@pytest.fixture
def framework_info() -> FrameworkInfo:
    return FrameworkInfo(name="flask")


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


class TestFlaskInstrumentor:
    """Test instrumentor activation/deactivation."""

    def test_activate_and_deactivate(self, framework_info: FrameworkInfo) -> None:
        inst = FlaskInstrumentor(framework_info)
        inst.activate()
        inst.deactivate()

    def test_never_raises(self, framework_info: FrameworkInfo) -> None:
        inst = FlaskInstrumentor(framework_info)
        inst.activate()
        inst.deactivate()
