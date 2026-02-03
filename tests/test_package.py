"""Tests for SDK package structure and imports (AC1)."""

from __future__ import annotations


def test_import_tracely():
    """Package is importable via `import tracely`."""
    import tracely

    assert tracely is not None


def test_version_available():
    """Package exposes __version__."""
    import tracely

    assert hasattr(tracely, "__version__")
    assert isinstance(tracely.__version__, str)
    assert tracely.__version__ == "0.1.0"


def test_init_exported():
    """tracely.init() is available as a public API."""
    import tracely

    assert hasattr(tracely, "init")
    assert callable(tracely.init)


def test_shutdown_exported():
    """tracely.shutdown() is available as a public API."""
    import tracely

    assert hasattr(tracely, "shutdown")
    assert callable(tracely.shutdown)
