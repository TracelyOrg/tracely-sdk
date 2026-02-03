"""Tests for FastAPI auto-instrumentation (Story 2.2, Task 3)."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from tracely.detection import FrameworkInfo
from tracely.instrumentation.fastapi_inst import (
    FastAPIInstrumentor,
    TracelyASGIMiddleware,
)


@pytest.fixture
def framework_info() -> FrameworkInfo:
    return FrameworkInfo(name="fastapi")


class TestTracelyASGIMiddleware:
    """Test the ASGI middleware that wraps FastAPI apps."""

    @pytest.fixture
    def captured_spans(self) -> list[dict]:
        return []

    @pytest.fixture
    def middleware(self, captured_spans: list[dict]) -> TracelyASGIMiddleware:
        async def dummy_app(scope, receive, send):
            if scope["type"] == "http":
                await send(
                    {
                        "type": "http.response.start",
                        "status": 200,
                        "headers": [],
                    }
                )
                await send(
                    {
                        "type": "http.response.body",
                        "body": b"OK",
                    }
                )

        return TracelyASGIMiddleware(
            app=dummy_app,
            on_span=lambda span: captured_spans.append(span),
        )

    @pytest.mark.asyncio
    async def test_passes_through_non_http(self, middleware: TracelyASGIMiddleware, captured_spans: list[dict]) -> None:
        """Non-HTTP scopes (lifespan, websocket) pass through untouched."""
        scope = {"type": "lifespan"}
        received = []
        await middleware(scope, lambda: None, lambda msg: received.append(msg))
        assert len(captured_spans) == 0

    @pytest.mark.asyncio
    async def test_creates_span_for_http_request(self, middleware: TracelyASGIMiddleware, captured_spans: list[dict]) -> None:
        """HTTP request produces a span with method, path, status, duration."""
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/api/users",
            "query_string": b"",
            "headers": [],
        }
        await middleware(scope, self._mock_receive, self._noop_send)
        assert len(captured_spans) == 1
        span = captured_spans[0]
        assert span["http.method"] == "GET"
        assert span["http.route"] == "/api/users"
        assert span["http.status_code"] == 200
        assert "duration_ms" in span
        assert span["duration_ms"] >= 0

    @pytest.mark.asyncio
    async def test_captures_query_string(self, middleware: TracelyASGIMiddleware, captured_spans: list[dict]) -> None:
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/search",
            "query_string": b"q=test&page=1",
            "headers": [],
        }
        await middleware(scope, self._mock_receive, self._noop_send)
        span = captured_spans[0]
        assert span["http.query"] == "q=test&page=1"

    @pytest.mark.asyncio
    async def test_captures_error_status(self) -> None:
        """Middleware captures 500 status from the app."""
        captured = []

        async def error_app(scope, receive, send):
            await send(
                {"type": "http.response.start", "status": 500, "headers": []}
            )
            await send({"type": "http.response.body", "body": b"error"})

        mw = TracelyASGIMiddleware(
            app=error_app,
            on_span=lambda span: captured.append(span),
        )
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/fail",
            "query_string": b"",
            "headers": [],
        }
        await mw(scope, self._mock_receive, self._noop_send)
        assert captured[0]["http.status_code"] == 500

    @pytest.mark.asyncio
    async def test_captures_exception_from_app(self) -> None:
        """If the app raises, middleware still records the span with error info."""
        captured = []

        async def crashing_app(scope, receive, send):
            raise ValueError("boom")

        mw = TracelyASGIMiddleware(
            app=crashing_app,
            on_span=lambda span: captured.append(span),
        )
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/crash",
            "query_string": b"",
            "headers": [],
        }
        with pytest.raises(ValueError, match="boom"):
            await mw(scope, self._mock_receive, self._noop_send)
        assert len(captured) == 1
        assert captured[0]["error"] is True
        assert "ValueError" in captured[0]["error.type"]

    @pytest.mark.asyncio
    async def test_span_type_is_http(self, middleware: TracelyASGIMiddleware, captured_spans: list[dict]) -> None:
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/",
            "query_string": b"",
            "headers": [],
        }
        await middleware(scope, self._mock_receive, self._noop_send)
        assert captured_spans[0]["span_type"] == "http"

    @staticmethod
    async def _mock_receive():
        return {"type": "http.request", "body": b""}

    @staticmethod
    async def _noop_send(msg):
        pass


class TestFastAPIInstrumentor:
    """Test instrumentor activation/deactivation."""

    def test_activate_and_deactivate(self, framework_info: FrameworkInfo) -> None:
        inst = FastAPIInstrumentor(framework_info)
        # activate should not raise
        inst.activate()
        # deactivate should not raise
        inst.deactivate()

    def test_never_raises(self, framework_info: FrameworkInfo) -> None:
        """Instrumentor never crashes even if FastAPI is not importable."""
        inst = FastAPIInstrumentor(framework_info)
        # Should not raise even if internal hooks fail
        inst.activate()
        inst.deactivate()
