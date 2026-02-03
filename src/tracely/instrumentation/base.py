"""Base instrumentor interface for framework auto-instrumentation."""

from __future__ import annotations

from abc import ABC, abstractmethod

from tracely.detection import FrameworkInfo


class BaseInstrumentor(ABC):
    """Abstract base class for framework-specific instrumentors.

    Subclasses implement activate() to install hooks/middleware and
    deactivate() to remove them on shutdown.
    """

    def __init__(self, framework_info: FrameworkInfo) -> None:
        self._framework_info = framework_info

    @property
    def framework_info(self) -> FrameworkInfo:
        return self._framework_info

    @abstractmethod
    def activate(self) -> None:
        """Install instrumentation hooks for the detected framework."""

    @abstractmethod
    def deactivate(self) -> None:
        """Remove instrumentation hooks (cleanup on shutdown)."""
