"""Integration tests for the full span pipeline (AC1, AC2, AC3, AC4).

Verifies end-to-end: span creation → processor → buffer → exporter → transport.
Uses real SpanBuffer/SpanProcessor/BatchSpanExporter with mocked HttpTransport.
"""

from __future__ import annotations

import os
import time
from unittest.mock import AsyncMock, patch

import pytest

import tracely
from tracely.exporter import BatchSpanExporter
from tracely.otlp import serialize_spans
from tracely.sdk import _reset, _sdk_instance
from tracely.span import Span
from tracely.span_processor import SpanProcessor, get_processor, on_span_end, on_span_start
from tracely.transport import HttpTransport, SpanBuffer


class TestFullPipeline:
    """Integration: span lifecycle → buffer → OTLP export."""

    def setup_method(self):
        _reset()

    def teardown_method(self):
        _reset()

    def test_pending_span_enqueued_on_start(self):
        """AC1: on_span_start puts a pending_span dict in the buffer."""
        buf = SpanBuffer()
        proc = SpanProcessor(buffer=buf)

        span = Span(name="GET /users", kind="SERVER", service_name="api")
        proc.on_start(span)

        items = buf.flush()
        assert len(items) == 1
        assert items[0]["span_type"] == "pending_span"
        assert items[0]["span_name"] == "GET /users"
        assert items[0]["trace_id"] is not None
        assert items[0]["span_id"] is not None

    def test_final_span_enqueued_on_end(self):
        """AC2: on_span_end puts a span dict with span_type='span' in buffer."""
        buf = SpanBuffer()
        proc = SpanProcessor(buffer=buf)

        span = Span(name="GET /users", kind="SERVER", service_name="api")
        proc.on_start(span)
        span.set_attribute("http.status_code", "200")
        span.end()
        proc.on_end(span)

        items = buf.flush()
        assert len(items) == 2
        assert items[0]["span_type"] == "pending_span"
        assert items[1]["span_type"] == "span"
        assert items[1]["end_time"] is not None
        assert items[1]["attributes"]["http.status_code"] == "200"

    def test_on_end_callback_wires_to_processor(self):
        """Span's on_end callback calls processor.on_end automatically."""
        buf = SpanBuffer()
        proc = SpanProcessor(buffer=buf)

        span = Span(name="GET /", kind="SERVER", on_end=proc.on_end)
        proc.on_start(span)
        span.end()  # triggers on_end callback → proc.on_end

        items = buf.flush()
        assert len(items) == 2
        assert items[0]["span_type"] == "pending_span"
        assert items[1]["span_type"] == "span"

    def test_global_processor_registry(self):
        """Global on_span_start / on_span_end use registered processor."""
        buf = SpanBuffer()
        proc = SpanProcessor(buffer=buf)

        from tracely.span_processor import set_processor
        set_processor(proc)
        try:
            span = Span(name="GET /", kind="SERVER", on_end=on_span_end)
            on_span_start(span)
            span.end()  # triggers on_span_end via callback

            items = buf.flush()
            assert len(items) == 2
            assert items[0]["span_type"] == "pending_span"
            assert items[1]["span_type"] == "span"
        finally:
            set_processor(None)

    def test_global_processor_noop_when_none(self):
        """on_span_start/on_span_end are no-ops when no processor is set."""
        from tracely.span_processor import set_processor
        set_processor(None)

        span = Span(name="GET /", kind="SERVER")
        # Should not raise
        on_span_start(span)
        on_span_end(span)

    def test_buffer_to_otlp_serialization(self):
        """AC3: Buffered spans serialize to valid OTLP protobuf."""
        from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
            ExportTraceServiceRequest,
        )

        buf = SpanBuffer()
        proc = SpanProcessor(buffer=buf)

        span = Span(name="POST /orders", kind="SERVER", service_name="api")
        proc.on_start(span)
        span.end()
        proc.on_end(span)

        items = buf.flush()
        payload = serialize_spans(items)

        assert isinstance(payload, bytes)
        assert len(payload) > 0

        # Deserialize and verify
        req = ExportTraceServiceRequest()
        req.ParseFromString(payload)
        assert len(req.resource_spans) == 1
        scope_spans = req.resource_spans[0].scope_spans[0]
        # 2 spans: pending + final
        assert len(scope_spans.spans) == 2

    def test_exporter_flushes_buffer_via_transport(self):
        """AC3: BatchSpanExporter flushes buffer through transport."""
        buf = SpanBuffer()
        transport = AsyncMock(spec=HttpTransport)
        transport.send = AsyncMock(return_value=True)

        exporter = BatchSpanExporter(
            buffer=buf,
            transport=transport,
            flush_interval=0.1,
        )

        # Enqueue a span
        proc = SpanProcessor(buffer=buf)
        span = Span(name="GET /", kind="SERVER", service_name="test")
        proc.on_start(span)

        exporter.start()
        try:
            # Wait for flush
            time.sleep(0.5)
        finally:
            exporter.stop()

        # Transport.send should have been called with bytes payload
        assert transport.send.called
        call_args = transport.send.call_args
        payload = call_args[0][0] if call_args[0] else call_args[1].get("payload")
        assert isinstance(payload, bytes)

    def test_sdk_init_creates_full_pipeline(self):
        """init() with API key creates buffer, processor, exporter, transport."""
        with patch.dict(os.environ, {"TRACELY_API_KEY": "trly_test123"}):
            tracely.init()
            sdk = _sdk_instance()

            assert sdk is not None
            assert sdk.enabled is True
            assert sdk.buffer is not None
            assert sdk.transport is not None
            assert sdk.processor is not None
            assert sdk.exporter is not None
            assert get_processor() is sdk.processor

    def test_sdk_init_disabled_no_pipeline(self):
        """init() without API key creates no pipeline components."""
        with patch.dict(os.environ, {}, clear=True):
            tracely.init()
            sdk = _sdk_instance()

            assert sdk is not None
            assert sdk.enabled is False
            assert sdk.buffer is None
            assert sdk.transport is None
            assert sdk.processor is None
            assert sdk.exporter is None
            assert get_processor() is None

    def test_sdk_shutdown_clears_processor(self):
        """shutdown() clears the global processor."""
        with patch.dict(os.environ, {"TRACELY_API_KEY": "trly_test123"}):
            tracely.init()
            assert get_processor() is not None

            tracely.shutdown()
            assert get_processor() is None

    def test_tracing_api_uses_global_processor(self):
        """tracely.span() context manager wires to global processor."""
        buf = SpanBuffer()
        proc = SpanProcessor(buffer=buf)

        from tracely.span_processor import set_processor
        set_processor(proc)
        try:
            with tracely.span("db-query", kind="CLIENT") as s:
                s.set_attribute("db.statement", "SELECT 1")

            items = buf.flush()
            # pending_span + final span
            assert len(items) == 2
            assert items[0]["span_type"] == "pending_span"
            assert items[0]["span_name"] == "db-query"
            assert items[1]["span_type"] == "span"
            assert items[1]["attributes"]["db.statement"] == "SELECT 1"
        finally:
            set_processor(None)

    def test_child_span_pipeline(self):
        """Child spans also go through the global processor."""
        buf = SpanBuffer()
        proc = SpanProcessor(buffer=buf)

        from tracely.span_processor import set_processor
        set_processor(proc)
        try:
            with tracely.span("http-handler", kind="SERVER") as parent:
                with tracely.span("db-query", kind="CLIENT") as child:
                    child.set_attribute("db.system", "postgres")

            items = buf.flush()
            # 4 items: parent pending, child pending, child final, parent final
            assert len(items) == 4
            types = [i["span_type"] for i in items]
            assert types.count("pending_span") == 2
            assert types.count("span") == 2
        finally:
            set_processor(None)

    def test_buffer_overflow_drops_oldest(self):
        """AC4: Buffer cap of 1000 drops oldest spans when full."""
        buf = SpanBuffer(max_size=5)
        proc = SpanProcessor(buffer=buf)

        for i in range(10):
            span = Span(name=f"span-{i}", kind="SERVER")
            proc.on_start(span)

        items = buf.flush()
        assert len(items) == 5
        # Should have the 5 most recent
        names = [i["span_name"] for i in items]
        assert names == [f"span-{i}" for i in range(5, 10)]

    def test_every_span_triggers_notify(self):
        """AC3: Processor calls notify on every span for near-instant delivery."""
        notified = []
        buf = SpanBuffer(batch_size=3)
        proc = SpanProcessor(buffer=buf, on_buffer_ready=lambda: notified.append(True))

        # Each span triggers notify for immediate flush
        for i in range(3):
            span = Span(name="GET /", kind="SERVER")
            proc.on_start(span)
            assert len(notified) == i + 1

    def test_fail_silent_on_processor_error(self):
        """AC4/FR10: Processor errors don't crash the host."""
        buf = SpanBuffer()
        proc = SpanProcessor(buffer=buf)

        # Make buffer.enqueue raise
        original_enqueue = buf.enqueue
        def failing_enqueue(item):
            raise RuntimeError("buffer broken")
        buf.enqueue = failing_enqueue

        span = Span(name="GET /", kind="SERVER")
        # Should not raise
        proc.on_start(span)
        proc.on_end(span)
