"""Tests for framework auto-detection (Story 2.2, Task 1)."""

from __future__ import annotations

import importlib
from unittest.mock import patch

import pytest

from tracely.detection import FrameworkInfo, detect_framework


class TestDetectFramework:
    """Test detect_framework() identifies installed frameworks."""

    def test_detects_fastapi_when_installed(self) -> None:
        """FastAPI detected via importlib.util.find_spec."""
        with patch("tracely.detection.find_spec") as mock_find:
            mock_find.side_effect = lambda name: (
                True if name == "fastapi" else None
            )
            result = detect_framework()
        assert result is not None
        assert result.name == "fastapi"

    def test_detects_django_when_installed(self) -> None:
        """Django detected via importlib.util.find_spec."""
        with patch("tracely.detection.find_spec") as mock_find:
            mock_find.side_effect = lambda name: (
                True if name == "django" else None
            )
            result = detect_framework()
        assert result is not None
        assert result.name == "django"

    def test_detects_flask_when_installed(self) -> None:
        """Flask detected via importlib.util.find_spec."""
        with patch("tracely.detection.find_spec") as mock_find:
            mock_find.side_effect = lambda name: (
                True if name == "flask" else None
            )
            result = detect_framework()
        assert result is not None
        assert result.name == "flask"

    def test_returns_none_when_no_framework(self) -> None:
        """No framework detected returns None."""
        with patch("tracely.detection.find_spec", return_value=None):
            result = detect_framework()
        assert result is None

    def test_priority_fastapi_over_django(self) -> None:
        """FastAPI takes priority when both FastAPI and Django are installed."""
        with patch("tracely.detection.find_spec") as mock_find:
            mock_find.side_effect = lambda name: (
                True if name in ("fastapi", "django") else None
            )
            result = detect_framework()
        assert result is not None
        assert result.name == "fastapi"

    def test_priority_fastapi_over_flask(self) -> None:
        """FastAPI takes priority when both FastAPI and Flask are installed."""
        with patch("tracely.detection.find_spec") as mock_find:
            mock_find.side_effect = lambda name: (
                True if name in ("fastapi", "flask") else None
            )
            result = detect_framework()
        assert result is not None
        assert result.name == "fastapi"

    def test_priority_django_over_flask(self) -> None:
        """Django takes priority when both Django and Flask are installed."""
        with patch("tracely.detection.find_spec") as mock_find:
            mock_find.side_effect = lambda name: (
                True if name in ("django", "flask") else None
            )
            result = detect_framework()
        assert result is not None
        assert result.name == "django"


class TestDetectDatabaseLibraries:
    """Test database library detection in FrameworkInfo."""

    def test_detects_sqlalchemy(self) -> None:
        """SQLAlchemy detected when installed."""
        with patch("tracely.detection.find_spec") as mock_find:
            mock_find.side_effect = lambda name: (
                True if name in ("fastapi", "sqlalchemy") else None
            )
            result = detect_framework()
        assert result is not None
        assert result.has_sqlalchemy is True

    def test_detects_pymongo(self) -> None:
        """pymongo detected when installed."""
        with patch("tracely.detection.find_spec") as mock_find:
            mock_find.side_effect = lambda name: (
                True if name in ("fastapi", "pymongo") else None
            )
            result = detect_framework()
        assert result is not None
        assert result.has_pymongo is True

    def test_no_db_libraries(self) -> None:
        """No DB libraries detected."""
        with patch("tracely.detection.find_spec") as mock_find:
            mock_find.side_effect = lambda name: (
                True if name == "fastapi" else None
            )
            result = detect_framework()
        assert result is not None
        assert result.has_sqlalchemy is False
        assert result.has_pymongo is False

    def test_detection_never_raises(self) -> None:
        """Detection catches all exceptions — SDK never crashes host app."""
        with patch(
            "tracely.detection.find_spec",
            side_effect=Exception("boom"),
        ):
            result = detect_framework()
        assert result is None


class TestFrameworkInfo:
    """Test FrameworkInfo data class."""

    def test_framework_info_fields(self) -> None:
        info = FrameworkInfo(
            name="fastapi",
            has_sqlalchemy=True,
            has_pymongo=False,
        )
        assert info.name == "fastapi"
        assert info.has_sqlalchemy is True
        assert info.has_pymongo is False

    def test_framework_info_defaults(self) -> None:
        info = FrameworkInfo(name="flask")
        assert info.has_sqlalchemy is False
        assert info.has_pymongo is False
