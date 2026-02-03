"""Tests for smart data redaction (Story 2.5).

Covers: field-name redaction in JSON bodies, header redaction,
pattern-based redaction (credit card, email, SSN), and custom field config.
"""

from __future__ import annotations

import json

import pytest

from tracely.redaction import (
    SENSITIVE_FIELDS,
    SENSITIVE_HEADERS,
    redact_body,
    redact_headers,
    redact_patterns,
)


# ---------------------------------------------------------------------------
# redact_body — field-name based redaction (AC1)
# ---------------------------------------------------------------------------


class TestRedactBody:
    """Test field-name based redaction in JSON bodies."""

    def test_redacts_password_field(self) -> None:
        body = '{"username": "alice", "password": "s3cret!"}'
        result = redact_body(body)
        parsed = json.loads(result)
        assert parsed["password"] == "[REDACTED]"
        assert parsed["username"] == "alice"

    def test_redacts_all_default_sensitive_fields(self) -> None:
        body = json.dumps({
            "password": "pass123",
            "secret": "mysecret",
            "token": "tok_abc",
            "authorization": "Bearer xyz",
            "api_key": "key_123",
            "credit_card": "4111111111111111",
            "ssn": "123-45-6789",
            "safe_field": "keep_me",
        })
        result = redact_body(body)
        parsed = json.loads(result)
        for field in ["password", "secret", "token", "authorization", "api_key", "credit_card", "ssn"]:
            assert parsed[field] == "[REDACTED]", f"Field '{field}' was not redacted"
        assert parsed["safe_field"] == "keep_me"

    def test_preserves_field_names(self) -> None:
        """AC1: field names are preserved for debugging context."""
        body = '{"password": "secret123", "token": "abc"}'
        result = redact_body(body)
        parsed = json.loads(result)
        assert "password" in parsed
        assert "token" in parsed

    def test_case_insensitive_field_matching(self) -> None:
        body = '{"Password": "abc", "API_KEY": "xyz", "Token": "tok"}'
        result = redact_body(body)
        parsed = json.loads(result)
        assert parsed["Password"] == "[REDACTED]"
        assert parsed["API_KEY"] == "[REDACTED]"
        assert parsed["Token"] == "[REDACTED]"

    def test_nested_object_redaction(self) -> None:
        body = json.dumps({
            "user": {
                "name": "Alice",
                "password": "secret",
                "profile": {
                    "token": "nested_tok",
                    "bio": "hello",
                },
            },
        })
        result = redact_body(body)
        parsed = json.loads(result)
        assert parsed["user"]["password"] == "[REDACTED]"
        assert parsed["user"]["profile"]["token"] == "[REDACTED]"
        assert parsed["user"]["name"] == "Alice"
        assert parsed["user"]["profile"]["bio"] == "hello"

    def test_array_of_objects_redaction(self) -> None:
        body = json.dumps([
            {"username": "alice", "password": "pw1"},
            {"username": "bob", "password": "pw2"},
        ])
        result = redact_body(body)
        parsed = json.loads(result)
        assert parsed[0]["password"] == "[REDACTED]"
        assert parsed[1]["password"] == "[REDACTED]"
        assert parsed[0]["username"] == "alice"
        assert parsed[1]["username"] == "bob"

    def test_non_json_body_returned_unchanged(self) -> None:
        body = "plain text body with no JSON"
        result = redact_body(body)
        assert result == body

    def test_empty_body(self) -> None:
        assert redact_body("") == ""

    def test_body_with_non_string_values(self) -> None:
        body = json.dumps({"password": 12345, "count": 10})
        result = redact_body(body)
        parsed = json.loads(result)
        assert parsed["password"] == "[REDACTED]"
        assert parsed["count"] == 10

    def test_body_with_null_sensitive_value(self) -> None:
        body = json.dumps({"password": None, "name": "alice"})
        result = redact_body(body)
        parsed = json.loads(result)
        assert parsed["password"] == "[REDACTED]"
        assert parsed["name"] == "alice"

    def test_body_with_boolean_sensitive_value(self) -> None:
        body = json.dumps({"secret": True})
        result = redact_body(body)
        parsed = json.loads(result)
        assert parsed["secret"] == "[REDACTED]"

    def test_default_sensitive_fields_constant(self) -> None:
        expected = {"password", "secret", "token", "authorization", "api_key", "credit_card", "ssn"}
        assert expected == SENSITIVE_FIELDS

    def test_fail_silent_on_malformed_json(self) -> None:
        """Redaction must never crash — return body as-is if JSON parsing fails."""
        body = '{"broken": json'
        result = redact_body(body)
        assert result == body


# ---------------------------------------------------------------------------
# redact_headers — header value redaction (AC2)
# ---------------------------------------------------------------------------


class TestRedactHeaders:
    """Test header value redaction for sensitive headers."""

    def test_redacts_authorization_header(self) -> None:
        headers = {"Authorization": "Bearer eyJhbGci...", "Content-Type": "application/json"}
        result = redact_headers(headers)
        assert result["Authorization"] == "[REDACTED]"
        assert result["Content-Type"] == "application/json"

    def test_redacts_cookie_header(self) -> None:
        headers = {"Cookie": "session=abc123; csrf=xyz", "Accept": "text/html"}
        result = redact_headers(headers)
        assert result["Cookie"] == "[REDACTED]"
        assert result["Accept"] == "text/html"

    def test_redacts_set_cookie_header(self) -> None:
        headers = {"Set-Cookie": "session=abc123; HttpOnly; Secure"}
        result = redact_headers(headers)
        assert result["Set-Cookie"] == "[REDACTED]"

    def test_redacts_x_api_key_header(self) -> None:
        headers = {"X-API-Key": "trly_abc123", "Host": "example.com"}
        result = redact_headers(headers)
        assert result["X-API-Key"] == "[REDACTED]"
        assert result["Host"] == "example.com"

    def test_redacts_all_sensitive_headers(self) -> None:
        headers = {
            "Authorization": "Bearer tok",
            "Cookie": "sid=x",
            "Set-Cookie": "sid=y",
            "X-API-Key": "key",
            "Content-Type": "application/json",
        }
        result = redact_headers(headers)
        for h in ["Authorization", "Cookie", "Set-Cookie", "X-API-Key"]:
            assert result[h] == "[REDACTED]", f"Header '{h}' was not redacted"
        assert result["Content-Type"] == "application/json"

    def test_case_insensitive_header_matching(self) -> None:
        headers = {"authorization": "Bearer x", "cookie": "sid=y", "x-api-key": "k"}
        result = redact_headers(headers)
        assert result["authorization"] == "[REDACTED]"
        assert result["cookie"] == "[REDACTED]"
        assert result["x-api-key"] == "[REDACTED]"

    def test_asgi_tuple_headers(self) -> None:
        """ASGI-style list of (bytes, bytes) tuples."""
        headers = [
            (b"authorization", b"Bearer tok"),
            (b"content-type", b"application/json"),
            (b"cookie", b"session=abc"),
        ]
        result = redact_headers(headers)
        assert result["authorization"] == "[REDACTED]"
        assert result["content-type"] == "application/json"
        assert result["cookie"] == "[REDACTED]"

    def test_empty_headers(self) -> None:
        assert redact_headers({}) == {}

    def test_none_headers(self) -> None:
        assert redact_headers(None) == {}

    def test_sensitive_headers_constant(self) -> None:
        expected = {"authorization", "cookie", "set-cookie", "x-api-key"}
        assert expected == SENSITIVE_HEADERS

    def test_preserves_header_names(self) -> None:
        """Header names must be preserved, only values redacted."""
        headers = {"Authorization": "secret", "X-Custom": "safe"}
        result = redact_headers(headers)
        assert "Authorization" in result
        assert "X-Custom" in result


# ---------------------------------------------------------------------------
# redact_patterns — pattern-based redaction (AC3)
# ---------------------------------------------------------------------------


class TestRedactPatterns:
    """Test pattern-based redaction for credit card, email, SSN."""

    def test_redacts_credit_card_16_digits(self) -> None:
        text = "Card: 4111111111111111 is valid"
        result = redact_patterns(text)
        assert "4111111111111111" not in result
        assert "[REDACTED:credit_card]" in result
        assert "Card: " in result
        assert " is valid" in result

    def test_redacts_credit_card_with_dashes(self) -> None:
        text = "Card: 4111-1111-1111-1111"
        result = redact_patterns(text)
        assert "4111-1111-1111-1111" not in result
        assert "[REDACTED:credit_card]" in result

    def test_redacts_credit_card_with_spaces(self) -> None:
        text = "Card: 4111 1111 1111 1111"
        result = redact_patterns(text)
        assert "4111 1111 1111 1111" not in result
        assert "[REDACTED:credit_card]" in result

    def test_redacts_email_address(self) -> None:
        text = "Contact: alice@example.com for info"
        result = redact_patterns(text)
        assert "alice@example.com" not in result
        assert "[REDACTED:email]" in result
        assert "Contact: " in result
        assert " for info" in result

    def test_redacts_email_with_subdomain(self) -> None:
        text = "Email: user@mail.example.co.uk"
        result = redact_patterns(text)
        assert "user@mail.example.co.uk" not in result
        assert "[REDACTED:email]" in result

    def test_redacts_ssn_pattern(self) -> None:
        text = "SSN: 123-45-6789"
        result = redact_patterns(text)
        assert "123-45-6789" not in result
        assert "[REDACTED:ssn]" in result
        assert "SSN: " in result

    def test_redacts_multiple_patterns_in_same_string(self) -> None:
        text = "Email: bob@test.com, Card: 4111111111111111, SSN: 999-88-7777"
        result = redact_patterns(text)
        assert "bob@test.com" not in result
        assert "4111111111111111" not in result
        assert "999-88-7777" not in result
        assert "[REDACTED:email]" in result
        assert "[REDACTED:credit_card]" in result
        assert "[REDACTED:ssn]" in result

    def test_no_false_positive_on_short_numbers(self) -> None:
        """Numbers shorter than 16 digits should not be matched as CC."""
        text = "Order: 123456789"
        result = redact_patterns(text)
        assert result == text

    def test_no_false_positive_on_regular_text(self) -> None:
        text = "Hello world, this is a normal message."
        result = redact_patterns(text)
        assert result == text

    def test_empty_string(self) -> None:
        assert redact_patterns("") == ""

    def test_non_string_values_in_json_body(self) -> None:
        """Pattern redaction applied to JSON body string values."""
        body = json.dumps({
            "email": "alice@example.com",
            "notes": "Contact at bob@test.com",
            "count": 42,
        })
        result = redact_patterns(body)
        assert "alice@example.com" not in result
        assert "bob@test.com" not in result

    def test_fail_silent(self) -> None:
        """redact_patterns must never raise."""
        # Passing None-like edge cases
        result = redact_patterns("")
        assert result == ""


# ---------------------------------------------------------------------------
# Custom field configuration (AC4)
# ---------------------------------------------------------------------------


class TestCustomFieldRedaction:
    """Test custom field redaction via extra_fields parameter."""

    def test_extra_fields_are_redacted(self) -> None:
        body = json.dumps({"my_field": "sensitive", "name": "alice"})
        result = redact_body(body, extra_fields=frozenset({"my_field"}))
        parsed = json.loads(result)
        assert parsed["my_field"] == "[REDACTED]"
        assert parsed["name"] == "alice"

    def test_extra_fields_additive_to_defaults(self) -> None:
        """Custom rules are additive — defaults still apply."""
        body = json.dumps({
            "password": "secret",
            "my_field": "also_sensitive",
            "safe": "ok",
        })
        result = redact_body(body, extra_fields=frozenset({"my_field"}))
        parsed = json.loads(result)
        assert parsed["password"] == "[REDACTED]"
        assert parsed["my_field"] == "[REDACTED]"
        assert parsed["safe"] == "ok"

    def test_empty_extra_fields(self) -> None:
        """Empty frozenset should not change behavior."""
        body = json.dumps({"password": "secret", "name": "alice"})
        result = redact_body(body, extra_fields=frozenset())
        parsed = json.loads(result)
        assert parsed["password"] == "[REDACTED]"
        assert parsed["name"] == "alice"

    def test_none_extra_fields(self) -> None:
        body = json.dumps({"password": "secret"})
        result = redact_body(body, extra_fields=None)
        parsed = json.loads(result)
        assert parsed["password"] == "[REDACTED]"

    def test_multiple_custom_fields(self) -> None:
        body = json.dumps({
            "custom_secret": "val1",
            "internal_key": "val2",
            "safe": "ok",
        })
        result = redact_body(body, extra_fields=frozenset({"custom_secret", "internal_key"}))
        parsed = json.loads(result)
        assert parsed["custom_secret"] == "[REDACTED]"
        assert parsed["internal_key"] == "[REDACTED]"
        assert parsed["safe"] == "ok"

    def test_case_insensitive_custom_fields(self) -> None:
        body = json.dumps({"My_Field": "val"})
        result = redact_body(body, extra_fields=frozenset({"my_field"}))
        parsed = json.loads(result)
        assert parsed["My_Field"] == "[REDACTED]"


class TestConfigRedactFields:
    """Test TRACELY_REDACT_FIELDS env var parsing in config."""

    def test_parses_comma_separated_fields(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TRACELY_REDACT_FIELDS", "my_field,another_field")
        from tracely.config import TracelyConfig
        config = TracelyConfig.from_env()
        assert config.redact_fields == frozenset({"my_field", "another_field"})

    def test_empty_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TRACELY_REDACT_FIELDS", "")
        from tracely.config import TracelyConfig
        config = TracelyConfig.from_env()
        assert config.redact_fields == frozenset()

    def test_unset_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("TRACELY_REDACT_FIELDS", raising=False)
        from tracely.config import TracelyConfig
        config = TracelyConfig.from_env()
        assert config.redact_fields == frozenset()

    def test_trims_whitespace(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TRACELY_REDACT_FIELDS", " my_field , another_field ")
        from tracely.config import TracelyConfig
        config = TracelyConfig.from_env()
        assert config.redact_fields == frozenset({"my_field", "another_field"})

    def test_lowercases_field_names(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TRACELY_REDACT_FIELDS", "My_Field,ANOTHER")
        from tracely.config import TracelyConfig
        config = TracelyConfig.from_env()
        assert config.redact_fields == frozenset({"my_field", "another"})


# ---------------------------------------------------------------------------
# Integration: capture pipeline with redaction (AC5)
# ---------------------------------------------------------------------------

from tracely.capture import capture_request_data, capture_response_data
from tracely.span import Span
from tracely import redaction as redaction_mod


class TestCaptureRedactionIntegration:
    """Test that redaction is applied in the capture pipeline."""

    def setup_method(self) -> None:
        """Reset module-level redaction state before each test."""
        redaction_mod.configure_redaction()

    def test_request_body_field_redaction(self) -> None:
        """AC1: sensitive field values redacted in request body."""
        span = Span(name="test")
        capture_request_data(
            span=span,
            method="POST",
            url="https://example.com/login",
            headers={"Content-Type": "application/json"},
            body=b'{"username": "alice", "password": "s3cret!"}',
            content_type="application/json",
        )
        body = span.attributes["http.request.body"]
        parsed = json.loads(body)
        assert parsed["password"] == "[REDACTED]"
        assert parsed["username"] == "alice"

    def test_request_header_redaction(self) -> None:
        """AC2: sensitive header values redacted."""
        span = Span(name="test")
        capture_request_data(
            span=span,
            method="GET",
            url="https://example.com/api",
            headers={"Authorization": "Bearer tok123", "Accept": "application/json"},
            body=None,
            content_type="",
        )
        headers_json = span.attributes["http.request.headers"]
        parsed = json.loads(headers_json)
        assert parsed["Authorization"] == "[REDACTED]"
        assert parsed["Accept"] == "application/json"

    def test_response_body_field_redaction(self) -> None:
        """AC1: sensitive fields redacted in response body."""
        span = Span(name="test")
        capture_response_data(
            span=span,
            status_code=200,
            headers={"Content-Type": "application/json"},
            body=b'{"token": "jwt_abc", "user": "alice"}',
            content_type="application/json",
        )
        body = span.attributes["http.response.body"]
        parsed = json.loads(body)
        assert parsed["token"] == "[REDACTED]"
        assert parsed["user"] == "alice"

    def test_response_header_redaction(self) -> None:
        """AC2: sensitive response headers redacted."""
        span = Span(name="test")
        capture_response_data(
            span=span,
            status_code=200,
            headers={"Set-Cookie": "session=xyz; HttpOnly", "Content-Type": "text/html"},
            body=b"<html></html>",
            content_type="text/html",
        )
        headers_json = span.attributes["http.response.headers"]
        parsed = json.loads(headers_json)
        assert parsed["Set-Cookie"] == "[REDACTED]"
        assert parsed["Content-Type"] == "text/html"

    def test_pattern_redaction_in_body(self) -> None:
        """AC3: pattern-based redaction applied to body values."""
        span = Span(name="test")
        capture_request_data(
            span=span,
            method="POST",
            url="https://example.com/checkout",
            headers={},
            body=b'{"note": "Email is alice@example.com, card 4111111111111111"}',
            content_type="application/json",
        )
        body = span.attributes["http.request.body"]
        assert "alice@example.com" not in body
        assert "4111111111111111" not in body
        assert "[REDACTED:email]" in body
        assert "[REDACTED:credit_card]" in body

    def test_custom_field_redaction_via_config(self) -> None:
        """AC4: custom fields from configure_redaction are applied."""
        redaction_mod.configure_redaction(extra_fields=frozenset({"my_secret"}))
        span = Span(name="test")
        capture_request_data(
            span=span,
            method="POST",
            url="https://example.com/api",
            headers={},
            body=b'{"my_secret": "hidden", "name": "alice"}',
            content_type="application/json",
        )
        body = span.attributes["http.request.body"]
        parsed = json.loads(body)
        assert parsed["my_secret"] == "[REDACTED]"
        assert parsed["name"] == "alice"

    def test_original_data_not_modified(self) -> None:
        """AC5: original application data is never modified."""
        original_headers = {"Authorization": "Bearer tok", "Accept": "text/html"}
        original_body = b'{"password": "secret", "user": "alice"}'

        # Take copies to compare later
        headers_before = dict(original_headers)
        body_before = bytes(original_body)

        span = Span(name="test")
        capture_request_data(
            span=span,
            method="POST",
            url="https://example.com/api",
            headers=original_headers,
            body=original_body,
            content_type="application/json",
        )

        # Original data must be unchanged
        assert original_headers == headers_before
        assert original_body == body_before

    def test_non_json_body_not_broken(self) -> None:
        """Non-JSON bodies should pass through unmodified by field redaction."""
        span = Span(name="test")
        capture_request_data(
            span=span,
            method="POST",
            url="https://example.com/upload",
            headers={},
            body=b"plain text with password mention",
            content_type="text/plain",
        )
        assert span.attributes["http.request.body"] == "plain text with password mention"

    def test_binary_body_still_replaced(self) -> None:
        """Binary bodies should still be replaced with placeholder, not redacted."""
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

    def test_asgi_headers_redacted(self) -> None:
        """ASGI-style byte tuple headers also get redacted."""
        span = Span(name="test")
        capture_request_data(
            span=span,
            method="GET",
            url="https://example.com/api",
            headers=[
                (b"authorization", b"Bearer secret_tok"),
                (b"content-type", b"application/json"),
            ],
            body=None,
            content_type="",
        )
        headers_json = span.attributes["http.request.headers"]
        parsed = json.loads(headers_json)
        assert parsed["authorization"] == "[REDACTED]"
        assert parsed["content-type"] == "application/json"
