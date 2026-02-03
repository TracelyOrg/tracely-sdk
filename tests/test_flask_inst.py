"""Tests for Flask auto-instrumentation (Story 2.2, Task 5)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from tracely.detection import FrameworkInfo
from tracely.instrumentation.flask_inst import (
    FlaskInstrumentor,
    TracelyWSGIMiddleware,
)


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
        )
        environ = self._make_environ("GET", "/api/users")
        start_resp, _ = self._make_start_response()
        result = list(mw(environ, start_resp))

        assert result == [b"Hello"]
        assert len(captured_spans) == 1
        span = captured_spans[0]
        assert span["http.method"] == "GET"
        assert span["http.route"] == "/api/users"
        assert span["http.status_code"] == 200
        assert span["duration_ms"] >= 0
        assert span["span_type"] == "http"

    def test_captures_post_404(self, captured_spans: list[dict]) -> None:
        def app(environ: dict, start_response: Any) -> list[bytes]:
            start_response("404 Not Found", [])
            return [b"Not Found"]

        mw = TracelyWSGIMiddleware(
            app=app,
            on_span=lambda s: captured_spans.append(s),
        )
        result = list(mw(self._make_environ("POST", "/missing"), MagicMock()))
        assert captured_spans[0]["http.method"] == "POST"
        assert captured_spans[0]["http.status_code"] == 404

    def test_captures_query_string(self, captured_spans: list[dict]) -> None:
        def app(environ: dict, start_response: Any) -> list[bytes]:
            start_response("200 OK", [])
            return [b"OK"]

        mw = TracelyWSGIMiddleware(
            app=app,
            on_span=lambda s: captured_spans.append(s),
        )
        environ = self._make_environ("GET", "/search", query="q=test")
        list(mw(environ, MagicMock()))
        assert captured_spans[0]["http.query"] == "q=test"

    def test_captures_exception(self, captured_spans: list[dict]) -> None:
        """If app raises, middleware records span with error info."""

        def app(environ: dict, start_response: Any) -> list[bytes]:
            raise ValueError("boom")

        mw = TracelyWSGIMiddleware(
            app=app,
            on_span=lambda s: captured_spans.append(s),
        )
        with pytest.raises(ValueError, match="boom"):
            list(mw(self._make_environ(), MagicMock()))

        assert len(captured_spans) == 1
        assert captured_spans[0]["error"] is True
        assert "ValueError" in captured_spans[0]["error.type"]

    def test_captures_500_status(self, captured_spans: list[dict]) -> None:
        def app(environ: dict, start_response: Any) -> list[bytes]:
            start_response("500 Internal Server Error", [])
            return [b"error"]

        mw = TracelyWSGIMiddleware(
            app=app,
            on_span=lambda s: captured_spans.append(s),
        )
        list(mw(self._make_environ(), MagicMock()))
        assert captured_spans[0]["http.status_code"] == 500


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
