"""Framework instrumentation modules.

Users instrument their applications by calling the top-level helpers:
    tracely.instrument_fastapi(app)
    tracely.instrument_flask(app)
    tracely.instrument_django()

The individual middleware classes (TracelyASGIMiddleware, etc.) remain
available for advanced usage.
"""

from __future__ import annotations

from tracely.instrumentation.base import BaseInstrumentor

__all__ = ["BaseInstrumentor"]
