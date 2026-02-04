"""Tests for base instrumentation infrastructure (Story 2.2, Task 2)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from tracely.detection import FrameworkInfo
from tracely.instrumentation.base import BaseInstrumentor


class _StubInstrumentor(BaseInstrumentor):
    """Concrete stub for testing the ABC."""

    activated = False
    deactivated = False

    def activate(self) -> None:
        self.activated = True

    def deactivate(self) -> None:
        self.deactivated = True


class TestBaseInstrumentor:
    """Test the BaseInstrumentor ABC contract."""

    def test_cannot_instantiate_abc(self) -> None:
        with pytest.raises(TypeError):
            BaseInstrumentor(FrameworkInfo(name="fastapi"))  # type: ignore[abstract]

    def test_concrete_subclass_instantiates(self) -> None:
        info = FrameworkInfo(name="fastapi")
        inst = _StubInstrumentor(info)
        assert inst.framework_info is info

    def test_activate_called(self) -> None:
        inst = _StubInstrumentor(FrameworkInfo(name="fastapi"))
        inst.activate()
        assert inst.activated is True

    def test_deactivate_called(self) -> None:
        inst = _StubInstrumentor(FrameworkInfo(name="flask"))
        inst.deactivate()
        assert inst.deactivated is True


class TestInitIntegration:
    """Test that init() triggers detection."""

    def setup_method(self) -> None:
        from tracely.sdk import _reset
        _reset()

    def teardown_method(self) -> None:
        from tracely.sdk import _reset
        _reset()

    def test_init_detects_and_stores_framework(self) -> None:
        """init() runs detection and stores the framework info on the SDK instance."""
        with patch("tracely.sdk.detect_framework") as mock_detect:
            mock_detect.return_value = FrameworkInfo(name="fastapi")
            from tracely.sdk import init, _sdk_instance
            init(api_key="test-key")
            instance = _sdk_instance()
            assert instance is not None
            assert instance.framework_info is not None
            assert instance.framework_info.name == "fastapi"

    def test_init_no_framework_detected(self) -> None:
        """init() stores None framework_info when no framework found."""
        with patch("tracely.sdk.detect_framework", return_value=None):
            from tracely.sdk import init, _sdk_instance
            init(api_key="test-key")
            instance = _sdk_instance()
            assert instance is not None
            assert instance.framework_info is None

    def test_init_no_longer_auto_activates_instrumentor(self) -> None:
        """init() no longer auto-activates instrumentors; instrumentation is explicit."""
        with patch("tracely.sdk.detect_framework") as mock_detect:
            mock_detect.return_value = FrameworkInfo(name="fastapi")
            from tracely.sdk import init, _sdk_instance
            init(api_key="test-key")
            instance = _sdk_instance()
            assert instance is not None
            # No instrumentor attribute -- instrumentation is now explicit
            assert not hasattr(instance, "instrumentor")
