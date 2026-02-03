"""Configuration management for the TRACELY SDK."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

DEFAULT_ENDPOINT = "https://api.tracely.dev"


@dataclass
class TracelyConfig:
    """SDK configuration. Reads from env vars or accepts explicit values."""

    api_key: str | None = None
    environment: str | None = None
    endpoint: str = DEFAULT_ENDPOINT
    service_name: str | None = None
    service_version: str | None = None
    redact_fields: frozenset[str] = field(default_factory=frozenset)

    @classmethod
    def from_env(cls) -> TracelyConfig:
        """Create config from environment variables."""
        raw_fields = os.environ.get("TRACELY_REDACT_FIELDS", "")
        redact_fields = frozenset(
            f.strip().lower() for f in raw_fields.split(",") if f.strip()
        )
        return cls(
            api_key=os.environ.get("TRACELY_API_KEY"),
            environment=os.environ.get("ENVIRONMENT"),
            endpoint=os.environ.get("TRACELY_ENDPOINT", DEFAULT_ENDPOINT),
            redact_fields=redact_fields,
        )

    @property
    def enabled(self) -> bool:
        """SDK is enabled only when an API key is present."""
        return self.api_key is not None
