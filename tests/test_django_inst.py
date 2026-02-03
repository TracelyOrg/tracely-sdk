"""Tests for Django auto-instrumentation (Story 2.2, Task 4)."""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import MagicMock

import pytest

from tracely.detection import FrameworkInfo
from tracely.instrumentation.django_inst import (
    DjangoInstrumentor,
    TracelyDjangoMiddleware,
)


@pytest.fixture
def framework_info() -> FrameworkInfo:
    return FrameworkInfo(name="django")


class TestTracelyDjangoMiddleware:
    """Test the Django-style middleware that creates spans per request."""

    @pytest.fixture
    def captured_spans(self) -> list[dict]:
        return []

    def _make_request(
        self,
        method: str = "GET",
        path: str = "/api/users/",
        query: str = "",
    ) -> MagicMock:
        request = MagicMock()
        request.method = method
        request.path = path
        request.META = {"QUERY_STRING": query}
        return request

    def _make_response(self, status_code: int = 200) -> MagicMock:
        response = MagicMock()
        response.status_code = status_code
        return response

    def test_creates_span_for_request(self, captured_spans: list[dict]) -> None:
        """Middleware creates a span with method, path, status, duration."""
        response = self._make_response(200)

        def get_response(request: Any) -> Any:
            return response

        mw = TracelyDjangoMiddleware(
            get_response=get_response,
            on_span=lambda span: captured_spans.append(span),
        )
        request = self._make_request("GET", "/api/users/")
        result = mw(request)

        assert result is response
        assert len(captured_spans) == 1
        span = captured_spans[0]
        assert span["http.method"] == "GET"
        assert span["http.route"] == "/api/users/"
        assert span["http.status_code"] == 200
        assert span["duration_ms"] >= 0
        assert span["span_type"] == "http"

    def test_captures_post_request(self, captured_spans: list[dict]) -> None:
        response = self._make_response(201)

        def get_response(req: Any) -> Any:
            return response

        mw = TracelyDjangoMiddleware(
            get_response=get_response,
            on_span=lambda s: captured_spans.append(s),
        )
        request = self._make_request("POST", "/api/items/")
        mw(request)

        assert captured_spans[0]["http.method"] == "POST"
        assert captured_spans[0]["http.status_code"] == 201

    def test_captures_query_string(self, captured_spans: list[dict]) -> None:
        def get_response(req: Any) -> Any:
            return self._make_response(200)

        mw = TracelyDjangoMiddleware(
            get_response=get_response,
            on_span=lambda s: captured_spans.append(s),
        )
        request = self._make_request("GET", "/search/", query="q=hello")
        mw(request)

        assert captured_spans[0]["http.query"] == "q=hello"

    def test_captures_exception(self, captured_spans: list[dict]) -> None:
        """If get_response raises, middleware still records span with error."""

        def get_response(req: Any) -> Any:
            raise RuntimeError("db crashed")

        mw = TracelyDjangoMiddleware(
            get_response=get_response,
            on_span=lambda s: captured_spans.append(s),
        )
        request = self._make_request("GET", "/crash/")

        with pytest.raises(RuntimeError, match="db crashed"):
            mw(request)

        assert len(captured_spans) == 1
        assert captured_spans[0]["error"] is True
        assert "RuntimeError" in captured_spans[0]["error.type"]

    def test_captures_500_status(self, captured_spans: list[dict]) -> None:
        def get_response(req: Any) -> Any:
            return self._make_response(500)

        mw = TracelyDjangoMiddleware(
            get_response=get_response,
            on_span=lambda s: captured_spans.append(s),
        )
        mw(self._make_request())

        assert captured_spans[0]["http.status_code"] == 500


class TestDjangoInstrumentor:
    """Test instrumentor activation/deactivation."""

    def test_activate_and_deactivate(self, framework_info: FrameworkInfo) -> None:
        inst = DjangoInstrumentor(framework_info)
        inst.activate()
        inst.deactivate()

    def test_never_raises(self, framework_info: FrameworkInfo) -> None:
        inst = DjangoInstrumentor(framework_info)
        inst.activate()
        inst.deactivate()
