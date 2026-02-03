"""Tests for log event handler (AC5).

Verifies that log events are associated with the currently active
span's span_id, capturing level, message, and timestamp.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest

from tracely.context import _span_context
from tracely.log_handler import TracelyLogHandler
from tracely.span import Span


@pytest.fixture
def captured_events() -> list[dict[str, Any]]:
    return []


@pytest.fixture
def handler(captured_events: list[dict[str, Any]]) -> TracelyLogHandler:
    return TracelyLogHandler(on_event=lambda e: captured_events.append(e))


@pytest.fixture
def test_logger(handler: TracelyLogHandler) -> logging.Logger:
    logger = logging.getLogger("test.tracely.log_handler")
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    yield logger
    logger.removeHandler(handler)


class TestTracelyLogHandler:
    """Test log event capture and span association (AC5)."""

    def test_captures_log_with_active_span(
        self,
        test_logger: logging.Logger,
        captured_events: list[dict[str, Any]],
    ) -> None:
        """Log event is associated with active span's span_id."""
        root = Span(name="GET /api/users", kind="SERVER")

        with _span_context(root):
            test_logger.info("User fetched successfully")

        assert len(captured_events) == 1
        event = captured_events[0]
        assert event["span_id"] == root.span_id
        assert event["trace_id"] == root.trace_id
        assert event["level"] == "INFO"
        assert event["message"] == "User fetched successfully"
        assert "timestamp" in event

    def test_captures_log_level(
        self,
        test_logger: logging.Logger,
        captured_events: list[dict[str, Any]],
    ) -> None:
        """Log level is captured correctly for different levels."""
        root = Span(name="GET /api", kind="SERVER")

        with _span_context(root):
            test_logger.debug("debug msg")
            test_logger.warning("warn msg")
            test_logger.error("error msg")

        assert len(captured_events) == 3
        assert captured_events[0]["level"] == "DEBUG"
        assert captured_events[1]["level"] == "WARNING"
        assert captured_events[2]["level"] == "ERROR"

    def test_no_event_without_active_span(
        self,
        test_logger: logging.Logger,
        captured_events: list[dict[str, Any]],
    ) -> None:
        """Without active span, log events are not captured."""
        test_logger.info("No span active")
        assert len(captured_events) == 0

    def test_captures_timestamp(
        self,
        test_logger: logging.Logger,
        captured_events: list[dict[str, Any]],
    ) -> None:
        """Log event timestamp is a float (epoch seconds)."""
        root = Span(name="GET /api", kind="SERVER")

        with _span_context(root):
            test_logger.info("timed event")

        assert isinstance(captured_events[0]["timestamp"], float)
        assert captured_events[0]["timestamp"] > 0

    def test_captures_logger_name(
        self,
        test_logger: logging.Logger,
        captured_events: list[dict[str, Any]],
    ) -> None:
        """Log event includes the logger name."""
        root = Span(name="GET /api", kind="SERVER")

        with _span_context(root):
            test_logger.info("named logger")

        assert captured_events[0]["logger_name"] == "test.tracely.log_handler"

    def test_captures_exception_info(
        self,
        test_logger: logging.Logger,
        captured_events: list[dict[str, Any]],
    ) -> None:
        """Log event captures exception info when present."""
        root = Span(name="GET /api", kind="SERVER")

        with _span_context(root):
            try:
                raise ValueError("something broke")
            except ValueError:
                test_logger.exception("Error occurred")

        assert len(captured_events) == 1
        event = captured_events[0]
        assert event["level"] == "ERROR"
        assert "ValueError" in event.get("exception_type", "")
        assert "something broke" in event.get("exception_message", "")

    def test_never_raises(self) -> None:
        """Handler with broken callback does not crash the application."""
        def bad_callback(e: dict) -> None:
            raise RuntimeError("callback exploded")

        handler = TracelyLogHandler(on_event=bad_callback)
        logger = logging.getLogger("test.tracely.never_raises")
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)

        root = Span(name="GET /api", kind="SERVER")
        with _span_context(root):
            logger.info("should not crash")  # Must not raise

        logger.removeHandler(handler)

    def test_no_callback(self) -> None:
        """Handler with on_event=None does not crash."""
        handler = TracelyLogHandler(on_event=None)
        logger = logging.getLogger("test.tracely.no_callback")
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)

        root = Span(name="GET /api", kind="SERVER")
        with _span_context(root):
            logger.info("no callback")

        logger.removeHandler(handler)
