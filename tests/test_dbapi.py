"""Tests for database query instrumentation (Story 2.2, Task 6).

Tests SQLAlchemy, Django ORM, and MongoDB query tracking without
requiring actual database connections — all via mocking.
"""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from tracely.instrumentation.dbapi import (
    SQLAlchemyInstrumentor,
    DjangoORMInstrumentor,
    MongoInstrumentor,
)


# ---------------------------------------------------------------------------
# SQLAlchemy instrumentation
# ---------------------------------------------------------------------------
class TestSQLAlchemyInstrumentor:
    """Test SQLAlchemy event-based query timing."""

    def test_records_query_span(self) -> None:
        """on_query_end produces a span with statement, duration, db.system."""
        captured: list[dict[str, Any]] = []
        inst = SQLAlchemyInstrumentor(on_span=lambda s: captured.append(s))

        # Simulate before/after cursor execute
        ctx = MagicMock()
        inst.before_cursor_execute(
            conn=MagicMock(),
            cursor=MagicMock(),
            statement="SELECT * FROM users WHERE id = %s",
            parameters=(1,),
            context=ctx,
            executemany=False,
        )
        # Simulate some time passing
        time.sleep(0.001)
        inst.after_cursor_execute(
            conn=MagicMock(),
            cursor=MagicMock(),
            statement="SELECT * FROM users WHERE id = %s",
            parameters=(1,),
            context=ctx,
            executemany=False,
        )

        assert len(captured) == 1
        span = captured[0]
        assert span["span_type"] == "db"
        assert span["db.system"] == "sql"
        assert "SELECT" in span["db.statement"]
        assert span["duration_ms"] >= 0

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
        """Instrumentation never crashes — errors are silently caught."""
        inst = SQLAlchemyInstrumentor(on_span=None)
        # Should not raise even with None callback
        ctx = MagicMock()
        inst.before_cursor_execute(MagicMock(), MagicMock(), "SELECT 1", (), ctx, False)
        inst.after_cursor_execute(MagicMock(), MagicMock(), "SELECT 1", (), ctx, False)


# ---------------------------------------------------------------------------
# Django ORM instrumentation
# ---------------------------------------------------------------------------
class TestDjangoORMInstrumentor:
    """Test Django ORM query tracking."""

    def test_records_query_span(self) -> None:
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

    def test_records_command_span(self) -> None:
        captured: list[dict[str, Any]] = []
        inst = MongoInstrumentor(on_span=lambda s: captured.append(s))

        # Simulate command start
        inst.on_command_start(
            command_name="find",
            database_name="mydb",
            request_id=123,
        )
        time.sleep(0.001)
        # Simulate command success
        inst.on_command_success(
            request_id=123,
            duration_ms=5.2,
        )

        assert len(captured) == 1
        span = captured[0]
        assert span["span_type"] == "db"
        assert span["db.system"] == "mongodb"
        assert span["db.operation"] == "find"
        assert span["db.name"] == "mydb"
        assert span["duration_ms"] == 5.2

    def test_records_command_failure(self) -> None:
        captured: list[dict[str, Any]] = []
        inst = MongoInstrumentor(on_span=lambda s: captured.append(s))

        inst.on_command_start(
            command_name="insert",
            database_name="mydb",
            request_id=456,
        )
        inst.on_command_failure(
            request_id=456,
            duration_ms=3.0,
            failure="duplicate key error",
        )

        assert len(captured) == 1
        span = captured[0]
        assert span["error"] is True
        assert span["error.message"] == "duplicate key error"
        assert span["db.operation"] == "insert"

    def test_ignores_untracked_request_id(self) -> None:
        captured: list[dict[str, Any]] = []
        inst = MongoInstrumentor(on_span=lambda s: captured.append(s))
        # Success for a request_id that was never started
        inst.on_command_success(request_id=999, duration_ms=1.0)
        assert len(captured) == 0

    def test_never_raises(self) -> None:
        inst = MongoInstrumentor(on_span=None)
        inst.on_command_start("find", "db", 1)
        inst.on_command_success(1, 1.0)
        inst.on_command_failure(2, 1.0, "err")
