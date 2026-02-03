"""Generic fallback instrumentation when no framework is detected.

Provides basic Python process instrumentation and logs guidance
about manual instrumentation options.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("tracely")


class GenericInstrumentor:
    """Fallback instrumentor for non-framework Python applications.

    Logs an info message about manual instrumentation when activated.
    Does not require BaseInstrumentor inheritance since it is used
    outside the framework detection flow.
    """

    def __init__(self) -> None:
        self._active = False

    def activate(self) -> None:
        self._active = True
        logger.info(
            "TRACELY: No supported framework detected. "
            "For manual instrumentation, use tracely.create_span() "
            "to instrument your application code."
        )

    def deactivate(self) -> None:
        self._active = False

    @property
    def is_active(self) -> bool:
        return self._active
