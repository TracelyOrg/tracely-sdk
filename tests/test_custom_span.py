"""Tests for custom span context manager (AC4)."""

from __future__ import annotations

from typing import Any

import pytest

from tracely.context import _span_context, get_current_span
from tracely.span import Span
from tracely.tracing import span


class TestCustomSpanContextManager:
    """Test `tracely.span("name")` context manager (FR58, FR59)."""

    def test_creates_child_under_active_parent(self) -> None:
        """Custom span becomes child of the currently active span."""
        child_dicts: list[dict[str, Any]] = []
        root = Span(name="GET /api/users", kind="SERVER")

        with _span_context(root):
            with span("db-lookup") as s:
                s.set_attribute("db.system", "postgresql")
                child_dicts.append(s.to_dict())

        assert len(child_dicts) == 1
        d = child_dicts[0]
        assert d["parent_span_id"] == root.span_id
        assert d["trace_id"] == root.trace_id
        assert d["span_name"] == "db-lookup"
        assert d["attributes"]["db.system"] == "postgresql"

    def test_creates_root_when_no_parent(self) -> None:
        """Without active parent, custom span is a root span."""
        with span("standalone-op") as s:
            pass

        d = s.to_dict()
        assert d["parent_span_id"] is None
        assert len(d["trace_id"]) == 32
        assert len(d["span_id"]) == 16

    def test_span_is_ended_on_exit(self) -> None:
        """Span is automatically ended when exiting the context manager."""
        with span("auto-end") as s:
            assert s._ended is False

        assert s._ended is True
        assert s.duration_ms is not None
        assert s.duration_ms >= 0

    def test_span_is_ended_on_exception(self) -> None:
        """Span is ended even if an exception occurs."""
        with pytest.raises(ValueError, match="boom"):
            with span("error-op") as s:
                raise ValueError("boom")

        assert s._ended is True
        assert s.duration_ms is not None

    def test_set_attribute_within_context(self) -> None:
        """Developer can attach custom attributes within the span (FR59)."""
        with span("custom-op") as s:
            s.set_attribute("user.id", "123")
            s.set_attribute("operation.type", "batch")

        d = s.to_dict()
        assert d["attributes"]["user.id"] == "123"
        assert d["attributes"]["operation.type"] == "batch"

    def test_nested_custom_spans(self) -> None:
        """Nested custom spans form a parent-child hierarchy."""
        spans: list[dict[str, Any]] = []
        root = Span(name="GET /api", kind="SERVER")

        with _span_context(root):
            with span("outer-op") as outer:
                with span("inner-op") as inner:
                    spans.append(inner.to_dict())
                spans.append(outer.to_dict())

        inner_d, outer_d = spans[0], spans[1]
        # outer is child of root
        assert outer_d["parent_span_id"] == root.span_id
        assert outer_d["trace_id"] == root.trace_id
        # inner is child of outer
        assert inner_d["parent_span_id"] == outer.span_id
        assert inner_d["trace_id"] == root.trace_id

    def test_context_restored_after_exit(self) -> None:
        """After exiting custom span, the previous active span is restored."""
        root = Span(name="GET /api", kind="SERVER")

        with _span_context(root):
            assert get_current_span() is root
            with span("custom-op"):
                assert get_current_span() is not root
            assert get_current_span() is root

    def test_kind_defaults_to_internal(self) -> None:
        """Custom spans default to INTERNAL kind."""
        with span("internal-op") as s:
            pass

        assert s.kind == "INTERNAL"

    def test_on_end_callback(self) -> None:
        """on_end callback is invoked when span context exits."""
        ended: list[Span] = []

        with span("callback-op", on_end=lambda s: ended.append(s)) as s:
            pass

        assert len(ended) == 1
        assert ended[0] is s

    def test_custom_kind(self) -> None:
        """Custom span can have a specific kind."""
        with span("producer-op", kind="PRODUCER") as s:
            pass

        assert s.kind == "PRODUCER"


class TestTracelyImport:
    """Verify tracely.span is accessible from the package."""

    def test_import_from_tracely(self) -> None:
        import tracely
        assert hasattr(tracely, "span")
        assert callable(tracely.span)
