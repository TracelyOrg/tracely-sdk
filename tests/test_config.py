"""Tests for configuration management (AC2, AC3)."""

from __future__ import annotations

import os
from unittest.mock import patch

from tracely.config import TracelyConfig


class TestTracelyConfig:
    """Configuration reads env vars and supports overrides."""

    def test_reads_api_key_from_env(self):
        """AC2: Reads TRACELY_API_KEY from environment."""
        with patch.dict(os.environ, {"TRACELY_API_KEY": "trly_abc123"}):
            config = TracelyConfig.from_env()
            assert config.api_key == "trly_abc123"

    def test_reads_environment_from_env(self):
        """AC2: Reads ENVIRONMENT from env (generic, works with any framework)."""
        with patch.dict(os.environ, {
            "TRACELY_API_KEY": "trly_abc123",
            "ENVIRONMENT": "production",
        }):
            config = TracelyConfig.from_env()
            assert config.environment == "production"

    def test_reads_endpoint_from_env(self):
        """AC2: Reads optional TRACELY_ENDPOINT."""
        with patch.dict(os.environ, {
            "TRACELY_API_KEY": "trly_abc123",
            "TRACELY_ENDPOINT": "https://custom.api.com",
        }):
            config = TracelyConfig.from_env()
            assert config.endpoint == "https://custom.api.com"

    def test_default_endpoint(self):
        """AC2: Defaults to cloud API when TRACELY_ENDPOINT not set."""
        with patch.dict(os.environ, {"TRACELY_API_KEY": "trly_abc123"}, clear=True):
            config = TracelyConfig.from_env()
            assert config.endpoint == "https://i.tracely.sh"

    def test_default_environment_is_none(self):
        """Environment defaults to None when not set."""
        with patch.dict(os.environ, {"TRACELY_API_KEY": "trly_abc123"}, clear=True):
            config = TracelyConfig.from_env()
            assert config.environment is None

    def test_no_api_key_returns_config_with_none(self):
        """AC3: Missing API key results in config with api_key=None."""
        with patch.dict(os.environ, {}, clear=True):
            config = TracelyConfig.from_env()
            assert config.api_key is None

    def test_explicit_overrides(self):
        """Explicit parameters override env vars."""
        with patch.dict(os.environ, {"TRACELY_API_KEY": "trly_env_key"}):
            config = TracelyConfig(
                api_key="trly_explicit_key",
                environment="staging",
                endpoint="https://custom.endpoint.com",
            )
            assert config.api_key == "trly_explicit_key"
            assert config.environment == "staging"
            assert config.endpoint == "https://custom.endpoint.com"

    def test_service_name_not_read_from_env(self):
        """service_name is init-only, not read from env."""
        with patch.dict(os.environ, {
            "TRACELY_API_KEY": "trly_abc123",
            "TRACELY_SERVICE_NAME": "should-be-ignored",
        }):
            config = TracelyConfig.from_env()
            assert config.service_name is None

    def test_service_version_not_read_from_env(self):
        """service_version is init-only, not read from env."""
        with patch.dict(os.environ, {
            "TRACELY_API_KEY": "trly_abc123",
            "TRACELY_SERVICE_VERSION": "9.9.9",
        }):
            config = TracelyConfig.from_env()
            assert config.service_version is None

    def test_service_name_set_explicitly(self):
        """service_name can be set via constructor."""
        config = TracelyConfig(api_key="trly_abc123", service_name="celery-worker")
        assert config.service_name == "celery-worker"

    def test_service_version_set_explicitly(self):
        """service_version can be set via constructor."""
        config = TracelyConfig(api_key="trly_abc123", service_version="2.0.0")
        assert config.service_version == "2.0.0"

    def test_enabled_when_api_key_present(self):
        """SDK is enabled when API key is present."""
        config = TracelyConfig(api_key="trly_abc123")
        assert config.enabled is True

    def test_disabled_when_no_api_key(self):
        """SDK is disabled when no API key."""
        config = TracelyConfig(api_key=None)
        assert config.enabled is False
