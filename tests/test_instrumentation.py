"""Tests for base instrumentation infrastructure (Story 2.2, Task 2)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from tracely.detection import FrameworkInfo
from tracely.instrumentation.base import BaseInstrumentor
from tracely.instrumentation import get_instrumentor


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


class TestGetInstrumentor:
    """Test the instrumentor factory/registry."""

    def test_returns_fastapi_instrumentor(self) -> None:
        info = FrameworkInfo(name="fastapi")
        inst = get_instrumentor(info)
        assert inst is not None
        assert inst.framework_info.name == "fastapi"

    def test_returns_django_instrumentor(self) -> None:
        info = FrameworkInfo(name="django")
        inst = get_instrumentor(info)
        assert inst is not None
        assert inst.framework_info.name == "django"

    def test_returns_flask_instrumentor(self) -> None:
        info = FrameworkInfo(name="flask")
        inst = get_instrumentor(info)
        assert inst is not None
        assert inst.framework_info.name == "flask"

    def test_returns_none_for_unknown_framework(self) -> None:
        info = FrameworkInfo(name="tornado")
        inst = get_instrumentor(info)
        assert inst is None


class TestInitIntegration:
    """Test that init() triggers detection and instrumentation."""

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

    def test_init_activates_instrumentor(self) -> None:
        """init() activates the instrumentor for the detected framework."""
        with (
            patch("tracely.sdk.detect_framework") as mock_detect,
            patch("tracely.sdk.get_instrumentor") as mock_get,
        ):
            mock_detect.return_value = FrameworkInfo(name="fastapi")
            mock_inst = _StubInstrumentor(FrameworkInfo(name="fastapi"))
            mock_get.return_value = mock_inst
            from tracely.sdk import init
            init(api_key="test-key")
            assert mock_inst.activated is True

    def test_shutdown_deactivates_instrumentor(self) -> None:
        """shutdown() deactivates the instrumentor."""
        with (
            patch("tracely.sdk.detect_framework") as mock_detect,
            patch("tracely.sdk.get_instrumentor") as mock_get,
        ):
            mock_detect.return_value = FrameworkInfo(name="fastapi")
            mock_inst = _StubInstrumentor(FrameworkInfo(name="fastapi"))
            mock_get.return_value = mock_inst
            from tracely.sdk import init, shutdown
            init(api_key="test-key")
            shutdown()
            assert mock_inst.deactivated is True

    def test_init_disabled_skips_instrumentation(self) -> None:
        """When SDK is disabled (no API key), detection still runs but no instrumentation."""
        with patch("tracely.sdk.detect_framework") as mock_detect:
            mock_detect.return_value = FrameworkInfo(name="fastapi")
            from tracely.sdk import init, _sdk_instance
            init()  # no api_key → disabled
            instance = _sdk_instance()
            assert instance is not None
            assert instance.instrumentor is None
