"""Database query instrumentation for SQL and MongoDB.

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

logger = logging.getLogger("tracely")


def _extract_operation(statement: str) -> str:
    """Extract the SQL operation (SELECT, INSERT, UPDATE, DELETE) from a statement."""
    normalized = statement.strip().upper()
    for op in ("SELECT", "INSERT", "UPDATE", "DELETE"):
        if normalized.startswith(op):
            return op
    return "UNKNOWN"


class SQLAlchemyInstrumentor:
    """Tracks SQLAlchemy query execution times.

    Designed to be used with SQLAlchemy's event system:
    - event.listen(engine, "before_cursor_execute", inst.before_cursor_execute)
    - event.listen(engine, "after_cursor_execute", inst.after_cursor_execute)
    """

    def __init__(
        self,
        on_span: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self._on_span = on_span
        self._timings: dict[int, float] = {}

    def before_cursor_execute(
        self,
        conn: Any,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        """Record start time before query execution."""
        try:
            self._timings[id(context)] = time.perf_counter()
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
            start = self._timings.pop(id(context), None)
            if start is None:
                return

            elapsed_ms = (time.perf_counter() - start) * 1000
            span_data: dict[str, Any] = {
                "span_type": "db",
                "db.system": "sql",
                "db.statement": statement,
                "db.operation": _extract_operation(statement),
                "duration_ms": round(elapsed_ms, 3),
                "error": False,
            }

            if self._on_span is not None:
                self._on_span(span_data)
        except Exception:
            logger.debug("Error in after_cursor_execute", exc_info=True)


class DjangoORMInstrumentor:
    """Tracks Django ORM query execution.

    Designed to receive query data from Django's database instrumentation
    or a custom CursorWrapper. Call on_query() for each completed query.
    """

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
        """Record a completed Django ORM query as a span."""
        try:
            span_data: dict[str, Any] = {
                "span_type": "db",
                "db.system": vendor,
                "db.statement": sql,
                "db.operation": _extract_operation(sql),
                "duration_ms": round(duration_ms, 3),
                "error": False,
            }

            if self._on_span is not None:
                self._on_span(span_data)
        except Exception:
            logger.debug("Error in DjangoORMInstrumentor.on_query", exc_info=True)


class MongoInstrumentor:
    """Tracks MongoDB command execution times.

    Designed to be used as a pymongo CommandListener:
    - on_command_start / on_command_success / on_command_failure

    Maintains an in-flight map keyed by request_id to correlate
    start and end events.
    """

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
        """Record the start of a MongoDB command."""
        try:
            self._inflight[request_id] = {
                "command_name": command_name,
                "database_name": database_name,
                "start": time.perf_counter(),
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

            span_data: dict[str, Any] = {
                "span_type": "db",
                "db.system": "mongodb",
                "db.operation": info["command_name"],
                "db.name": info["database_name"],
                "duration_ms": round(duration_ms, 3),
                "error": False,
            }

            if self._on_span is not None:
                self._on_span(span_data)
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

            span_data: dict[str, Any] = {
                "span_type": "db",
                "db.system": "mongodb",
                "db.operation": info["command_name"],
                "db.name": info["database_name"],
                "duration_ms": round(duration_ms, 3),
                "error": True,
                "error.message": failure,
            }

            if self._on_span is not None:
                self._on_span(span_data)
        except Exception:
            logger.debug("Error in MongoInstrumentor.on_command_failure", exc_info=True)
