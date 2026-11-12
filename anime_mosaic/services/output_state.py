"""Path helpers shared by everything that stores per-output state.

Only relative paths are used, with forward slashes on every platform, so keys
stay portable between Windows and POSIX checkouts.
"""

from __future__ import annotations

import os


def state_key(rel: str) -> str:
    """Normalise a relative path to a forward-slash key."""
    if not rel:
        return ""
    return os.path.normpath(rel).replace("\\", "/")
