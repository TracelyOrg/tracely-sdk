"""Tests for BatchSpanExporter with background flush loop (FR9, AC3)."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, patch

import pytest

from tracely.exporter import BatchSpanExporter
from tracely.transport import SpanBuffer, HttpTransport


def _make_span_dict(span_id: str = "a" * 16, **kwargs):
    base = {
        "trace_id": "b" * 32,
        "span_id": span_id,
        "parent_span_id": None,
        "span_name": "GET /test",
        "span_type": "span",
        "kind": "SERVER",
        "service_name": "test",
        "start_time": 1700000000.0,
        "end_time": 1700000001.0,
        "duration_ms": 1000.0,
        "status_code": "OK",
        "status_message": "",
        "attributes": {},
        "events": [],
        "event_count": 0,
    }
    base.update(kwargs)
    return base


class TestBatchSpanExporter:
    """BatchSpanExporter flushes buffer on interval and size threshold."""

    def test_start_creates_background_thread(self):
        """start() spawns a background daemon thread."""
        buf = SpanBuffer()
        transport = AsyncMock(spec=HttpTransport)
        exporter = BatchSpanExporter(buffer=buf, transport=transport)

        exporter.start()
        assert exporter._thread is not None
        assert exporter._thread.is_alive()
        assert exporter._thread.daemon is True

        exporter.stop()

    def test_stop_joins_thread(self):
        """stop() terminates the background thread."""
        buf = SpanBuffer()
        transport = AsyncMock(spec=HttpTransport)
        transport.send = AsyncMock(return_value=True)
        exporter = BatchSpanExporter(buffer=buf, transport=transport)

        exporter.start()
        exporter.stop()
        assert not exporter._thread.is_alive()

    def test_interval_flush(self):
        """Buffer is flushed on interval even below batch threshold."""
        buf = SpanBuffer(batch_size=50)
        transport = AsyncMock(spec=HttpTransport)
        transport.send = AsyncMock(return_value=True)

        exporter = BatchSpanExporter(
            buffer=buf, transport=transport, flush_interval=0.05,
        )
        buf.enqueue(_make_span_dict(span_id="1" * 16))

        exporter.start()
        time.sleep(0.2)  # Allow 2-3 flush cycles
        exporter.stop()

        assert transport.send.call_count >= 1
        assert buf.size == 0

    def test_batch_size_threshold_flush(self):
        """Buffer is flushed when batch size threshold is reached via notify."""
        buf = SpanBuffer(batch_size=3)
        transport = AsyncMock(spec=HttpTransport)
        transport.send = AsyncMock(return_value=True)

        exporter = BatchSpanExporter(
            buffer=buf, transport=transport, flush_interval=10.0,  # Long interval
        )

        exporter.start()

        # Add spans to hit batch threshold
        for i in range(3):
            buf.enqueue(_make_span_dict(span_id=f"{i}" * 16))

        # Notify exporter that buffer has data
        exporter.notify()
        time.sleep(0.2)  # Allow flush to execute

        exporter.stop()

        assert transport.send.call_count >= 1

    def test_shutdown_drains_buffer(self):
        """stop() flushes remaining spans before stopping."""
        buf = SpanBuffer(batch_size=100)
        transport = AsyncMock(spec=HttpTransport)
        transport.send = AsyncMock(return_value=True)

        exporter = BatchSpanExporter(
            buffer=buf, transport=transport, flush_interval=10.0,
        )

        buf.enqueue(_make_span_dict(span_id="1" * 16))
        buf.enqueue(_make_span_dict(span_id="2" * 16))

        exporter.start()
        exporter.stop()

        # Buffer should be drained on shutdown (final flush in thread)
        assert buf.size == 0
        assert transport.send.call_count >= 1

    def test_empty_buffer_no_send(self):
        """No transport call when buffer is empty."""
        buf = SpanBuffer()
        transport = AsyncMock(spec=HttpTransport)
        transport.send = AsyncMock(return_value=True)

        exporter = BatchSpanExporter(
            buffer=buf, transport=transport, flush_interval=0.05,
        )

        exporter.start()
        time.sleep(0.15)
        exporter.stop()

        # send should not be called for empty buffer
        transport.send.assert_not_called()

    def test_serializes_spans_to_otlp(self):
        """Exporter uses otlp.serialize_spans for OTLP protobuf format."""
        buf = SpanBuffer(batch_size=50)
        transport = AsyncMock(spec=HttpTransport)
        transport.send = AsyncMock(return_value=True)

        exporter = BatchSpanExporter(
            buffer=buf, transport=transport, flush_interval=0.05,
        )

        buf.enqueue(_make_span_dict())

        with patch("tracely.exporter.serialize_spans", return_value=b"proto-data") as mock_serialize:
            exporter.start()
            time.sleep(0.15)
            exporter.stop()

            mock_serialize.assert_called()
            transport.send.assert_called_with(b"proto-data")

    def test_fail_silent_on_serialization_error(self):
        """FR10: Serialization errors are caught silently."""
        buf = SpanBuffer(batch_size=50)
        transport = AsyncMock(spec=HttpTransport)

        exporter = BatchSpanExporter(
            buffer=buf, transport=transport, flush_interval=0.05,
        )

        buf.enqueue(_make_span_dict())

        with patch("tracely.exporter.serialize_spans", side_effect=Exception("proto error")):
            exporter.start()
            time.sleep(0.15)
            # Should NOT raise
            exporter.stop()

    def test_multiple_flushes(self):
        """Exporter handles multiple flush cycles correctly."""
        buf = SpanBuffer(batch_size=50)
        transport = AsyncMock(spec=HttpTransport)
        transport.send = AsyncMock(return_value=True)

        exporter = BatchSpanExporter(
            buffer=buf, transport=transport, flush_interval=0.05,
        )

        exporter.start()

        buf.enqueue(_make_span_dict(span_id="1" * 16))
        time.sleep(0.1)
        buf.enqueue(_make_span_dict(span_id="2" * 16))
        time.sleep(0.1)

        exporter.stop()

        assert transport.send.call_count >= 2

    def test_transport_failure_does_not_crash(self):
        """FR10/NFR22: Transport failure does not crash exporter thread."""
        buf = SpanBuffer(batch_size=50)
        transport = AsyncMock(spec=HttpTransport)
        transport.send = AsyncMock(return_value=False)

        exporter = BatchSpanExporter(
            buffer=buf, transport=transport, flush_interval=0.05,
        )

        buf.enqueue(_make_span_dict())

        exporter.start()
        time.sleep(0.15)

        assert exporter._thread.is_alive()

        exporter.stop()
