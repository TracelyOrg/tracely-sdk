"""Request/response data capture utilities.

Provides body processing (truncation at 64KB, binary content replacement),
URL construction, header sanitization, smart data redaction (FR8, FR11),
and span attribute attachment for full request/response data capture (FR6, FR7).

All public functions are fail-silent — exceptions are caught and logged
at DEBUG level to satisfy the SDK's zero-crash guarantee.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from tracely.redaction import (
    get_extra_fields,
    redact_body,
    redact_headers,
    redact_patterns,
)

logger = logging.getLogger("tracely")

# 64KB body size limit per AC3
MAX_BODY_SIZE: int = 64 * 1024

# Binary content type prefixes — bodies with these types are replaced
# with a placeholder rather than captured verbatim.
_BINARY_PREFIXES: tuple[str, ...] = (
    "image/",
    "video/",
    "audio/",
    "application/octet-stream",
    "application/zip",
    "application/gzip",
    "application/pdf",
    "application/x-tar",
    "application/x-bzip2",
    "application/x-7z-compressed",
    "application/vnd.",
    "font/",
)


def is_binary_content_type(content_type: str) -> bool:
    """Return True if the content type represents binary data.

    Matching is case-insensitive and ignores parameters (charset, etc.).
    """
    if not content_type:
        return False
    # Normalize: lowercase, strip parameters for prefix check
    ct_lower = content_type.lower().split(";")[0].strip()
    return ct_lower.startswith(_BINARY_PREFIXES)


def process_body(
    body: bytes | str | None,
    content_type: str,
) -> tuple[str, dict[str, str]]:
    """Process a request or response body for span storage.

    Returns:
        A tuple of (processed_body_str, metadata_dict).
        metadata_dict may contain:
          - http.body.original_length: original byte length (if truncated or binary)
          - http.body.truncated: "true" (if truncated)

    Rules (per AC3/AC4):
        - Bodies > 64KB are truncated with a ``[truncated]`` marker.
        - Binary content types are replaced with ``[binary: <ct>, <size> bytes]``.
        - Empty/None bodies return empty string with no metadata.
    """
    if body is None:
        return "", {}

    if isinstance(body, str):
        raw = body.encode("utf-8", errors="replace")
    else:
        raw = body

    if len(raw) == 0:
        return "", {}

    meta: dict[str, str] = {}

    # Binary content type — replace with placeholder (AC4)
    if is_binary_content_type(content_type or ""):
        meta["body.original_length"] = str(len(raw))
        return f"[binary: {content_type}, {len(raw)} bytes]", meta

    # Truncation at 64KB (AC3)
    if len(raw) > MAX_BODY_SIZE:
        meta["body.original_length"] = str(len(raw))
        meta["body.truncated"] = "true"
        truncated = raw[:MAX_BODY_SIZE].decode("utf-8", errors="replace")
        return truncated + "[truncated]", meta

    return raw.decode("utf-8", errors="replace"), meta


def build_url(scheme: str, host: str, path: str, query_string: str) -> str:
    """Construct a full URL from its components.

    Args:
        scheme: URL scheme (http, https).
        host: Hostname, optionally with port (e.g. "example.com:8080").
        path: Request path (e.g. "/api/users").
        query_string: Raw query string without leading '?'.

    Returns:
        Full URL string.
    """
    if not path:
        path = "/"
    elif not path.startswith("/"):
        path = "/" + path

    url = f"{scheme}://{host}{path}"
    if query_string:
        url = f"{url}?{query_string}"
    return url


def sanitize_headers(
    headers: dict[str, str] | list[tuple[bytes, bytes]] | None,
) -> str:
    """Convert headers to a JSON string for span attribute storage.

    Applies smart redaction (FR8) to sensitive header values before
    serialization.  The original headers object is never mutated.

    Accepts:
        - dict[str, str]: Already key-value pairs.
        - list[tuple[bytes, bytes]]: ASGI-style raw header pairs.
        - None: Returns empty JSON object.

    Returns:
        JSON string representation of headers with sensitive values redacted.
    """
    if headers is None:
        return "{}"

    # redact_headers returns a new dict — original data is never modified
    redacted = redact_headers(headers)
    if not redacted:
        return "{}"
    return json.dumps(redacted, default=str)


def capture_request_data(
    span: Any,
    *,
    method: str,
    url: str,
    headers: dict[str, str] | list[tuple[bytes, bytes]] | None = None,
    body: bytes | str | None = None,
    content_type: str = "",
    query_params: str = "",
) -> None:
    """Attach request data as span attributes (FR6).

    Fail-silent — never raises.
    """
    try:
        span.set_attribute("http.method", method)
        span.set_attribute("http.url", url)
        span.set_attribute("http.request.headers", sanitize_headers(headers))

        processed_body, meta = process_body(body, content_type)
        # Apply smart data redaction (FR8) — field-name + pattern-based
        redacted_body = redact_body(processed_body, extra_fields=get_extra_fields())
        redacted_body = redact_patterns(redacted_body)
        span.set_attribute("http.request.body", redacted_body)
        for key, value in meta.items():
            span.set_attribute(f"http.request.{key}", value)

        if query_params:
            span.set_attribute("http.request.query", query_params)
    except Exception:
        logger.debug("Error capturing request data", exc_info=True)


def capture_response_data(
    span: Any,
    *,
    status_code: int,
    headers: dict[str, str] | list[tuple[bytes, bytes]] | None = None,
    body: bytes | str | None = None,
    content_type: str = "",
) -> None:
    """Attach response data as span attributes (FR7).

    Fail-silent — never raises.
    """
    try:
        span.set_attribute("http.status_code", str(status_code))
        span.set_attribute("http.response.headers", sanitize_headers(headers))

        processed_body, meta = process_body(body, content_type or "")
        # Apply smart data redaction (FR8) — field-name + pattern-based
        redacted_body = redact_body(processed_body, extra_fields=get_extra_fields())
        redacted_body = redact_patterns(redacted_body)
        span.set_attribute("http.response.body", redacted_body)
        for key, value in meta.items():
            span.set_attribute(f"http.response.{key}", value)
    except Exception:
        logger.debug("Error capturing response data", exc_info=True)
