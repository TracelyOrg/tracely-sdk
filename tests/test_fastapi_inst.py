"""Tests for FastAPI auto-instrumentation (Story 2.2 + 2.3 span hierarchy)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from tracely.context import get_current_span
from tracely.detection import FrameworkInfo
from tracely.instrumentation.fastapi_inst import (
    FastAPIInstrumentor,
    TracelyASGIMiddleware,
)
from tracely.span import Span


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
            service_name="test-api",
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
        assert span["attributes"]["http.method"] == "GET"
        assert span["attributes"]["http.route"] == "/api/users"
        assert span["attributes"]["http.status_code"] == "200"
        assert span["duration_ms"] is not None
        assert span["duration_ms"] >= 0

    @pytest.mark.asyncio
    async def test_span_has_trace_id_and_span_id(self, middleware: TracelyASGIMiddleware, captured_spans: list[dict]) -> None:
        """Root span has unique trace_id and span_id (FR55)."""
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/",
            "query_string": b"",
            "headers": [],
        }
        await middleware(scope, self._mock_receive, self._noop_send)
        span = captured_spans[0]
        assert len(span["trace_id"]) == 32
        assert len(span["span_id"]) == 16
        assert span["parent_span_id"] is None

    @pytest.mark.asyncio
    async def test_root_span_captures_service_name(self, middleware: TracelyASGIMiddleware, captured_spans: list[dict]) -> None:
        """Root span captures service_name (AC1)."""
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/",
            "query_string": b"",
            "headers": [],
        }
        await middleware(scope, self._mock_receive, self._noop_send)
        assert captured_spans[0]["service_name"] == "test-api"

    @pytest.mark.asyncio
    async def test_root_span_captures_start_time(self, middleware: TracelyASGIMiddleware, captured_spans: list[dict]) -> None:
        """Root span captures start_time (AC1)."""
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/",
            "query_string": b"",
            "headers": [],
        }
        await middleware(scope, self._mock_receive, self._noop_send)
        assert captured_spans[0]["start_time"] is not None
        assert captured_spans[0]["start_time"] > 0

    @pytest.mark.asyncio
    async def test_span_kind_is_server(self, middleware: TracelyASGIMiddleware, captured_spans: list[dict]) -> None:
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/",
            "query_string": b"",
            "headers": [],
        }
        await middleware(scope, self._mock_receive, self._noop_send)
        assert captured_spans[0]["kind"] == "SERVER"

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
        assert span["attributes"]["http.query"] == "q=test&page=1"

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
        assert captured[0]["attributes"]["http.status_code"] == "500"

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
        assert captured[0]["attributes"]["error"] == "true"
        assert captured[0]["attributes"]["error.type"] == "ValueError"
        assert captured[0]["status_code"] == "ERROR"

    @pytest.mark.asyncio
    async def test_span_type_is_span(self, middleware: TracelyASGIMiddleware, captured_spans: list[dict]) -> None:
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/",
            "query_string": b"",
            "headers": [],
        }
        await middleware(scope, self._mock_receive, self._noop_send)
        assert captured_spans[0]["span_type"] == "span"

    @pytest.mark.asyncio
    async def test_active_span_during_request(self) -> None:
        """During request processing, the root span is the active span."""
        active_during_request = []

        async def check_context_app(scope, receive, send):
            current = get_current_span()
            active_during_request.append(current)
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"OK"})

        mw = TracelyASGIMiddleware(app=check_context_app)
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/context-test",
            "query_string": b"",
            "headers": [],
        }
        await mw(scope, self._mock_receive, self._noop_send)
        assert len(active_during_request) == 1
        assert isinstance(active_during_request[0], Span)
        assert active_during_request[0].name == "GET /context-test"

    @pytest.mark.asyncio
    async def test_no_active_span_after_request(self) -> None:
        """After request completes, no active span remains."""
        async def dummy(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"OK"})

        mw = TracelyASGIMiddleware(app=dummy)
        scope = {"type": "http", "method": "GET", "path": "/", "query_string": b"", "headers": []}
        await mw(scope, self._mock_receive, self._noop_send)
        assert get_current_span() is None

    @pytest.mark.asyncio
    async def test_on_end_callback_receives_span(self) -> None:
        """on_end callback receives the Span object."""
        ended_spans: list[Span] = []

        async def dummy(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"OK"})

        mw = TracelyASGIMiddleware(app=dummy, on_end=lambda s: ended_spans.append(s))
        scope = {"type": "http", "method": "GET", "path": "/", "query_string": b"", "headers": []}
        await mw(scope, self._mock_receive, self._noop_send)
        assert len(ended_spans) == 1
        assert isinstance(ended_spans[0], Span)
        assert ended_spans[0].end_time is not None

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
        inst.activate()
        inst.deactivate()

    def test_never_raises(self, framework_info: FrameworkInfo) -> None:
        """Instrumentor never crashes even if FastAPI is not importable."""
        inst = FastAPIInstrumentor(framework_info)
        inst.activate()
        inst.deactivate()


class TestASGIRequestResponseCapture:
    """Test full request/response data capture in ASGI middleware (Story 2.4)."""

    @staticmethod
    async def _mock_receive_with_body(body: bytes = b""):
        """Create a receive callable that returns a body."""
        async def receive():
            return {"type": "http.request", "body": body, "more_body": False}
        return receive

    @staticmethod
    async def _noop_send(msg):
        pass

    def _make_scope(
        self,
        method: str = "GET",
        path: str = "/",
        query_string: bytes = b"",
        headers: list | None = None,
        scheme: str = "https",
        server: tuple = ("example.com", 443),
    ) -> dict:
        return {
            "type": "http",
            "method": method,
            "path": path,
            "query_string": query_string,
            "headers": headers or [],
            "scheme": scheme,
            "server": server,
        }

    @pytest.mark.asyncio
    async def test_captures_request_headers(self) -> None:
        """AC1: request headers are captured as span attribute."""
        captured: list[dict] = []

        async def app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"OK"})

        mw = TracelyASGIMiddleware(app=app, on_span=lambda s: captured.append(s))
        headers = [
            (b"content-type", b"application/json"),
            (b"accept", b"text/html"),
        ]
        scope = self._make_scope(headers=headers)
        receive = await self._mock_receive_with_body(b"")
        await mw(scope, receive, self._noop_send)

        assert "http.request.headers" in captured[0]["attributes"]
        import json
        hdrs = json.loads(captured[0]["attributes"]["http.request.headers"])
        assert hdrs["content-type"] == "application/json"

    @pytest.mark.asyncio
    async def test_captures_request_body(self) -> None:
        """AC1: request body is captured as span attribute."""
        captured: list[dict] = []

        async def app(scope, receive, send):
            # App must still be able to read the body
            msg = await receive()
            assert msg["body"] == b'{"name": "test"}'
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"OK"})

        mw = TracelyASGIMiddleware(app=app, on_span=lambda s: captured.append(s))
        headers = [(b"content-type", b"application/json")]
        scope = self._make_scope(method="POST", headers=headers)
        receive = await self._mock_receive_with_body(b'{"name": "test"}')
        await mw(scope, receive, self._noop_send)

        assert captured[0]["attributes"]["http.request.body"] == '{"name": "test"}'

    @pytest.mark.asyncio
    async def test_captures_full_url(self) -> None:
        """AC1: full URL (scheme+host+path+query) is captured."""
        captured: list[dict] = []

        async def app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"OK"})

        mw = TracelyASGIMiddleware(app=app, on_span=lambda s: captured.append(s))
        scope = self._make_scope(
            path="/api/users",
            query_string=b"page=1",
            scheme="https",
            server=("example.com", 443),
        )
        receive = await self._mock_receive_with_body(b"")
        await mw(scope, receive, self._noop_send)

        assert captured[0]["attributes"]["http.url"] == "https://example.com/api/users?page=1"

    @pytest.mark.asyncio
    async def test_captures_response_headers(self) -> None:
        """AC2: response headers are captured."""
        captured: list[dict] = []

        async def app(scope, receive, send):
            await send({
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"application/json"), (b"x-request-id", b"abc123")],
            })
            await send({"type": "http.response.body", "body": b'{"ok": true}'})

        mw = TracelyASGIMiddleware(app=app, on_span=lambda s: captured.append(s))
        scope = self._make_scope()
        receive = await self._mock_receive_with_body(b"")
        await mw(scope, receive, self._noop_send)

        import json
        resp_hdrs = json.loads(captured[0]["attributes"]["http.response.headers"])
        assert resp_hdrs["content-type"] == "application/json"
        assert resp_hdrs["x-request-id"] == "abc123"

    @pytest.mark.asyncio
    async def test_captures_response_body(self) -> None:
        """AC2: response body is captured."""
        captured: list[dict] = []

        async def app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"application/json")]})
            await send({"type": "http.response.body", "body": b'{"id": 1}'})

        mw = TracelyASGIMiddleware(app=app, on_span=lambda s: captured.append(s))
        scope = self._make_scope()
        receive = await self._mock_receive_with_body(b"")
        await mw(scope, receive, self._noop_send)

        assert captured[0]["attributes"]["http.response.body"] == '{"id": 1}'

    @pytest.mark.asyncio
    async def test_truncates_large_request_body(self) -> None:
        """AC3: request body > 64KB is truncated."""
        captured: list[dict] = []
        large_body = b"x" * 70000

        async def app(scope, receive, send):
            await receive()  # consume body
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"OK"})

        mw = TracelyASGIMiddleware(app=app, on_span=lambda s: captured.append(s))
        headers = [(b"content-type", b"text/plain")]
        scope = self._make_scope(method="POST", headers=headers)
        receive = await self._mock_receive_with_body(large_body)
        await mw(scope, receive, self._noop_send)

        assert captured[0]["attributes"]["http.request.body"].endswith("[truncated]")
        assert captured[0]["attributes"]["http.request.body.original_length"] == str(len(large_body))

    @pytest.mark.asyncio
    async def test_replaces_binary_request_body(self) -> None:
        """AC4: binary content type request body replaced with placeholder."""
        captured: list[dict] = []

        async def app(scope, receive, send):
            await receive()
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"OK"})

        mw = TracelyASGIMiddleware(app=app, on_span=lambda s: captured.append(s))
        headers = [(b"content-type", b"image/png")]
        scope = self._make_scope(method="POST", headers=headers)
        receive = await self._mock_receive_with_body(b"\x89PNG" + b"\x00" * 100)
        await mw(scope, receive, self._noop_send)

        assert captured[0]["attributes"]["http.request.body"].startswith("[binary:")

    @pytest.mark.asyncio
    async def test_truncates_large_response_body(self) -> None:
        """AC3: response body > 64KB is truncated."""
        captured: list[dict] = []
        large_response = b"y" * 70000

        async def app(scope, receive, send):
            await send({
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"text/plain")],
            })
            await send({"type": "http.response.body", "body": large_response})

        mw = TracelyASGIMiddleware(app=app, on_span=lambda s: captured.append(s))
        scope = self._make_scope()
        receive = await self._mock_receive_with_body(b"")
        await mw(scope, receive, self._noop_send)

        assert captured[0]["attributes"]["http.response.body"].endswith("[truncated]")
        assert captured[0]["attributes"]["http.response.body.original_length"] == str(len(large_response))

    @pytest.mark.asyncio
    async def test_replaces_binary_response_body(self) -> None:
        """AC4: binary content type response body replaced with placeholder."""
        captured: list[dict] = []

        async def app(scope, receive, send):
            await send({
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"image/jpeg")],
            })
            await send({"type": "http.response.body", "body": b"\xff\xd8\xff" + b"\x00" * 500})

        mw = TracelyASGIMiddleware(app=app, on_span=lambda s: captured.append(s))
        scope = self._make_scope()
        receive = await self._mock_receive_with_body(b"")
        await mw(scope, receive, self._noop_send)

        assert captured[0]["attributes"]["http.response.body"].startswith("[binary:")

    @pytest.mark.asyncio
    async def test_multi_chunk_response_body(self) -> None:
        """Response body arriving in multiple chunks should be concatenated."""
        captured: list[dict] = []

        async def app(scope, receive, send):
            await send({
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"text/plain")],
            })
            await send({"type": "http.response.body", "body": b"hello ", "more_body": True})
            await send({"type": "http.response.body", "body": b"world"})

        mw = TracelyASGIMiddleware(app=app, on_span=lambda s: captured.append(s))
        scope = self._make_scope()
        receive = await self._mock_receive_with_body(b"")
        await mw(scope, receive, self._noop_send)

        assert captured[0]["attributes"]["http.response.body"] == "hello world"
