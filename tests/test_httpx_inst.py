"""Tests for external HTTP call instrumentation (AC3)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from tracely.context import _span_context, get_current_span
from tracely.instrumentation.httpx_inst import HttpxInstrumentor
from tracely.span import Span


@pytest.fixture(autouse=True)
def cleanup_httpx_patches():
    """Ensure httpx is restored after each test."""
    orig_sync = httpx.Client.send
    orig_async = httpx.AsyncClient.send
    yield
    httpx.Client.send = orig_sync  # type: ignore[assignment]
    httpx.AsyncClient.send = orig_async  # type: ignore[assignment]


def _mock_transport(status: int = 200) -> httpx.MockTransport:
    """Return a MockTransport that responds with the given status."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, request=request)
    return httpx.MockTransport(handler)


def _async_mock_transport(status: int = 200) -> httpx.MockTransport:
    """Return a MockTransport for async clients."""
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, request=request)
    return httpx.MockTransport(handler)


class TestHttpxInstrumentor:
    """Test httpx external call instrumentation."""

    def test_activate_deactivate(self) -> None:
        inst = HttpxInstrumentor()
        inst.activate()
        assert inst.is_active
        inst.deactivate()
        assert not inst.is_active

    def test_idempotent_activate(self) -> None:
        inst = HttpxInstrumentor()
        inst.activate()
        inst.activate()  # Should not error
        inst.deactivate()

    def test_sync_creates_child_span(self) -> None:
        """Sync httpx call creates child span linked to parent (AC3)."""
        inst = HttpxInstrumentor()
        inst.activate()

        child_spans: list[dict[str, Any]] = []
        root = Span(name="GET /api/users", kind="SERVER")

        original_end = Span.end

        def capturing_end(self_span: Span) -> None:
            if self_span.parent_span_id is not None:
                child_spans.append(self_span.to_dict())
            original_end(self_span)

        with _span_context(root):
            # Temporarily patch Span.end to capture child spans
            old_end = Span.end
            Span.end = capturing_end  # type: ignore[assignment]
            try:
                with httpx.Client(transport=_mock_transport()) as client:
                    response = client.get("https://api.example.com/data")
            finally:
                Span.end = old_end  # type: ignore[assignment]

        inst.deactivate()

        assert len(child_spans) == 1
        span = child_spans[0]
        assert span["parent_span_id"] == root.span_id
        assert span["trace_id"] == root.trace_id
        assert span["attributes"]["http.method"] == "GET"
        assert "api.example.com" in span["attributes"]["http.url"]
        assert span["attributes"]["http.status_code"] == "200"
        assert span["kind"] == "CLIENT"

    @pytest.mark.asyncio
    async def test_async_creates_child_span(self) -> None:
        """Async httpx call creates child span with method, URL, status (AC3)."""
        inst = HttpxInstrumentor()
        inst.activate()

        child_spans: list[dict[str, Any]] = []
        root = Span(name="GET /api/users", kind="SERVER")

        original_end = Span.end

        def capturing_end(self_span: Span) -> None:
            if self_span.parent_span_id is not None:
                child_spans.append(self_span.to_dict())
            original_end(self_span)

        with _span_context(root):
            old_end = Span.end
            Span.end = capturing_end  # type: ignore[assignment]
            try:
                async with httpx.AsyncClient(transport=_async_mock_transport()) as client:
                    response = await client.get("https://api.example.com/data")
            finally:
                Span.end = old_end  # type: ignore[assignment]

        inst.deactivate()

        assert response.status_code == 200
        assert len(child_spans) == 1
        span = child_spans[0]
        assert span["parent_span_id"] == root.span_id
        assert span["trace_id"] == root.trace_id
        assert span["attributes"]["http.method"] == "GET"
        assert "api.example.com" in span["attributes"]["http.url"]
        assert span["attributes"]["http.status_code"] == "200"
        assert span["kind"] == "CLIENT"

    def test_no_span_without_parent(self) -> None:
        """Without active parent span, calls pass through without child span."""
        inst = HttpxInstrumentor()
        inst.activate()

        child_spans: list[dict[str, Any]] = []
        original_end = Span.end

        def capturing_end(self_span: Span) -> None:
            if self_span.parent_span_id is not None:
                child_spans.append(self_span.to_dict())
            original_end(self_span)

        old_end = Span.end
        Span.end = capturing_end  # type: ignore[assignment]
        try:
            with httpx.Client(transport=_mock_transport()) as client:
                response = client.get("https://example.com")
        finally:
            Span.end = old_end  # type: ignore[assignment]

        inst.deactivate()
        assert response.status_code == 200
        assert len(child_spans) == 0

    def test_captures_error_status(self) -> None:
        """Child span records error status for 4xx/5xx responses."""
        inst = HttpxInstrumentor()
        inst.activate()

        child_spans: list[dict[str, Any]] = []
        root = Span(name="GET /api", kind="SERVER")

        original_end = Span.end

        def capturing_end(self_span: Span) -> None:
            if self_span.parent_span_id is not None:
                child_spans.append(self_span.to_dict())
            original_end(self_span)

        with _span_context(root):
            old_end = Span.end
            Span.end = capturing_end  # type: ignore[assignment]
            try:
                with httpx.Client(transport=_mock_transport(500)) as client:
                    response = client.get("https://api.example.com/fail")
            finally:
                Span.end = old_end  # type: ignore[assignment]

        inst.deactivate()

        assert response.status_code == 500
        assert len(child_spans) == 1
        assert child_spans[0]["status_code"] == "ERROR"
        assert child_spans[0]["attributes"]["http.status_code"] == "500"

    def test_captures_connection_error(self) -> None:
        """Child span records error when connection fails."""
        inst = HttpxInstrumentor()
        inst.activate()

        child_spans: list[dict[str, Any]] = []
        root = Span(name="GET /api", kind="SERVER")

        original_end = Span.end

        def capturing_end(self_span: Span) -> None:
            if self_span.parent_span_id is not None:
                child_spans.append(self_span.to_dict())
            original_end(self_span)

        def error_handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused")

        with _span_context(root):
            old_end = Span.end
            Span.end = capturing_end  # type: ignore[assignment]
            try:
                with httpx.Client(transport=httpx.MockTransport(error_handler)) as client:
                    with pytest.raises(httpx.ConnectError):
                        client.get("https://api.example.com/fail")
            finally:
                Span.end = old_end  # type: ignore[assignment]

        inst.deactivate()

        assert len(child_spans) == 1
        span = child_spans[0]
        assert span["status_code"] == "ERROR"
        assert span["attributes"]["error"] == "true"
        assert span["attributes"]["error.type"] == "ConnectError"
