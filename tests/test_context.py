"""Tests for span context propagation using contextvars."""

from __future__ import annotations

import asyncio

import pytest

from tracely.context import get_current_span, set_current_span, _span_context
from tracely.span import Span


class TestContextPropagation:
    """Tests for get/set current span."""

    def test_no_current_span_by_default(self) -> None:
        assert get_current_span() is None

    def test_set_and_get_current_span(self) -> None:
        span = Span(name="root")
        token = set_current_span(span)
        assert get_current_span() is span
        set_current_span(None, token)

    def test_set_none_clears_current_span(self) -> None:
        span = Span(name="root")
        token = set_current_span(span)
        set_current_span(None, token)
        assert get_current_span() is None

    def test_nested_spans_restore_parent(self) -> None:
        parent = Span(name="parent")
        t1 = set_current_span(parent)

        child = Span(name="child", parent=parent)
        t2 = set_current_span(child)
        assert get_current_span() is child

        set_current_span(parent, t2)
        assert get_current_span() is parent
        set_current_span(None, t1)


class TestSpanContextManager:
    """Tests for _span_context() internal context manager."""

    def test_span_context_sets_active_span(self) -> None:
        span = Span(name="test")
        with _span_context(span):
            assert get_current_span() is span
        assert get_current_span() is None

    def test_span_context_restores_parent(self) -> None:
        parent = Span(name="parent")
        child = Span(name="child", parent=parent)

        with _span_context(parent):
            assert get_current_span() is parent
            with _span_context(child):
                assert get_current_span() is child
            assert get_current_span() is parent
        assert get_current_span() is None

    def test_span_context_restores_on_exception(self) -> None:
        span = Span(name="test")
        with pytest.raises(ValueError):
            with _span_context(span):
                raise ValueError("boom")
        assert get_current_span() is None


class TestAsyncContextIsolation:
    """Tests that context is properly isolated across async tasks."""

    @pytest.mark.asyncio
    async def test_async_tasks_have_separate_context(self) -> None:
        results: dict[str, str | None] = {}

        async def task_a() -> None:
            span_a = Span(name="task-a")
            with _span_context(span_a):
                await asyncio.sleep(0.01)
                current = get_current_span()
                results["a"] = current.name if current else None

        async def task_b() -> None:
            span_b = Span(name="task-b")
            with _span_context(span_b):
                await asyncio.sleep(0.01)
                current = get_current_span()
                results["b"] = current.name if current else None

        await asyncio.gather(task_a(), task_b())
        assert results["a"] == "task-a"
        assert results["b"] == "task-b"

    @pytest.mark.asyncio
    async def test_no_span_leaks_between_requests(self) -> None:
        span = Span(name="request-1")
        with _span_context(span):
            pass
        assert get_current_span() is None
