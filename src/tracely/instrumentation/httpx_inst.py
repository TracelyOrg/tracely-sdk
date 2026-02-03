"""External HTTP call instrumentation via httpx event hooks.

Creates child spans for outbound HTTP calls made through httpx,
capturing method, URL, status code, and duration (AC3).

All instrumentation is fail-silent — never crashes the host application.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from tracely.context import get_current_span
from tracely.span import Span

logger = logging.getLogger("tracely")


class HttpxInstrumentor:
    """Instruments httpx clients to create child spans for outbound HTTP calls.

    Usage:
        instrumentor = HttpxInstrumentor()
        instrumentor.activate()  # Patches httpx.Client and httpx.AsyncClient
        instrumentor.deactivate()  # Restores originals
    """

    def __init__(self) -> None:
        self._active = False
        self._original_sync_send: Any = None
        self._original_async_send: Any = None

    def activate(self) -> None:
        """Patch httpx Client/AsyncClient to create child spans."""
        if self._active:
            return

        self._original_sync_send = httpx.Client.send
        self._original_async_send = httpx.AsyncClient.send

        original_sync = self._original_sync_send
        original_async = self._original_async_send

        def instrumented_sync_send(client_self: httpx.Client, request: httpx.Request, **kwargs: Any) -> httpx.Response:
            parent = get_current_span()
            if parent is None:
                return original_sync(client_self, request, **kwargs)

            span = Span(
                name=f"HTTP {request.method} {request.url.host}",
                parent=parent,
                kind="CLIENT",
            )
            span.set_attribute("http.method", str(request.method))
            span.set_attribute("http.url", str(request.url))

            try:
                response = original_sync(client_self, request, **kwargs)
                span.set_attribute("http.status_code", str(response.status_code))
                if response.status_code >= 400:
                    span.set_status("ERROR", f"HTTP {response.status_code}")
                else:
                    span.set_status("OK")
                return response
            except Exception as exc:
                span.set_status("ERROR", str(exc))
                span.set_attribute("error", "true")
                span.set_attribute("error.type", type(exc).__name__)
                span.set_attribute("error.message", str(exc))
                raise
            finally:
                span.end()

        async def instrumented_async_send(client_self: httpx.AsyncClient, request: httpx.Request, **kwargs: Any) -> httpx.Response:
            parent = get_current_span()
            if parent is None:
                return await original_async(client_self, request, **kwargs)

            span = Span(
                name=f"HTTP {request.method} {request.url.host}",
                parent=parent,
                kind="CLIENT",
            )
            span.set_attribute("http.method", str(request.method))
            span.set_attribute("http.url", str(request.url))

            try:
                response = await original_async(client_self, request, **kwargs)
                span.set_attribute("http.status_code", str(response.status_code))
                if response.status_code >= 400:
                    span.set_status("ERROR", f"HTTP {response.status_code}")
                else:
                    span.set_status("OK")
                return response
            except Exception as exc:
                span.set_status("ERROR", str(exc))
                span.set_attribute("error", "true")
                span.set_attribute("error.type", type(exc).__name__)
                span.set_attribute("error.message", str(exc))
                raise
            finally:
                span.end()

        httpx.Client.send = instrumented_sync_send  # type: ignore[assignment]
        httpx.AsyncClient.send = instrumented_async_send  # type: ignore[assignment]
        self._active = True
        logger.info("TRACELY: httpx instrumentation activated")

    def deactivate(self) -> None:
        """Restore original httpx send methods."""
        if not self._active:
            return

        if self._original_sync_send is not None:
            httpx.Client.send = self._original_sync_send  # type: ignore[assignment]
        if self._original_async_send is not None:
            httpx.AsyncClient.send = self._original_async_send  # type: ignore[assignment]

        self._active = False
        self._original_sync_send = None
        self._original_async_send = None
        logger.debug("TRACELY: httpx instrumentation deactivated")

    @property
    def is_active(self) -> bool:
        return self._active
