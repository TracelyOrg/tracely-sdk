"""Tests for database query instrumentation (Story 2.2 + 2.3).

Tests SQLAlchemy, Django ORM, and MongoDB query tracking including
child span hierarchy when a parent span is active (AC2).
"""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import MagicMock

import pytest

from tracely.context import _span_context
from tracely.instrumentation.dbapi import (
    SQLAlchemyInstrumentor,
    DjangoORMInstrumentor,
    MongoInstrumentor,
)
from tracely.span import Span


# ---------------------------------------------------------------------------
# SQLAlchemy instrumentation
# ---------------------------------------------------------------------------
class TestSQLAlchemyInstrumentor:
    """Test SQLAlchemy event-based query timing."""

    def test_records_query_span_no_parent(self) -> None:
        """Without active parent, produces flat dict span."""
        captured: list[dict[str, Any]] = []
        inst = SQLAlchemyInstrumentor(on_span=lambda s: captured.append(s))

        ctx = MagicMock()
        inst.before_cursor_execute(
            MagicMock(), MagicMock(),
            "SELECT * FROM users WHERE id = %s",
            (1,), ctx, False,
        )
        time.sleep(0.001)
        inst.after_cursor_execute(
            MagicMock(), MagicMock(),
            "SELECT * FROM users WHERE id = %s",
            (1,), ctx, False,
        )

        assert len(captured) == 1
        span = captured[0]
        assert span["span_type"] == "db"
        assert span["db.system"] == "sql"
        assert "SELECT" in span["db.statement"]
        assert span["duration_ms"] >= 0

    def test_creates_child_span_with_parent(self) -> None:
        """With active parent, creates child Span with parent_span_id (AC2)."""
        captured: list[dict[str, Any]] = []
        inst = SQLAlchemyInstrumentor(on_span=lambda s: captured.append(s))

        root = Span(name="GET /api/users", kind="SERVER")
        with _span_context(root):
            ctx = MagicMock()
            inst.before_cursor_execute(
                MagicMock(), MagicMock(),
                "SELECT * FROM users",
                (), ctx, False,
            )
            inst.after_cursor_execute(
                MagicMock(), MagicMock(),
                "SELECT * FROM users",
                (), ctx, False,
            )

        assert len(captured) == 1
        span = captured[0]
        assert span["parent_span_id"] == root.span_id
        assert span["trace_id"] == root.trace_id
        assert span["kind"] == "CLIENT"
        assert span["attributes"]["db.system"] == "sql"
        assert span["attributes"]["db.operation"] == "SELECT"

    def test_records_insert_statement(self) -> None:
        captured: list[dict[str, Any]] = []
        inst = SQLAlchemyInstrumentor(on_span=lambda s: captured.append(s))
        ctx = MagicMock()
        inst.before_cursor_execute(
            MagicMock(), MagicMock(),
            "INSERT INTO orders (user_id, total) VALUES (%s, %s)",
            (1, 99.99), ctx, False,
        )
        inst.after_cursor_execute(
            MagicMock(), MagicMock(),
            "INSERT INTO orders (user_id, total) VALUES (%s, %s)",
            (1, 99.99), ctx, False,
        )
        assert captured[0]["db.operation"] == "INSERT"

    def test_extracts_operation_from_statement(self) -> None:
        captured: list[dict[str, Any]] = []
        inst = SQLAlchemyInstrumentor(on_span=lambda s: captured.append(s))
        ctx = MagicMock()

        for stmt, expected_op in [
            ("SELECT * FROM t", "SELECT"),
            ("INSERT INTO t VALUES (1)", "INSERT"),
            ("UPDATE t SET x=1", "UPDATE"),
            ("DELETE FROM t WHERE id=1", "DELETE"),
        ]:
            captured.clear()
            inst.before_cursor_execute(MagicMock(), MagicMock(), stmt, (), ctx, False)
            inst.after_cursor_execute(MagicMock(), MagicMock(), stmt, (), ctx, False)
            assert captured[0]["db.operation"] == expected_op

    def test_never_raises(self) -> None:
        inst = SQLAlchemyInstrumentor(on_span=None)
        ctx = MagicMock()
        inst.before_cursor_execute(MagicMock(), MagicMock(), "SELECT 1", (), ctx, False)
        inst.after_cursor_execute(MagicMock(), MagicMock(), "SELECT 1", (), ctx, False)


# ---------------------------------------------------------------------------
# Django ORM instrumentation
# ---------------------------------------------------------------------------
class TestDjangoORMInstrumentor:
    """Test Django ORM query tracking."""

    def test_records_query_span_no_parent(self) -> None:
        captured: list[dict[str, Any]] = []
        inst = DjangoORMInstrumentor(on_span=lambda s: captured.append(s))

        inst.on_query(
            sql="SELECT * FROM auth_user WHERE id = %s",
            duration_ms=12.5,
            vendor="postgresql",
        )

        assert len(captured) == 1
        span = captured[0]
        assert span["span_type"] == "db"
        assert span["db.system"] == "postgresql"
        assert "SELECT" in span["db.statement"]
        assert span["duration_ms"] == 12.5
        assert span["db.operation"] == "SELECT"

    def test_creates_child_span_with_parent(self) -> None:
        """With active parent, creates child Span linked to parent (AC2)."""
        captured: list[dict[str, Any]] = []
        inst = DjangoORMInstrumentor(on_span=lambda s: captured.append(s))

        root = Span(name="GET /api/users", kind="SERVER")
        with _span_context(root):
            inst.on_query(
                sql="SELECT * FROM auth_user",
                duration_ms=5.0,
                vendor="postgresql",
            )

        assert len(captured) == 1
        span = captured[0]
        assert span["parent_span_id"] == root.span_id
        assert span["trace_id"] == root.trace_id
        assert span["attributes"]["db.system"] == "postgresql"
        assert span["attributes"]["db.operation"] == "SELECT"

    def test_records_sqlite_vendor(self) -> None:
        captured: list[dict[str, Any]] = []
        inst = DjangoORMInstrumentor(on_span=lambda s: captured.append(s))
        inst.on_query(sql="SELECT 1", duration_ms=0.1, vendor="sqlite")
        assert captured[0]["db.system"] == "sqlite"

    def test_never_raises(self) -> None:
        inst = DjangoORMInstrumentor(on_span=None)
        inst.on_query(sql="SELECT 1", duration_ms=0.1, vendor="postgresql")


# ---------------------------------------------------------------------------
# MongoDB instrumentation
# ---------------------------------------------------------------------------
class TestMongoInstrumentor:
    """Test MongoDB command monitoring."""

    def test_records_command_span_no_parent(self) -> None:
        captured: list[dict[str, Any]] = []
        inst = MongoInstrumentor(on_span=lambda s: captured.append(s))

        inst.on_command_start("find", "mydb", 123)
        inst.on_command_success(123, 5.2)

        assert len(captured) == 1
        span = captured[0]
        assert span["span_type"] == "db"
        assert span["db.system"] == "mongodb"
        assert span["db.operation"] == "find"
        assert span["db.name"] == "mydb"
        assert span["duration_ms"] == 5.2

    def test_creates_child_span_with_parent(self) -> None:
        """With active parent, creates child Span linked to parent (AC2)."""
        captured: list[dict[str, Any]] = []
        inst = MongoInstrumentor(on_span=lambda s: captured.append(s))

        root = Span(name="GET /api/items", kind="SERVER")
        with _span_context(root):
            inst.on_command_start("find", "mydb", 123)
            inst.on_command_success(123, 5.2)

        assert len(captured) == 1
        span = captured[0]
        assert span["parent_span_id"] == root.span_id
        assert span["trace_id"] == root.trace_id
        assert span["attributes"]["db.system"] == "mongodb"
        assert span["attributes"]["db.operation"] == "find"
        assert span["attributes"]["db.name"] == "mydb"

    def test_records_command_failure_no_parent(self) -> None:
        captured: list[dict[str, Any]] = []
        inst = MongoInstrumentor(on_span=lambda s: captured.append(s))

        inst.on_command_start("insert", "mydb", 456)
        inst.on_command_failure(456, 3.0, "duplicate key error")

        assert len(captured) == 1
        span = captured[0]
        assert span["error"] is True
        assert span["error.message"] == "duplicate key error"
        assert span["db.operation"] == "insert"

    def test_records_command_failure_with_parent(self) -> None:
        captured: list[dict[str, Any]] = []
        inst = MongoInstrumentor(on_span=lambda s: captured.append(s))

        root = Span(name="POST /api/items", kind="SERVER")
        with _span_context(root):
            inst.on_command_start("insert", "mydb", 456)
            inst.on_command_failure(456, 3.0, "duplicate key error")

        assert len(captured) == 1
        span = captured[0]
        assert span["parent_span_id"] == root.span_id
        assert span["status_code"] == "ERROR"
        assert span["attributes"]["error.message"] == "duplicate key error"

    def test_ignores_untracked_request_id(self) -> None:
        captured: list[dict[str, Any]] = []
        inst = MongoInstrumentor(on_span=lambda s: captured.append(s))
        inst.on_command_success(request_id=999, duration_ms=1.0)
        assert len(captured) == 0

    def test_never_raises(self) -> None:
        inst = MongoInstrumentor(on_span=None)
        inst.on_command_start("find", "db", 1)
        inst.on_command_success(1, 1.0)
        inst.on_command_failure(2, 1.0, "err")


# ---------------------------------------------------------------------------
# Trace tree validation (FR57)
# ---------------------------------------------------------------------------
class TestTraceTreeHierarchy:
    """Verify that DB child spans form a valid trace tree with root spans."""

    def test_full_trace_tree_with_db_query(self) -> None:
        """Root HTTP span + DB child span share trace_id and have correct parent chain."""
        captured: list[dict[str, Any]] = []
        inst = SQLAlchemyInstrumentor(on_span=lambda s: captured.append(s))

        root = Span(name="GET /api/users", kind="SERVER", service_name="api")
        with _span_context(root):
            ctx = MagicMock()
            inst.before_cursor_execute(
                MagicMock(), MagicMock(),
                "SELECT * FROM users", (), ctx, False,
            )
            inst.after_cursor_execute(
                MagicMock(), MagicMock(),
                "SELECT * FROM users", (), ctx, False,
            )

        root.end()
        root_dict = root.to_dict()
        db_dict = captured[0]

        # Same trace
        assert db_dict["trace_id"] == root_dict["trace_id"]
        # DB span is child of root
        assert db_dict["parent_span_id"] == root_dict["span_id"]
        # Root has no parent
        assert root_dict["parent_span_id"] is None
        # Different span IDs
        assert db_dict["span_id"] != root_dict["span_id"]
