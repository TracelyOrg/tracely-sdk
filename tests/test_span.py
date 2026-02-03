"""Tests for the Span model and trace ID generation."""

from __future__ import annotations

import time
from unittest.mock import MagicMock

from tracely.span import Span, generate_trace_id, generate_span_id


class TestIdGeneration:
    """Tests for trace_id and span_id generation."""

    def test_trace_id_is_32_hex_chars(self) -> None:
        tid = generate_trace_id()
        assert len(tid) == 32
        assert all(c in "0123456789abcdef" for c in tid)

    def test_span_id_is_16_hex_chars(self) -> None:
        sid = generate_span_id()
        assert len(sid) == 16
        assert all(c in "0123456789abcdef" for c in sid)

    def test_trace_ids_are_unique(self) -> None:
        ids = {generate_trace_id() for _ in range(100)}
        assert len(ids) == 100

    def test_span_ids_are_unique(self) -> None:
        ids = {generate_span_id() for _ in range(100)}
        assert len(ids) == 100


class TestSpanCreation:
    """Tests for Span construction."""

    def test_root_span_has_trace_id_and_span_id(self) -> None:
        span = Span(name="test-root")
        assert len(span.trace_id) == 32
        assert len(span.span_id) == 16
        assert span.parent_span_id is None

    def test_root_span_has_no_parent(self) -> None:
        span = Span(name="root")
        assert span.parent_span_id is None

    def test_child_span_inherits_trace_id(self) -> None:
        parent = Span(name="parent")
        child = Span(name="child", parent=parent)
        assert child.trace_id == parent.trace_id
        assert child.parent_span_id == parent.span_id
        assert child.span_id != parent.span_id

    def test_span_name_is_set(self) -> None:
        span = Span(name="my-operation")
        assert span.name == "my-operation"

    def test_span_type_default_is_span(self) -> None:
        span = Span(name="test")
        assert span.span_type == "span"

    def test_span_kind_default_is_internal(self) -> None:
        span = Span(name="test")
        assert span.kind == "INTERNAL"

    def test_span_kind_can_be_set(self) -> None:
        span = Span(name="http-in", kind="SERVER")
        assert span.kind == "SERVER"

    def test_span_service_name(self) -> None:
        span = Span(name="test", service_name="api")
        assert span.service_name == "api"

    def test_span_start_time_is_set(self) -> None:
        before = time.time()
        span = Span(name="test")
        after = time.time()
        assert before <= span.start_time <= after

    def test_span_is_not_ended_initially(self) -> None:
        span = Span(name="test")
        assert span.end_time is None
        assert span.duration_ms is None


class TestSpanAttributes:
    """Tests for set_attribute and attributes dict."""

    def test_set_attribute_stores_value(self) -> None:
        span = Span(name="test")
        span.set_attribute("http.method", "GET")
        assert span.attributes["http.method"] == "GET"

    def test_set_attribute_overwrites_existing(self) -> None:
        span = Span(name="test")
        span.set_attribute("key", "v1")
        span.set_attribute("key", "v2")
        assert span.attributes["key"] == "v2"

    def test_set_attribute_converts_value_to_string(self) -> None:
        span = Span(name="test")
        span.set_attribute("status", 200)
        assert span.attributes["status"] == "200"

    def test_set_attribute_on_ended_span_is_noop(self) -> None:
        span = Span(name="test")
        span.end()
        span.set_attribute("late", "value")
        assert "late" not in span.attributes

    def test_initial_attributes_are_empty(self) -> None:
        span = Span(name="test")
        assert span.attributes == {}

    def test_set_multiple_attributes(self) -> None:
        span = Span(name="test")
        span.set_attribute("a", "1")
        span.set_attribute("b", "2")
        span.set_attribute("c", "3")
        assert len(span.attributes) == 3


class TestSpanEnd:
    """Tests for Span.end() method."""

    def test_end_sets_end_time(self) -> None:
        span = Span(name="test")
        span.end()
        assert span.end_time is not None
        assert span.end_time >= span.start_time

    def test_end_computes_duration_ms(self) -> None:
        span = Span(name="test")
        time.sleep(0.01)  # 10ms
        span.end()
        assert span.duration_ms is not None
        assert span.duration_ms >= 10.0

    def test_end_is_idempotent(self) -> None:
        span = Span(name="test")
        span.end()
        first_end = span.end_time
        span.end()
        assert span.end_time == first_end

    def test_end_calls_on_end_callback(self) -> None:
        callback = MagicMock()
        span = Span(name="test", on_end=callback)
        span.end()
        callback.assert_called_once_with(span)

    def test_end_callback_not_called_twice(self) -> None:
        callback = MagicMock()
        span = Span(name="test", on_end=callback)
        span.end()
        span.end()
        callback.assert_called_once()

    def test_end_callback_error_does_not_raise(self) -> None:
        callback = MagicMock(side_effect=RuntimeError("boom"))
        span = Span(name="test", on_end=callback)
        # Should not raise
        span.end()
        assert span.end_time is not None


class TestSpanStatus:
    """Tests for span status tracking."""

    def test_default_status_is_unset(self) -> None:
        span = Span(name="test")
        assert span.status_code == "UNSET"
        assert span.status_message == ""

    def test_set_status_ok(self) -> None:
        span = Span(name="test")
        span.set_status("OK")
        assert span.status_code == "OK"

    def test_set_status_error_with_message(self) -> None:
        span = Span(name="test")
        span.set_status("ERROR", "something broke")
        assert span.status_code == "ERROR"
        assert span.status_message == "something broke"

    def test_set_status_on_ended_span_is_noop(self) -> None:
        span = Span(name="test")
        span.end()
        span.set_status("ERROR", "late error")
        assert span.status_code == "UNSET"


class TestSpanToDict:
    """Tests for Span.to_dict() serialization."""

    def test_to_dict_contains_required_fields(self) -> None:
        span = Span(name="test-op", service_name="api")
        span.set_attribute("http.method", "GET")
        span.end()
        d = span.to_dict()

        assert d["trace_id"] == span.trace_id
        assert d["span_id"] == span.span_id
        assert d["parent_span_id"] is None
        assert d["span_name"] == "test-op"
        assert d["span_type"] == "span"
        assert d["kind"] == "INTERNAL"
        assert d["service_name"] == "api"
        assert d["start_time"] == span.start_time
        assert d["end_time"] == span.end_time
        assert d["duration_ms"] == span.duration_ms
        assert d["status_code"] == "UNSET"
        assert d["status_message"] == ""
        assert d["attributes"] == {"http.method": "GET"}

    def test_to_dict_child_span_has_parent_id(self) -> None:
        parent = Span(name="parent")
        child = Span(name="child", parent=parent)
        child.end()
        d = child.to_dict()
        assert d["parent_span_id"] == parent.span_id

    def test_to_dict_pending_span(self) -> None:
        span = Span(name="pending", span_type="pending_span")
        d = span.to_dict()
        assert d["span_type"] == "pending_span"
        assert d["end_time"] is None
        assert d["duration_ms"] is None
