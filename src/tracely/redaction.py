"""Smart data redaction for the TRACELY SDK (FR8, FR11, NFR11).

Provides field-name based redaction for JSON bodies, header value
redaction for sensitive headers, and pattern-based redaction for
credit card numbers, email addresses, and SSNs.

All public functions are fail-silent — exceptions are caught and logged
at DEBUG level to satisfy the SDK's zero-crash guarantee.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger("tracely")

# Default sensitive field names (AC1) — matched case-insensitively
SENSITIVE_FIELDS: frozenset[str] = frozenset({
    "password",
    "secret",
    "token",
    "authorization",
    "api_key",
    "credit_card",
    "ssn",
})

# Default sensitive header names (AC2) — matched case-insensitively
SENSITIVE_HEADERS: frozenset[str] = frozenset({
    "authorization",
    "cookie",
    "set-cookie",
    "x-api-key",
})

REDACTED: str = "[REDACTED]"

# Pattern-based redaction (AC3) — compiled regexes for performance
# Credit card: 16 digits, optionally separated by dashes or spaces
_CC_PATTERN: re.Pattern[str] = re.compile(
    r"\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b"
)
# SSN: XXX-XX-XXXX format
_SSN_PATTERN: re.Pattern[str] = re.compile(
    r"\b\d{3}-\d{2}-\d{4}\b"
)
# Email: standard email pattern
_EMAIL_PATTERN: re.Pattern[str] = re.compile(
    r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
)


# Module-level state for custom redaction fields (set via configure_redaction)
_extra_fields: frozenset[str] = frozenset()


def configure_redaction(
    *,
    extra_fields: frozenset[str] = frozenset(),
) -> None:
    """Configure module-level redaction settings.

    Called by SDK init to propagate ``TRACELY_REDACT_FIELDS`` config.

    Args:
        extra_fields: Additional field names to redact (additive to defaults).
    """
    global _extra_fields
    _extra_fields = extra_fields


def get_extra_fields() -> frozenset[str]:
    """Return the currently configured extra redaction fields."""
    return _extra_fields


def _redact_value(obj: Any, sensitive: frozenset[str]) -> Any:
    """Recursively redact sensitive field values in a parsed JSON structure.

    Field name matching is case-insensitive.  Field names are preserved;
    only values are replaced with ``[REDACTED]``.
    """
    if isinstance(obj, dict):
        return {
            key: REDACTED if key.lower() in sensitive else _redact_value(value, sensitive)
            for key, value in obj.items()
        }
    if isinstance(obj, list):
        return [_redact_value(item, sensitive) for item in obj]
    return obj


def redact_body(
    body: str,
    *,
    extra_fields: frozenset[str] | None = None,
) -> str:
    """Redact sensitive field values in a JSON body string.

    Args:
        body: The body string (may or may not be valid JSON).
        extra_fields: Additional field names to redact (merged with defaults).

    Returns:
        The body with sensitive field values replaced by ``[REDACTED]``,
        or the original body unchanged if it is not valid JSON.
    """
    if not body:
        return body

    sensitive = SENSITIVE_FIELDS
    if extra_fields:
        sensitive = SENSITIVE_FIELDS | extra_fields

    try:
        parsed = json.loads(body)
    except (json.JSONDecodeError, ValueError):
        return body

    try:
        redacted = _redact_value(parsed, sensitive)
        # Only re-serialize if redaction actually changed something;
        # otherwise preserve original body formatting exactly.
        if redacted == parsed:
            return body
        return json.dumps(redacted)
    except Exception:
        logger.debug("Error during body redaction", exc_info=True)
        return body


def redact_headers(
    headers: dict[str, str] | list[tuple[bytes, bytes]] | None,
) -> dict[str, str]:
    """Redact sensitive header values.

    Args:
        headers: Headers as dict, ASGI-style byte tuples, or None.

    Returns:
        A new dict with sensitive header values replaced by ``[REDACTED]``.
        Non-sensitive headers are preserved as-is.
    """
    if headers is None:
        return {}

    try:
        if isinstance(headers, dict):
            if not headers:
                return {}
            return {
                key: REDACTED if key.lower() in SENSITIVE_HEADERS else value
                for key, value in headers.items()
            }

        # ASGI-style list of (name_bytes, value_bytes) tuples
        result: dict[str, str] = {}
        for name, value in headers:
            key = name.decode("utf-8", errors="replace") if isinstance(name, bytes) else str(name)
            val = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value)
            result[key] = REDACTED if key.lower() in SENSITIVE_HEADERS else val
        return result
    except Exception:
        logger.debug("Error during header redaction", exc_info=True)
        return {}


def redact_patterns(text: str) -> str:
    """Apply pattern-based redaction for credit card, email, and SSN.

    Scans the input text and replaces matches with typed placeholders:
    ``[REDACTED:credit_card]``, ``[REDACTED:email]``, ``[REDACTED:ssn]``.

    Args:
        text: The text string to scan.

    Returns:
        The text with matched patterns replaced, or the original text
        if no patterns are found or an error occurs.
    """
    if not text:
        return text

    try:
        # Order matters: SSN before CC to avoid SSN being partially matched
        # as a CC sub-pattern.  SSN is more specific (XXX-XX-XXXX).
        result = _SSN_PATTERN.sub("[REDACTED:ssn]", text)
        result = _CC_PATTERN.sub("[REDACTED:credit_card]", result)
        result = _EMAIL_PATTERN.sub("[REDACTED:email]", result)
        return result
    except Exception:
        logger.debug("Error during pattern redaction", exc_info=True)
        return text
