"""Tests for request/response data capture utilities.

Covers: body processing (truncation, binary detection), URL building,
header sanitization, and span attribute attachment for request/response data.
"""

from __future__ import annotations

import json

import pytest

from tracely.capture import (
    MAX_BODY_SIZE,
    build_url,
    capture_request_data,
    capture_response_data,
    is_binary_content_type,
    process_body,
    sanitize_headers,
)
from tracely.span import Span


# ---------------------------------------------------------------------------
# is_binary_content_type
# ---------------------------------------------------------------------------


class TestIsBinaryContentType:
    """Test binary content type detection."""

    @pytest.mark.parametrize(
        "content_type",
        [
            "image/png",
            "image/jpeg",
            "image/gif",
            "image/webp",
            "video/mp4",
            "video/webm",
            "audio/mpeg",
            "audio/ogg",
            "application/octet-stream",
            "application/zip",
            "application/gzip",
            "application/pdf",
        ],
    )
    def test_detects_binary_types(self, content_type: str) -> None:
        assert is_binary_content_type(content_type) is True

    @pytest.mark.parametrize(
        "content_type",
        [
            "text/plain",
            "text/html",
            "application/json",
            "application/xml",
            "application/x-www-form-urlencoded",
            "multipart/form-data",
            "text/css",
            "text/javascript",
        ],
    )
    def test_non_binary_types(self, content_type: str) -> None:
        assert is_binary_content_type(content_type) is False

    def test_empty_content_type(self) -> None:
        assert is_binary_content_type("") is False

    def test_content_type_with_charset(self) -> None:
        assert is_binary_content_type("image/png; charset=utf-8") is True
        assert is_binary_content_type("application/json; charset=utf-8") is False

    def test_case_insensitive(self) -> None:
        assert is_binary_content_type("Image/PNG") is True
        assert is_binary_content_type("APPLICATION/JSON") is False


# ---------------------------------------------------------------------------
# process_body
# ---------------------------------------------------------------------------


class TestProcessBody:
    """Test body processing: truncation and binary replacement."""

    def test_small_text_body_unchanged(self) -> None:
        body = b'{"key": "value"}'
        result, meta = process_body(body, "application/json")
        assert result == '{"key": "value"}'
        assert meta.get("body.truncated") is None

    def test_string_body_accepted(self) -> None:
        result, meta = process_body("hello world", "text/plain")
        assert result == "hello world"

    def test_truncation_at_64kb(self) -> None:
        body = b"x" * (MAX_BODY_SIZE + 1000)
        result, meta = process_body(body, "text/plain")
        assert len(result) == MAX_BODY_SIZE + len("[truncated]")
        assert result.endswith("[truncated]")
        assert meta["body.original_length"] == str(len(body))
        assert meta["body.truncated"] == "true"

    def test_exactly_64kb_not_truncated(self) -> None:
        body = b"x" * MAX_BODY_SIZE
        result, meta = process_body(body, "text/plain")
        assert len(result) == MAX_BODY_SIZE
        assert "[truncated]" not in result
        assert meta.get("body.truncated") is None

    def test_binary_body_replaced(self) -> None:
        body = b"\x89PNG\r\n\x1a\n" + b"\x00" * 1000
        result, meta = process_body(body, "image/png")
        assert result == f"[binary: image/png, {len(body)} bytes]"
        assert meta["body.original_length"] == str(len(body))

    def test_binary_body_with_charset(self) -> None:
        body = b"\x00" * 500
        result, meta = process_body(body, "image/jpeg; charset=binary")
        assert result.startswith("[binary: image/jpeg; charset=binary,")
        assert "500 bytes" in result

    def test_empty_body(self) -> None:
        result, meta = process_body(b"", "application/json")
        assert result == ""
        assert meta == {}

    def test_none_body(self) -> None:
        result, meta = process_body(None, "text/plain")
        assert result == ""
        assert meta == {}

    def test_large_binary_body_uses_placeholder_not_truncation(self) -> None:
        body = b"\x00" * (MAX_BODY_SIZE * 2)
        result, meta = process_body(body, "application/octet-stream")
        assert result.startswith("[binary:")
        assert "[truncated]" not in result


# ---------------------------------------------------------------------------
# build_url
# ---------------------------------------------------------------------------


class TestBuildUrl:
    """Test URL construction from components."""

    def test_basic_url(self) -> None:
        url = build_url("https", "example.com", "/api/users", "")
        assert url == "https://example.com/api/users"

    def test_url_with_query(self) -> None:
        url = build_url("https", "example.com", "/api/users", "page=1&limit=10")
        assert url == "https://example.com/api/users?page=1&limit=10"

    def test_url_with_port(self) -> None:
        url = build_url("http", "localhost:8000", "/api", "")
        assert url == "http://localhost:8000/api"

    def test_empty_path_defaults_to_slash(self) -> None:
        url = build_url("https", "example.com", "", "")
        assert url == "https://example.com/"

    def test_missing_leading_slash(self) -> None:
        url = build_url("https", "example.com", "api/users", "")
        assert url == "https://example.com/api/users"


# ---------------------------------------------------------------------------
# sanitize_headers
# ---------------------------------------------------------------------------


class TestSanitizeHeaders:
    """Test header sanitization to JSON string."""

    def test_dict_headers(self) -> None:
        headers = {"content-type": "application/json", "accept": "text/html"}
        result = sanitize_headers(headers)
        parsed = json.loads(result)
        assert parsed["content-type"] == "application/json"
        assert parsed["accept"] == "text/html"

    def test_list_of_tuples_headers(self) -> None:
        headers = [(b"content-type", b"application/json"), (b"accept", b"text/html")]
        result = sanitize_headers(headers)
        parsed = json.loads(result)
        assert parsed["content-type"] == "application/json"
        assert parsed["accept"] == "text/html"

    def test_empty_headers(self) -> None:
        result = sanitize_headers({})
        assert result == "{}"

    def test_none_headers(self) -> None:
        result = sanitize_headers(None)
        assert result == "{}"


# ---------------------------------------------------------------------------
# capture_request_data
# ---------------------------------------------------------------------------


class TestCaptureRequestData:
    """Test that request data is correctly attached to span attributes."""

    def test_captures_all_request_fields(self) -> None:
        span = Span(name="test")
        capture_request_data(
            span=span,
            method="POST",
            url="https://example.com/api/users?role=admin",
            headers={"content-type": "application/json", "authorization": "Bearer x"},
            body=b'{"name": "test"}',
            content_type="application/json",
            query_params="role=admin",
        )
        assert span.attributes["http.method"] == "POST"
        assert span.attributes["http.url"] == "https://example.com/api/users?role=admin"
        assert "content-type" in span.attributes["http.request.headers"]
        assert span.attributes["http.request.body"] == '{"name": "test"}'
        assert span.attributes["http.request.query"] == "role=admin"

    def test_truncates_large_request_body(self) -> None:
        span = Span(name="test")
        large_body = b"x" * (MAX_BODY_SIZE + 500)
        capture_request_data(
            span=span,
            method="POST",
            url="https://example.com/upload",
            headers={},
            body=large_body,
            content_type="text/plain",
        )
        assert span.attributes["http.request.body"].endswith("[truncated]")
        assert span.attributes["http.request.body.original_length"] == str(len(large_body))

    def test_replaces_binary_request_body(self) -> None:
        span = Span(name="test")
        capture_request_data(
            span=span,
            method="POST",
            url="https://example.com/upload",
            headers={},
            body=b"\x89PNG" + b"\x00" * 100,
            content_type="image/png",
        )
        assert span.attributes["http.request.body"].startswith("[binary:")


# ---------------------------------------------------------------------------
# capture_response_data
# ---------------------------------------------------------------------------


class TestCaptureResponseData:
    """Test that response data is correctly attached to span attributes."""

    def test_captures_all_response_fields(self) -> None:
        span = Span(name="test")
        capture_response_data(
            span=span,
            status_code=200,
            headers={"content-type": "application/json"},
            body=b'{"id": 1}',
            content_type="application/json",
        )
        assert span.attributes["http.status_code"] == "200"
        assert "content-type" in span.attributes["http.response.headers"]
        assert span.attributes["http.response.body"] == '{"id": 1}'

    def test_truncates_large_response_body(self) -> None:
        span = Span(name="test")
        large_body = b"a" * (MAX_BODY_SIZE + 2000)
        capture_response_data(
            span=span,
            status_code=200,
            headers={},
            body=large_body,
            content_type="text/plain",
        )
        assert span.attributes["http.response.body"].endswith("[truncated]")
        assert span.attributes["http.response.body.original_length"] == str(len(large_body))

    def test_replaces_binary_response_body(self) -> None:
        span = Span(name="test")
        capture_response_data(
            span=span,
            status_code=200,
            headers={},
            body=b"\x00" * 5000,
            content_type="application/octet-stream",
        )
        assert span.attributes["http.response.body"].startswith("[binary:")

    def test_fail_silent_on_error(self) -> None:
        """capture_response_data must never raise — fail-silent design."""
        span = Span(name="test")
        # Passing invalid types should not crash
        capture_response_data(
            span=span,
            status_code="not_a_number",  # type: ignore[arg-type]
            headers=None,
            body=None,
            content_type=None,
        )
        # Should not raise — just best-effort capture
