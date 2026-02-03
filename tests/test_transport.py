"""Tests for transport layer with buffering and retry (AC4)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from tracely.transport import SpanBuffer, HttpTransport


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
    """Transport sends spans over HTTP with retry."""

    @pytest.mark.asyncio
    async def test_send_success(self):
        """Successful send clears buffer."""
        transport = HttpTransport(
            endpoint="https://api.tracely.dev",
            api_key="trly_abc123",
        )
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = lambda: None

        with patch.object(transport, "_client") as mock_client:
            mock_client.post = AsyncMock(return_value=mock_response)
            await transport.send([{"trace_id": "abc"}])
            mock_client.post.assert_called_once()

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
            await transport.send([{"trace_id": "abc"}])
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
            await transport.send([{"trace_id": "abc"}])

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
            await transport.send([{"trace_id": "abc"}])
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
            await transport.send([{"trace_id": "abc"}])
            assert mock_client.post.call_count == 3  # initial + 2 retries
