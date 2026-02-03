"""Tests for generic fallback instrumentation (Story 2.2, Task 7)."""

from __future__ import annotations

import logging
from unittest.mock import patch

import pytest

from tracely.instrumentation.generic import GenericInstrumentor


class TestGenericInstrumentor:
    """Test the generic fallback when no framework is detected."""

    def test_activate_logs_info_message(self, caplog: pytest.LogCaptureFixture) -> None:
        """Activation logs an info message about manual instrumentation."""
        inst = GenericInstrumentor()
        with caplog.at_level(logging.INFO, logger="tracely"):
            inst.activate()
        assert any("manual instrumentation" in r.message.lower() for r in caplog.records)

    def test_deactivate_does_not_crash(self) -> None:
        inst = GenericInstrumentor()
        inst.activate()
        inst.deactivate()

    def test_is_active_flag(self) -> None:
        inst = GenericInstrumentor()
        assert inst.is_active is False
        inst.activate()
        assert inst.is_active is True
        inst.deactivate()
        assert inst.is_active is False

    def test_never_raises(self) -> None:
        """Generic instrumentor never crashes."""
        inst = GenericInstrumentor()
        inst.activate()
        inst.deactivate()
        # Double deactivate should be fine
        inst.deactivate()
