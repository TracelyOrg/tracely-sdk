"""Tests for Django auto-instrumentation (Story 2.2 + 2.3 span hierarchy)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from tracely.context import get_current_span
from tracely.detection import FrameworkInfo
from tracely.instrumentation.django_inst import (
    DjangoInstrumentor,
    TracelyDjangoMiddleware,
)
from tracely.span import Span


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
            service_name="django-api",
        )
        request = self._make_request("GET", "/api/users/")
        result = mw(request)

        assert result is response
        assert len(captured_spans) == 1
        span = captured_spans[0]
        assert span["attributes"]["http.method"] == "GET"
        assert span["attributes"]["http.route"] == "/api/users/"
        assert span["attributes"]["http.status_code"] == "200"
        assert span["duration_ms"] >= 0
        assert span["span_type"] == "span"

    def test_span_has_trace_id_and_span_id(self, captured_spans: list[dict]) -> None:
        """Root span has unique trace_id and span_id (FR55)."""

        def get_response(req: Any) -> Any:
            return self._make_response(200)

        mw = TracelyDjangoMiddleware(get_response=get_response, on_span=lambda s: captured_spans.append(s))
        mw(self._make_request())
        span = captured_spans[0]
        assert len(span["trace_id"]) == 32
        assert len(span["span_id"]) == 16
        assert span["parent_span_id"] is None

    def test_captures_post_request(self, captured_spans: list[dict]) -> None:
        response = self._make_response(201)

        def get_response(req: Any) -> Any:
            return response

        mw = TracelyDjangoMiddleware(get_response=get_response, on_span=lambda s: captured_spans.append(s))
        mw(self._make_request("POST", "/api/items/"))
        assert captured_spans[0]["attributes"]["http.method"] == "POST"
        assert captured_spans[0]["attributes"]["http.status_code"] == "201"

    def test_captures_query_string(self, captured_spans: list[dict]) -> None:
        def get_response(req: Any) -> Any:
            return self._make_response(200)

        mw = TracelyDjangoMiddleware(get_response=get_response, on_span=lambda s: captured_spans.append(s))
        mw(self._make_request("GET", "/search/", query="q=hello"))
        assert captured_spans[0]["attributes"]["http.query"] == "q=hello"

    def test_captures_exception(self, captured_spans: list[dict]) -> None:
        """If get_response raises, middleware still records span with error."""

        def get_response(req: Any) -> Any:
            raise RuntimeError("db crashed")

        mw = TracelyDjangoMiddleware(get_response=get_response, on_span=lambda s: captured_spans.append(s))
        with pytest.raises(RuntimeError, match="db crashed"):
            mw(self._make_request("GET", "/crash/"))

        assert len(captured_spans) == 1
        assert captured_spans[0]["attributes"]["error"] == "true"
        assert captured_spans[0]["attributes"]["error.type"] == "RuntimeError"
        assert captured_spans[0]["status_code"] == "ERROR"

    def test_captures_500_status(self, captured_spans: list[dict]) -> None:
        def get_response(req: Any) -> Any:
            return self._make_response(500)

        mw = TracelyDjangoMiddleware(get_response=get_response, on_span=lambda s: captured_spans.append(s))
        mw(self._make_request())
        assert captured_spans[0]["attributes"]["http.status_code"] == "500"

    def test_context_propagation_during_request(self) -> None:
        """Root span is active during request processing."""
        active_spans: list[Span | None] = []

        def get_response(req: Any) -> Any:
            active_spans.append(get_current_span())
            resp = MagicMock()
            resp.status_code = 200
            return resp

        mw = TracelyDjangoMiddleware(get_response=get_response)
        mw(self._make_request("GET", "/test/"))
        assert len(active_spans) == 1
        assert isinstance(active_spans[0], Span)
        assert active_spans[0].name == "GET /test/"


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
