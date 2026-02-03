"""Core SDK initialization and lifecycle."""

from __future__ import annotations

import logging

from tracely.config import TracelyConfig

logger = logging.getLogger("tracely")

_instance: TracelySdk | None = None


class TracelySdk:
    """Singleton managing SDK state and lifecycle."""

    def __init__(self, config: TracelyConfig) -> None:
        self.config = config
        self.enabled = config.enabled

    def shutdown(self) -> None:
        """Flush buffers and release resources."""
        self.enabled = False


def init(
    *,
    api_key: str | None = None,
    environment: str | None = None,
    endpoint: str | None = None,
) -> None:
    """Initialize the TRACELY SDK.

    Reads configuration from environment variables by default.
    Explicit parameters override env vars.

    Args:
        api_key: Override TRACELY_API_KEY env var.
        environment: Override TRACELY_ENVIRONMENT env var.
        endpoint: Override TRACELY_ENDPOINT env var.
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

    if not config.enabled:
        logger.warning(
            "TRACELY_API_KEY not set. SDK is disabled — "
            "no telemetry will be collected or sent."
        )

    _instance = TracelySdk(config=config)


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
    _instance = None
