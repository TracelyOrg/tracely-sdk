"""Tests for span processor and pending span pattern (AR3).

Verifies that spans are exported on start (pending_span) and
on end (span) for real-time dashboard updates.
"""

from __future__ import annotations

from typing import Any

import pytest

from tracely.span import Span
from tracely.span_processor import SpanProcessor
from tracely.transport import SpanBuffer


class TestSpanProcessor:
    """Test span lifecycle export via SpanProcessor."""

    def test_on_start_enqueues_pending_span(self) -> None:
        """Span start exports a pending_span to the buffer."""
        buffer = SpanBuffer()
        proc = SpanProcessor(buffer=buffer)

        span = Span(name="GET /api/users", kind="SERVER")
        proc.on_start(span)

        assert buffer.size == 1
        flushed = buffer.flush()
        assert flushed[0]["span_type"] == "pending_span"
        assert flushed[0]["span_name"] == "GET /api/users"
        assert flushed[0]["trace_id"] == span.trace_id
        assert flushed[0]["span_id"] == span.span_id
        assert flushed[0]["end_time"] is None
        assert flushed[0]["duration_ms"] is None

    def test_on_end_enqueues_final_span(self) -> None:
        """Span end exports a final span to the buffer."""
        buffer = SpanBuffer()
        proc = SpanProcessor(buffer=buffer)

        span = Span(name="GET /api/users", kind="SERVER")
        span.end()
        proc.on_end(span)

        assert buffer.size == 1
        flushed = buffer.flush()
        assert flushed[0]["span_type"] == "span"
        assert flushed[0]["span_name"] == "GET /api/users"
        assert flushed[0]["end_time"] is not None
        assert flushed[0]["duration_ms"] is not None
        assert flushed[0]["duration_ms"] >= 0

    def test_full_lifecycle_pending_then_final(self) -> None:
        """Start + end produces pending_span then span in buffer (AR3)."""
        buffer = SpanBuffer()
        proc = SpanProcessor(buffer=buffer)

        span = Span(name="GET /api", kind="SERVER")
        proc.on_start(span)
        span.set_attribute("http.method", "GET")
        span.end()
        proc.on_end(span)

        assert buffer.size == 2
        flushed = buffer.flush()
        assert flushed[0]["span_type"] == "pending_span"
        assert flushed[1]["span_type"] == "span"
        # Both share trace_id and span_id
        assert flushed[0]["trace_id"] == flushed[1]["trace_id"]
        assert flushed[0]["span_id"] == flushed[1]["span_id"]
        # Final span has attributes set after start
        assert flushed[1]["attributes"]["http.method"] == "GET"

    def test_on_end_callback_wiring(self) -> None:
        """SpanProcessor.on_end works as Span's on_end callback."""
        buffer = SpanBuffer()
        proc = SpanProcessor(buffer=buffer)

        span = Span(name="GET /api", kind="SERVER", on_end=proc.on_end)
        proc.on_start(span)
        span.end()  # triggers proc.on_end via callback

        assert buffer.size == 2
        flushed = buffer.flush()
        assert flushed[0]["span_type"] == "pending_span"
        assert flushed[1]["span_type"] == "span"

    def test_child_span_lifecycle(self) -> None:
        """Child spans also export pending + final."""
        buffer = SpanBuffer()
        proc = SpanProcessor(buffer=buffer)

        root = Span(name="GET /api", kind="SERVER", on_end=proc.on_end)
        proc.on_start(root)

        child = Span(name="DB SELECT", kind="CLIENT", parent=root, on_end=proc.on_end)
        proc.on_start(child)
        child.end()

        root.end()

        flushed = buffer.flush()
        assert len(flushed) == 4  # root_pending, child_pending, child_final, root_final
        types = [f["span_type"] for f in flushed]
        assert types == ["pending_span", "pending_span", "span", "span"]
        # All share trace_id
        assert all(f["trace_id"] == root.trace_id for f in flushed)

    def test_never_raises(self) -> None:
        """Processor never crashes even with broken buffer."""
        proc = SpanProcessor(buffer=None)  # type: ignore[arg-type]
        span = Span(name="GET /api", kind="SERVER")
        # Should not raise
        proc.on_start(span)
        proc.on_end(span)

    def test_flush_returns_all_pending_and_final(self) -> None:
        """Flushing buffer returns all enqueued spans."""
        buffer = SpanBuffer()
        proc = SpanProcessor(buffer=buffer)

        for i in range(3):
            s = Span(name=f"op-{i}", kind="SERVER", on_end=proc.on_end)
            proc.on_start(s)
            s.end()

        flushed = buffer.flush()
        assert len(flushed) == 6  # 3 pending + 3 final
        assert buffer.size == 0
