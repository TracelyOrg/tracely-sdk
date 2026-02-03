"""TRACELY SDK - Lightweight observability for Python web frameworks."""

from __future__ import annotations

try:
    from tracely._version import __version__
except ImportError:
    __version__ = "0.0.0-dev"

from tracely.sdk import init, shutdown
from tracely.tracing import span
from tracely.logging_api import debug, info, warning, error

__all__ = ["init", "shutdown", "span", "debug", "info", "warning", "error", "__version__"]
