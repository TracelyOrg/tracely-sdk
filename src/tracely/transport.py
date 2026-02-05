"""HTTP transport with buffering and retry for span data."""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from typing import Any

import httpx

logger = logging.getLogger("tracely")

DEFAULT_BATCH_SIZE = 50
DEFAULT_MAX_BUFFER = 1000
DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 0.1  # reduced from 1.0s for faster recovery
DEFAULT_MAX_DELAY = 5.0   # reduced from 30s to avoid long delays


class SpanBuffer:
    """Thread-safe in-memory buffer for span data.

    Drops oldest spans when max_size is exceeded.
    """

    def __init__(
        self,
        max_size: int = DEFAULT_MAX_BUFFER,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> None:
        self._buffer: deque[dict[str, Any]] = deque(maxlen=max_size)
        self._batch_size = batch_size

    def enqueue(self, span: dict[str, Any]) -> None:
        """Add a span to the buffer. Oldest dropped if full."""
        self._buffer.append(span)

    def flush(self) -> list[dict[str, Any]]:
        """Return all buffered spans and clear the buffer."""
        spans = list(self._buffer)
        self._buffer.clear()
        return spans

    @property
    def size(self) -> int:
        """Number of spans currently in buffer."""
        return len(self._buffer)

    @property
    def is_ready(self) -> bool:
        """Buffer has reached the batch threshold."""
        return len(self._buffer) >= self._batch_size


class HttpTransport:
    """Sends span data to the TRACELY API with retry and backoff.

    All errors are caught silently — the host application must never be
    affected by transport failures (FR10, NFR22).
    """

    def __init__(
        self,
        endpoint: str,
        api_key: str,
        max_retries: int = DEFAULT_MAX_RETRIES,
        base_delay: float = DEFAULT_BASE_DELAY,
        max_delay: float = DEFAULT_MAX_DELAY,
    ) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._api_key = api_key
        self._max_retries = max_retries
        self._base_delay = base_delay
        self._max_delay = max_delay
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(10.0),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/x-protobuf",
            },
        )

    async def send(self, payload: bytes) -> bool:
        """Send OTLP protobuf payload to the API. Returns True on success.

        Args:
            payload: Serialized OTLP ExportTraceServiceRequest bytes.

        Never raises — all exceptions are caught and logged (FR10, NFR22).
        """
        if not payload:
            return True

        url = f"{self._endpoint}/v1/traces"
        attempt = 0
        max_attempts = 1 + self._max_retries

        while attempt < max_attempts:
            try:
                response = await self._client.post(url, content=payload)
                response.raise_for_status()
                return True
            except (httpx.HTTPStatusError, httpx.ConnectError, httpx.TimeoutException, ConnectionError, OSError) as exc:
                attempt += 1
                if attempt < max_attempts:
                    delay = min(
                        self._base_delay * (2 ** (attempt - 1)),
                        self._max_delay,
                    )
                    logger.debug(
                        "TRACELY transport retry %d/%d after %.1fs: %s",
                        attempt,
                        self._max_retries,
                        delay,
                        exc,
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.debug(
                        "TRACELY transport failed after %d attempts: %s",
                        max_attempts,
                        exc,
                    )
            except Exception as exc:
                # Catch-all: SDK must never crash the host app
                logger.debug("TRACELY transport unexpected error: %s", exc)
                return False

        return False

    async def close(self) -> None:
        """Close the HTTP client."""
        await self._client.aclose()
