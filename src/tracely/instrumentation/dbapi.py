"""Database query instrumentation for SQL and MongoDB.

Creates child Span objects linked to the active root span via context
propagation, enabling hierarchical trace trees (FR56, FR57).

Provides instrumentors for:
- SQLAlchemy (via before/after_cursor_execute events)
- Django ORM (via query callback)
- MongoDB (via pymongo command monitoring)

All instrumentors are fail-silent and never crash the host application.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable

from tracely.context import get_current_span
from tracely.span import Span

logger = logging.getLogger("tracely")


def _extract_operation(statement: str) -> str:
    """Extract the SQL operation (SELECT, INSERT, UPDATE, DELETE) from a statement."""
    normalized = statement.strip().upper()
    for op in ("SELECT", "INSERT", "UPDATE", "DELETE"):
        if normalized.startswith(op):
            return op
    return "UNKNOWN"


class SQLAlchemyInstrumentor:
    """Tracks SQLAlchemy query execution as child spans.

    Creates a child Span linked to the active root/parent span when a
    query executes. If no active span exists, records a standalone dict.
    """

    def __init__(
        self,
        on_span: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self._on_span = on_span
        self._timings: dict[int, tuple[float, Span | None]] = {}

    def before_cursor_execute(
        self,
        conn: Any,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        """Record start time and create child span before query execution."""
        try:
            parent = get_current_span()
            span: Span | None = None
            if parent is not None:
                operation = _extract_operation(statement)
                span = Span(
                    name=f"SQL {operation}",
                    parent=parent,
                    kind="CLIENT",
                )
                span.set_attribute("db.system", "sql")
                span.set_attribute("db.statement", statement)
                span.set_attribute("db.operation", operation)
            self._timings[id(context)] = (time.perf_counter(), span)
        except Exception:
            logger.debug("Error in before_cursor_execute", exc_info=True)

    def after_cursor_execute(
        self,
        conn: Any,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        """Record query span after execution completes."""
        try:
            entry = self._timings.pop(id(context), None)
            if entry is None:
                return

            start, span = entry
            elapsed_ms = (time.perf_counter() - start) * 1000

            if span is not None:
                span.set_attribute("duration_ms", str(round(elapsed_ms, 3)))
                span.set_status("OK")
                span.end()

                if self._on_span is not None:
                    self._on_span(span.to_dict())
            elif self._on_span is not None:
                self._on_span({
                    "span_type": "db",
                    "db.system": "sql",
                    "db.statement": statement,
                    "db.operation": _extract_operation(statement),
                    "duration_ms": round(elapsed_ms, 3),
                    "error": False,
                })
        except Exception:
            logger.debug("Error in after_cursor_execute", exc_info=True)


class DjangoORMInstrumentor:
    """Tracks Django ORM query execution as child spans."""

    def __init__(
        self,
        on_span: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self._on_span = on_span

    def on_query(
        self,
        sql: str,
        duration_ms: float,
        vendor: str = "sql",
    ) -> None:
        """Record a completed Django ORM query as a child span."""
        try:
            parent = get_current_span()
            operation = _extract_operation(sql)

            if parent is not None:
                span = Span(
                    name=f"SQL {operation}",
                    parent=parent,
                    kind="CLIENT",
                )
                span.set_attribute("db.system", vendor)
                span.set_attribute("db.statement", sql)
                span.set_attribute("db.operation", operation)
                span.set_attribute("duration_ms", str(round(duration_ms, 3)))
                span.set_status("OK")
                span.end()

                if self._on_span is not None:
                    self._on_span(span.to_dict())
            elif self._on_span is not None:
                self._on_span({
                    "span_type": "db",
                    "db.system": vendor,
                    "db.statement": sql,
                    "db.operation": operation,
                    "duration_ms": round(duration_ms, 3),
                    "error": False,
                })
        except Exception:
            logger.debug("Error in DjangoORMInstrumentor.on_query", exc_info=True)


class MongoInstrumentor:
    """Tracks MongoDB command execution as child spans."""

    def __init__(
        self,
        on_span: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self._on_span = on_span
        self._inflight: dict[int, dict[str, Any]] = {}

    def on_command_start(
        self,
        command_name: str,
        database_name: str,
        request_id: int,
    ) -> None:
        """Record the start of a MongoDB command and create a child span."""
        try:
            parent = get_current_span()
            span: Span | None = None
            if parent is not None:
                span = Span(
                    name=f"MongoDB {command_name}",
                    parent=parent,
                    kind="CLIENT",
                )
                span.set_attribute("db.system", "mongodb")
                span.set_attribute("db.operation", command_name)
                span.set_attribute("db.name", database_name)

            self._inflight[request_id] = {
                "command_name": command_name,
                "database_name": database_name,
                "start": time.perf_counter(),
                "span": span,
            }
        except Exception:
            logger.debug("Error in MongoInstrumentor.on_command_start", exc_info=True)

    def on_command_success(
        self,
        request_id: int,
        duration_ms: float,
    ) -> None:
        """Record a successful MongoDB command completion."""
        try:
            info = self._inflight.pop(request_id, None)
            if info is None:
                return

            span: Span | None = info.get("span")
            if span is not None:
                span.set_attribute("duration_ms", str(round(duration_ms, 3)))
                span.set_status("OK")
                span.end()

                if self._on_span is not None:
                    self._on_span(span.to_dict())
            elif self._on_span is not None:
                self._on_span({
                    "span_type": "db",
                    "db.system": "mongodb",
                    "db.operation": info["command_name"],
                    "db.name": info["database_name"],
                    "duration_ms": round(duration_ms, 3),
                    "error": False,
                })
        except Exception:
            logger.debug("Error in MongoInstrumentor.on_command_success", exc_info=True)

    def on_command_failure(
        self,
        request_id: int,
        duration_ms: float,
        failure: str,
    ) -> None:
        """Record a failed MongoDB command."""
        try:
            info = self._inflight.pop(request_id, None)
            if info is None:
                return

            span: Span | None = info.get("span")
            if span is not None:
                span.set_attribute("duration_ms", str(round(duration_ms, 3)))
                span.set_attribute("error.message", failure)
                span.set_status("ERROR", failure)
                span.end()

                if self._on_span is not None:
                    self._on_span(span.to_dict())
            elif self._on_span is not None:
                self._on_span({
                    "span_type": "db",
                    "db.system": "mongodb",
                    "db.operation": info["command_name"],
                    "db.name": info["database_name"],
                    "duration_ms": round(duration_ms, 3),
                    "error": True,
                    "error.message": failure,
                })
        except Exception:
            logger.debug("Error in MongoInstrumentor.on_command_failure", exc_info=True)
