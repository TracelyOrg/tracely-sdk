"""Tests for SDK init() and shutdown() (AC2, AC3)."""

from __future__ import annotations

import logging
import os
from unittest.mock import patch

import tracely
from tracely.sdk import _sdk_instance, _reset


class TestInit:
    """tracely.init() behavior."""

    def setup_method(self):
        """Reset SDK state before each test."""
        _reset()

    def test_init_with_api_key_env(self):
        """AC2: init() reads TRACELY_API_KEY and initializes successfully."""
        with patch.dict(os.environ, {"TRACELY_API_KEY": "trly_abc123"}):
            tracely.init()
            sdk = _sdk_instance()
            assert sdk is not None
            assert sdk.config.api_key == "trly_abc123"
            assert sdk.enabled is True

    def test_init_with_explicit_api_key(self):
        """init() accepts explicit api_key parameter."""
        tracely.init(api_key="trly_explicit")
        sdk = _sdk_instance()
        assert sdk is not None
        assert sdk.config.api_key == "trly_explicit"

    def test_init_with_environment(self):
        """AC2: init() reads ENVIRONMENT from env."""
        with patch.dict(os.environ, {
            "TRACELY_API_KEY": "trly_abc123",
            "ENVIRONMENT": "production",
        }):
            tracely.init()
            sdk = _sdk_instance()
            assert sdk.config.environment == "production"

    def test_init_with_endpoint(self):
        """AC2: init() reads TRACELY_ENDPOINT."""
        with patch.dict(os.environ, {
            "TRACELY_API_KEY": "trly_abc123",
            "TRACELY_ENDPOINT": "https://custom.api.com",
        }):
            tracely.init()
            sdk = _sdk_instance()
            assert sdk.config.endpoint == "https://custom.api.com"

    def test_init_without_api_key_logs_warning(self, caplog):
        """AC3: Missing API key logs warning but does not crash."""
        with patch.dict(os.environ, {}, clear=True):
            with caplog.at_level(logging.WARNING, logger="tracely"):
                tracely.init()
            assert any("TRACELY_API_KEY" in msg for msg in caplog.messages)

    def test_init_without_api_key_disables_sdk(self):
        """AC3: Missing API key silently disables all instrumentation."""
        with patch.dict(os.environ, {}, clear=True):
            tracely.init()
            sdk = _sdk_instance()
            assert sdk is not None
            assert sdk.enabled is False

    def test_init_without_api_key_does_not_crash(self):
        """AC3: SDK must never crash the host application."""
        with patch.dict(os.environ, {}, clear=True):
            # This must complete without raising
            tracely.init()

    def test_init_with_service_name(self):
        """init() accepts explicit service_name parameter."""
        tracely.init(api_key="trly_abc123", service_name="my-api")
        sdk = _sdk_instance()
        assert sdk.config.service_name == "my-api"

    def test_init_with_service_version(self):
        """init() accepts explicit service_version parameter."""
        tracely.init(api_key="trly_abc123", service_version="1.2.3")
        sdk = _sdk_instance()
        assert sdk.config.service_version == "1.2.3"

    def test_service_name_defaults_to_none(self):
        """service_name defaults to None when not set."""
        tracely.init(api_key="trly_abc123")
        sdk = _sdk_instance()
        assert sdk.config.service_name is None

    def test_service_version_defaults_to_none(self):
        """service_version defaults to None when not set."""
        tracely.init(api_key="trly_abc123")
        sdk = _sdk_instance()
        assert sdk.config.service_version is None

    def test_init_idempotent(self):
        """Calling init() multiple times is safe."""
        with patch.dict(os.environ, {"TRACELY_API_KEY": "trly_abc123"}):
            tracely.init()
            tracely.init()
            sdk = _sdk_instance()
            assert sdk is not None

    def test_shutdown(self):
        """shutdown() gracefully stops the SDK."""
        with patch.dict(os.environ, {"TRACELY_API_KEY": "trly_abc123"}):
            tracely.init()
            tracely.shutdown()
            sdk = _sdk_instance()
            assert sdk is None
