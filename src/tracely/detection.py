"""Framework auto-detection for the TRACELY SDK.

Detects installed web frameworks (FastAPI, Django, Flask) and database
libraries (SQLAlchemy, pymongo) using importlib.util.find_spec() — a
non-importing check that avoids side effects.

Detection priority: FastAPI > Django > Flask.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from importlib.util import find_spec

logger = logging.getLogger("tracely")

DETECTION_ORDER = ("fastapi", "django", "flask")


@dataclass
class FrameworkInfo:
    """Detected framework and companion libraries."""

    name: str
    has_sqlalchemy: bool = False
    has_pymongo: bool = False


def detect_framework() -> FrameworkInfo | None:
    """Detect installed web framework and database libraries.

    Returns FrameworkInfo for the highest-priority detected framework,
    or None if no supported framework is found.

    Never raises — all exceptions are caught silently (FR10).
    """
    try:
        for framework_name in DETECTION_ORDER:
            if find_spec(framework_name) is not None:
                return FrameworkInfo(
                    name=framework_name,
                    has_sqlalchemy=find_spec("sqlalchemy") is not None,
                    has_pymongo=find_spec("pymongo") is not None,
                )
        return None
    except Exception:
        logger.debug("TRACELY framework detection failed", exc_info=True)
        return None
