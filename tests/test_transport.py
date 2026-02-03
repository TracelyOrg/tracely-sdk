"""Tests for transport layer with buffering and retry (AC4)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from tracely.transport import SpanBuffer, HttpTransport

# Stub protobuf payload for transport tests
STUB_PAYLOAD = b"\x0a\x02OK"


class TestSpanBuffer:
    """Buffer enqueues spans and flushes on threshold."""

    def test_enqueue_span(self):
        """Buffer accepts span data."""
        buf = SpanBuffer(max_size=100)
        buf.enqueue({"trace_id": "abc", "span_id": "123"})
        assert buf.size == 1

    def test_flush_returns_all_spans(self):
        """Flush returns buffered spans and clears the buffer."""
        buf = SpanBuffer(max_size=100)
        buf.enqueue({"trace_id": "abc"})
        buf.enqueue({"trace_id": "def"})
        spans = buf.flush()
        assert len(spans) == 2
        assert buf.size == 0

    def test_flush_empty_buffer(self):
        """Flush on empty buffer returns empty list."""
        buf = SpanBuffer(max_size=100)
        spans = buf.flush()
        assert spans == []

    def test_buffer_overflow_drops_oldest(self):
        """When buffer exceeds max_size, oldest spans are dropped."""
        buf = SpanBuffer(max_size=2)
        buf.enqueue({"id": "1"})
        buf.enqueue({"id": "2"})
        buf.enqueue({"id": "3"})
        assert buf.size == 2
        spans = buf.flush()
        assert spans[0]["id"] == "2"
        assert spans[1]["id"] == "3"

    def test_is_ready_at_batch_threshold(self):
        """Buffer reports ready when batch threshold is reached."""
        buf = SpanBuffer(max_size=100, batch_size=2)
        buf.enqueue({"id": "1"})
        assert buf.is_ready is False
        buf.enqueue({"id": "2"})
        assert buf.is_ready is True


class TestHttpTransport:
    """Transport sends OTLP protobuf spans over HTTP with retry."""

    @pytest.mark.asyncio
    async def test_send_success(self):
        """Successful send returns True."""
        transport = HttpTransport(
            endpoint="https://api.tracely.dev",
            api_key="trly_abc123",
        )
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = lambda: None

        with patch.object(transport, "_client") as mock_client:
            mock_client.post = AsyncMock(return_value=mock_response)
            result = await transport.send(STUB_PAYLOAD)
            assert result is True
            mock_client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_uses_protobuf_content_type(self):
        """Transport sends content= (bytes) not json= to endpoint."""
        transport = HttpTransport(
            endpoint="https://api.tracely.dev",
            api_key="trly_abc123",
        )
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = lambda: None

        with patch.object(transport, "_client") as mock_client:
            mock_client.post = AsyncMock(return_value=mock_response)
            await transport.send(STUB_PAYLOAD)
            call_kwargs = mock_client.post.call_args
            # Must use content= kwarg (bytes), not json=
            assert call_kwargs.kwargs.get("content") == STUB_PAYLOAD or call_kwargs[1].get("content") == STUB_PAYLOAD

    @pytest.mark.asyncio
    async def test_send_empty_payload_returns_true(self):
        """Empty payload is a no-op, returns True."""
        transport = HttpTransport(
            endpoint="https://api.tracely.dev",
            api_key="trly_abc123",
        )
        result = await transport.send(b"")
        assert result is True

    @pytest.mark.asyncio
    async def test_send_retries_on_failure(self):
        """Transport retries on server error with backoff."""
        transport = HttpTransport(
            endpoint="https://api.tracely.dev",
            api_key="trly_abc123",
            max_retries=2,
            base_delay=0.01,  # Fast for testing
        )

        mock_request = httpx.Request("POST", "https://api.tracely.dev/v1/traces")
        fail_response = httpx.Response(500, request=mock_request)

        ok_response = AsyncMock()
        ok_response.status_code = 200
        ok_response.raise_for_status = lambda: None

        with patch.object(transport, "_client") as mock_client:
            mock_client.post = AsyncMock(side_effect=[fail_response, ok_response])
            await transport.send(STUB_PAYLOAD)
            assert mock_client.post.call_count == 2

    @pytest.mark.asyncio
    async def test_send_catches_all_errors_silently(self):
        """AC4/FR10: Transport never raises to caller."""
        transport = HttpTransport(
            endpoint="https://api.tracely.dev",
            api_key="trly_abc123",
            max_retries=1,
            base_delay=0.01,
        )

        with patch.object(transport, "_client") as mock_client:
            mock_client.post = AsyncMock(side_effect=ConnectionError("unreachable"))
            # Must NOT raise
            result = await transport.send(STUB_PAYLOAD)
            assert result is False

    @pytest.mark.asyncio
    async def test_send_network_error_retries(self):
        """AC4/NFR22: Network errors trigger retry."""
        transport = HttpTransport(
            endpoint="https://api.tracely.dev",
            api_key="trly_abc123",
            max_retries=2,
            base_delay=0.01,
        )

        ok_response = AsyncMock()
        ok_response.status_code = 200
        ok_response.raise_for_status = lambda: None

        with patch.object(transport, "_client") as mock_client:
            mock_client.post = AsyncMock(
                side_effect=[httpx.ConnectError("timeout"), ok_response]
            )
            await transport.send(STUB_PAYLOAD)
            assert mock_client.post.call_count == 2

    @pytest.mark.asyncio
    async def test_send_all_retries_exhausted_no_raise(self):
        """When all retries fail, transport still does not raise."""
        transport = HttpTransport(
            endpoint="https://api.tracely.dev",
            api_key="trly_abc123",
            max_retries=2,
            base_delay=0.01,
        )

        with patch.object(transport, "_client") as mock_client:
            mock_client.post = AsyncMock(
                side_effect=httpx.ConnectError("always fails")
            )
            # Must NOT raise even after all retries
            result = await transport.send(STUB_PAYLOAD)
            assert result is False
            assert mock_client.post.call_count == 3  # initial + 2 retries

    @pytest.mark.asyncio
    async def test_exponential_backoff_delays(self):
        """AC4: Verify exponential backoff 1s, 2s, 4s, max 30s."""
        transport = HttpTransport(
            endpoint="https://api.tracely.dev",
            api_key="trly_abc123",
            max_retries=4,
            base_delay=1.0,
            max_delay=30.0,
        )
        recorded_delays: list[float] = []

        async def mock_sleep(delay: float) -> None:
            recorded_delays.append(delay)

        with patch.object(transport, "_client") as mock_client, \
             patch("tracely.transport.asyncio.sleep", side_effect=mock_sleep):
            mock_client.post = AsyncMock(
                side_effect=httpx.ConnectError("always fails")
            )
            await transport.send(STUB_PAYLOAD)

        # Expected: 1.0, 2.0, 4.0, 8.0 (4 retries)
        assert recorded_delays == [1.0, 2.0, 4.0, 8.0]

    @pytest.mark.asyncio
    async def test_backoff_capped_at_max_delay(self):
        """AC4: Delay never exceeds max_delay (30s)."""
        transport = HttpTransport(
            endpoint="https://api.tracely.dev",
            api_key="trly_abc123",
            max_retries=6,
            base_delay=1.0,
            max_delay=30.0,
        )
        recorded_delays: list[float] = []

        async def mock_sleep(delay: float) -> None:
            recorded_delays.append(delay)

        with patch.object(transport, "_client") as mock_client, \
             patch("tracely.transport.asyncio.sleep", side_effect=mock_sleep):
            mock_client.post = AsyncMock(
                side_effect=httpx.ConnectError("always fails")
            )
            await transport.send(STUB_PAYLOAD)

        # 1, 2, 4, 8, 16, 30 (capped)
        assert recorded_delays == [1.0, 2.0, 4.0, 8.0, 16.0, 30.0]

    @pytest.mark.asyncio
    async def test_protobuf_content_type_header(self):
        """HttpTransport uses application/x-protobuf content type."""
        transport = HttpTransport(
            endpoint="https://api.tracely.dev",
            api_key="trly_abc123",
        )
        assert transport._client.headers["content-type"] == "application/x-protobuf"
