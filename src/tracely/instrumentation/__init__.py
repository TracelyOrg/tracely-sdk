"""Instrumentor registry and factory."""

from __future__ import annotations

import logging

from tracely.detection import FrameworkInfo
from tracely.instrumentation.base import BaseInstrumentor

logger = logging.getLogger("tracely")

# Lazy-loaded instrumentor classes keyed by framework name.
_REGISTRY: dict[str, str] = {
    "fastapi": "tracely.instrumentation.fastapi_inst.FastAPIInstrumentor",
    "django": "tracely.instrumentation.django_inst.DjangoInstrumentor",
    "flask": "tracely.instrumentation.flask_inst.FlaskInstrumentor",
}


def get_instrumentor(framework_info: FrameworkInfo) -> BaseInstrumentor | None:
    """Return the instrumentor for the given framework, or None if unknown.

    Uses lazy import to avoid pulling in framework-specific code until needed.
    Never raises — returns None on any failure.
    """
    qualname = _REGISTRY.get(framework_info.name)
    if qualname is None:
        logger.debug("No instrumentor registered for %s", framework_info.name)
        return None

    try:
        module_path, class_name = qualname.rsplit(".", 1)
        import importlib

        module = importlib.import_module(module_path)
        cls = getattr(module, class_name)
        return cls(framework_info)
    except Exception:
        logger.debug(
            "Failed to load instrumentor for %s",
            framework_info.name,
            exc_info=True,
        )
        return None


__all__ = ["BaseInstrumentor", "get_instrumentor"]
