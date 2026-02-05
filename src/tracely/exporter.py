"""Batch span exporter with background flush loop (FR9, AC3).

Drains SpanBuffer on a timer interval or batch-size threshold,
serializes to OTLP protobuf, and sends via HttpTransport.

Uses a daemon thread with its own event loop so it works in both
sync (Flask/Django) and async (FastAPI) host applications.

All operations are fail-silent — never crashes the host application.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import TYPE_CHECKING

from tracely.otlp import serialize_spans

if TYPE_CHECKING:
    from tracely.transport import HttpTransport, SpanBuffer

logger = logging.getLogger("tracely")

DEFAULT_FLUSH_INTERVAL = 0.2  # seconds - reduced from 1.0s for near-instant delivery


class BatchSpanExporter:
    """Background exporter that batch-sends buffered spans via OTLP/HTTP.

    Runs in a daemon thread with its own asyncio event loop so that
    SDK init/shutdown can be called from any context (sync or async).

    Args:
        buffer: SpanBuffer to drain spans from.
        transport: HttpTransport to send OTLP protobuf bytes.
        flush_interval: Seconds between flush cycles (default 1.0 per AC3).
    """

    def __init__(
        self,
        buffer: SpanBuffer,
        transport: HttpTransport,
        flush_interval: float = DEFAULT_FLUSH_INTERVAL,
    ) -> None:
        self._buffer = buffer
        self._transport = transport
        self._flush_interval = flush_interval
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._notify_event = threading.Event()

    def start(self) -> None:
        """Start the background export thread."""
        self._stop_event.clear()
        self._notify_event.clear()
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="tracely-exporter",
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop the background thread and drain remaining spans.

        Blocks until the thread exits (up to 5 seconds).
        The thread performs a final flush before exiting.
        """
        self._stop_event.set()
        self._notify_event.set()  # Wake up if sleeping
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=5.0)

    def notify(self) -> None:
        """Wake the export loop (e.g. when batch threshold is reached)."""
        self._notify_event.set()

    def _run(self) -> None:
        """Background loop running in daemon thread."""
        asyncio.set_event_loop(self._loop)
        try:
            while not self._stop_event.is_set():
                # Wait for interval or notification, whichever comes first
                self._notify_event.wait(timeout=self._flush_interval)
                self._notify_event.clear()

                if self._stop_event.is_set():
                    break

                self._loop.run_until_complete(self._flush())

            # Final drain before thread exits
            self._loop.run_until_complete(self._flush())
        except Exception:
            logger.debug("TRACELY: Error in exporter thread", exc_info=True)
        finally:
            self._loop.close()

    async def _flush(self) -> None:
        """Drain buffer, serialize to OTLP protobuf, send via transport."""
        spans = self._buffer.flush()
        if not spans:
            return

        try:
            payload = serialize_spans(spans)
        except Exception:
            logger.debug("TRACELY: Error serializing spans to OTLP", exc_info=True)
            return

        try:
            success = await self._transport.send(payload)
            if not success:
                logger.debug(
                    "TRACELY: Batch export failed for %d spans", len(spans),
                )
        except Exception:
            logger.debug("TRACELY: Unexpected error in batch export", exc_info=True)
