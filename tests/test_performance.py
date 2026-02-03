"""Performance tests for SDK initialization (AC2)."""

from __future__ import annotations

import os
import time
from unittest.mock import patch

from tracely.sdk import _reset


def test_init_completes_under_50ms():
    """AC2: Initialization completes in < 50ms."""
    import tracely

    _reset()

    with patch.dict(os.environ, {"TRACELY_API_KEY": "trly_abc123"}):
        start = time.perf_counter()
        tracely.init()
        elapsed_ms = (time.perf_counter() - start) * 1000

    _reset()

    assert elapsed_ms < 50, f"init() took {elapsed_ms:.1f}ms, expected < 50ms"


def test_init_without_key_also_fast():
    """Disabled init path is also fast."""
    import tracely

    _reset()

    with patch.dict(os.environ, {}, clear=True):
        start = time.perf_counter()
        tracely.init()
        elapsed_ms = (time.perf_counter() - start) * 1000

    _reset()

    assert elapsed_ms < 50, f"init() took {elapsed_ms:.1f}ms, expected < 50ms"
