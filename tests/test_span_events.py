"""Tests for span events and tracely.debug/info/warning/error API."""

from __future__ import annotations

from typing import Any

import pytest

from tracely.context import _span_context
from tracely.span import Span


class TestSpanAddEvent:
    """Test Span.add_event() method."""

    def test_add_event_stores_event(self) -> None:
        """add_event appends an event with timestamp, level, message."""
        span = Span(name="GET /api", kind="SERVER")
        span.add_event("User fetched", level="INFO")

        assert len(span.events) == 1
        event = span.events[0]
        assert event["message"] == "User fetched"
        assert event["level"] == "INFO"
        assert isinstance(event["timestamp"], float)
        assert event["timestamp"] > 0

    def test_add_event_default_level_is_info(self) -> None:
        """Default level is INFO if not specified."""
        span = Span(name="op", kind="INTERNAL")
        span.add_event("something happened")

        assert span.events[0]["level"] == "INFO"

    def test_add_event_noop_after_end(self) -> None:
        """No event is added to an ended span."""
        span = Span(name="op", kind="INTERNAL")
        span.end()
        span.add_event("too late")

        assert len(span.events) == 0

    def test_add_event_with_attributes(self) -> None:
        """Events can carry custom attributes."""
        span = Span(name="op", kind="INTERNAL")
        span.add_event("cache miss", level="DEBUG", attributes={"key": "user:123", "cache": "redis"})

        event = span.events[0]
        assert event["attributes"]["key"] == "user:123"
        assert event["attributes"]["cache"] == "redis"

    def test_add_event_empty_attributes_default(self) -> None:
        """Events without attributes have empty dict."""
        span = Span(name="op", kind="INTERNAL")
        span.add_event("simple msg")

        assert span.events[0]["attributes"] == {}

    def test_multiple_events_ordered(self) -> None:
        """Multiple events are stored in order."""
        span = Span(name="op", kind="INTERNAL")
        span.add_event("first", level="DEBUG")
        span.add_event("second", level="INFO")
        span.add_event("third", level="ERROR")

        assert len(span.events) == 3
        assert span.events[0]["message"] == "first"
        assert span.events[1]["message"] == "second"
        assert span.events[2]["message"] == "third"


class TestSpanToDictEvents:
    """Test events in to_dict() serialization."""

    def test_to_dict_includes_events(self) -> None:
        """to_dict includes events and event_count."""
        span = Span(name="op", kind="INTERNAL")
        span.add_event("event A", level="INFO")
        span.add_event("event B", level="DEBUG")

        d = span.to_dict()
        assert "events" in d
        assert "event_count" in d
        assert len(d["events"]) == 2
        assert d["event_count"] == 2

    def test_to_dict_empty_events_default(self) -> None:
        """to_dict includes empty events and 0 count by default."""
        span = Span(name="op", kind="INTERNAL")

        d = span.to_dict()
        assert d["events"] == []
        assert d["event_count"] == 0

    def test_event_count_matches_events(self) -> None:
        """event_count always matches len(events)."""
        span = Span(name="op", kind="INTERNAL")
        for i in range(5):
            span.add_event(f"event {i}")

        d = span.to_dict()
        assert d["event_count"] == 5
        assert len(d["events"]) == 5


class TestTracelyLoggingAPI:
    """Test tracely.debug/info/warning/error functions."""

    def test_tracely_debug_adds_event(self) -> None:
        """tracely.debug() adds DEBUG event to active span."""
        from tracely.logging_api import debug

        span = Span(name="op", kind="SERVER")
        with _span_context(span):
            debug("debug message")

        assert len(span.events) == 1
        assert span.events[0]["level"] == "DEBUG"
        assert span.events[0]["message"] == "debug message"

    def test_tracely_info_adds_event(self) -> None:
        """tracely.info() adds INFO event to active span."""
        from tracely.logging_api import info

        span = Span(name="op", kind="SERVER")
        with _span_context(span):
            info("info message")

        assert len(span.events) == 1
        assert span.events[0]["level"] == "INFO"
        assert span.events[0]["message"] == "info message"

    def test_tracely_warning_adds_event(self) -> None:
        """tracely.warning() adds WARNING event to active span."""
        from tracely.logging_api import warning

        span = Span(name="op", kind="SERVER")
        with _span_context(span):
            warning("warning message")

        assert len(span.events) == 1
        assert span.events[0]["level"] == "WARNING"
        assert span.events[0]["message"] == "warning message"

    def test_tracely_error_adds_event(self) -> None:
        """tracely.error() adds ERROR event to active span."""
        from tracely.logging_api import error

        span = Span(name="op", kind="SERVER")
        with _span_context(span):
            error("error message")

        assert len(span.events) == 1
        assert span.events[0]["level"] == "ERROR"
        assert span.events[0]["message"] == "error message"

    def test_no_span_noop(self) -> None:
        """Calling logging functions without active span does nothing."""
        from tracely.logging_api import info

        # Should not raise
        info("no span active")

    def test_event_attributes_via_api(self) -> None:
        """Custom attributes can be passed via kwargs."""
        from tracely.logging_api import info

        span = Span(name="op", kind="SERVER")
        with _span_context(span):
            info("cache hit", cache="redis", key="user:42")

        event = span.events[0]
        assert event["attributes"]["cache"] == "redis"
        assert event["attributes"]["key"] == "user:42"

    def test_events_across_child_spans(self) -> None:
        """Events on parent vs child are separate."""
        from tracely.logging_api import info

        root = Span(name="GET /api", kind="SERVER")
        with _span_context(root):
            info("root event")
            child = Span(name="DB query", kind="CLIENT", parent=root)
            with _span_context(child):
                info("child event")

        assert len(root.events) == 1
        assert root.events[0]["message"] == "root event"
        assert len(child.events) == 1
        assert child.events[0]["message"] == "child event"


class TestTracelyImportLogging:
    """Verify logging functions are accessible from tracely package."""

    def test_import_from_tracely(self) -> None:
        import tracely

        assert hasattr(tracely, "debug")
        assert hasattr(tracely, "info")
        assert hasattr(tracely, "warning")
        assert hasattr(tracely, "error")
        assert callable(tracely.debug)
        assert callable(tracely.info)
        assert callable(tracely.warning)
        assert callable(tracely.error)
