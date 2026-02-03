"""Core SDK initialization and lifecycle."""

from __future__ import annotations

import logging

from tracely.config import TracelyConfig
from tracely.detection import FrameworkInfo, detect_framework
from tracely.exporter import BatchSpanExporter
from tracely.instrumentation import get_instrumentor
from tracely.instrumentation.base import BaseInstrumentor
from tracely.redaction import configure_redaction
from tracely.span_processor import SpanProcessor, set_processor
from tracely.transport import HttpTransport, SpanBuffer

logger = logging.getLogger("tracely")

_instance: TracelySdk | None = None


class TracelySdk:
    """Singleton managing SDK state and lifecycle."""

    def __init__(
        self,
        config: TracelyConfig,
        framework_info: FrameworkInfo | None = None,
        instrumentor: BaseInstrumentor | None = None,
        buffer: SpanBuffer | None = None,
        transport: HttpTransport | None = None,
        processor: SpanProcessor | None = None,
        exporter: BatchSpanExporter | None = None,
    ) -> None:
        self.config = config
        self.enabled = config.enabled
        self.framework_info = framework_info
        self.instrumentor = instrumentor
        self.buffer = buffer
        self.transport = transport
        self.processor = processor
        self.exporter = exporter

    def shutdown(self) -> None:
        """Flush buffers, deactivate instrumentation, release resources."""
        # Stop batch exporter (flushes remaining spans)
        if self.exporter is not None:
            try:
                self.exporter.stop()
            except Exception:
                logger.debug("Error stopping exporter", exc_info=True)

        # Deactivate instrumentation
        if self.instrumentor is not None:
            try:
                self.instrumentor.deactivate()
            except Exception:
                logger.debug("Error deactivating instrumentor", exc_info=True)

        # Clear global processor
        set_processor(None)

        self.enabled = False


def init(
    *,
    api_key: str | None = None,
    environment: str | None = None,
    endpoint: str | None = None,
    service_name: str | None = None,
    service_version: str | None = None,
) -> None:
    """Initialize the TRACELY SDK.

    Reads configuration from environment variables by default.
    Explicit parameters override env vars.

    When enabled (API key present), creates the full export pipeline:
    SpanBuffer → SpanProcessor → BatchSpanExporter → HttpTransport → OTLP/HTTP

    Args:
        api_key: Override TRACELY_API_KEY env var.
        environment: Override ENVIRONMENT env var.
        endpoint: Override TRACELY_ENDPOINT env var.
        service_name: Label for this service (e.g., "api", "celery-worker").
        service_version: Version string for this service.
    """
    global _instance

    if _instance is not None:
        return

    config = TracelyConfig.from_env()

    if api_key is not None:
        config.api_key = api_key
    if environment is not None:
        config.environment = environment
    if endpoint is not None:
        config.endpoint = endpoint
    if service_name is not None:
        config.service_name = service_name
    if service_version is not None:
        config.service_version = service_version

    # Configure smart data redaction with custom fields from env (FR8, FR11)
    configure_redaction(extra_fields=config.redact_fields)

    if not config.enabled:
        logger.warning(
            "TRACELY_API_KEY not set. SDK is disabled — "
            "no telemetry will be collected or sent."
        )

    # Detect framework (always, even when disabled — for diagnostics)
    framework_info = detect_framework()

    # Create export pipeline when SDK is enabled
    buffer: SpanBuffer | None = None
    transport: HttpTransport | None = None
    processor: SpanProcessor | None = None
    exporter: BatchSpanExporter | None = None

    if config.enabled and config.api_key:
        buffer = SpanBuffer()
        transport = HttpTransport(
            endpoint=config.endpoint,
            api_key=config.api_key,
        )
        processor = SpanProcessor(buffer=buffer)
        exporter = BatchSpanExporter(buffer=buffer, transport=transport)

        # Register global processor for middleware to use
        set_processor(processor)

        # Start background export thread
        try:
            exporter.start()
        except Exception:
            logger.debug("Error starting batch exporter", exc_info=True)

    # Activate instrumentation only when SDK is enabled
    instrumentor: BaseInstrumentor | None = None
    if config.enabled and framework_info is not None:
        instrumentor = get_instrumentor(framework_info)
        if instrumentor is not None:
            try:
                instrumentor.activate()
            except Exception:
                logger.debug("Error activating instrumentor", exc_info=True)
                instrumentor = None

    if framework_info is not None:
        logger.info("TRACELY: Detected framework: %s", framework_info.name)
    else:
        logger.info(
            "TRACELY: No supported framework detected. "
            "Use manual instrumentation for custom setups."
        )

    _instance = TracelySdk(
        config=config,
        framework_info=framework_info,
        instrumentor=instrumentor,
        buffer=buffer,
        transport=transport,
        processor=processor,
        exporter=exporter,
    )


def shutdown() -> None:
    """Gracefully shut down the SDK, flushing any buffered data."""
    global _instance

    if _instance is not None:
        _instance.shutdown()
        _instance = None


def _sdk_instance() -> TracelySdk | None:
    """Return the current SDK instance (for testing)."""
    return _instance


def _reset() -> None:
    """Reset SDK state (for testing only)."""
    global _instance
    if _instance is not None:
        _instance.shutdown()
    _instance = None
    set_processor(None)
