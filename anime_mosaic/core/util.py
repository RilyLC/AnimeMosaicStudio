"""Small formatting helpers with no third-party dependencies."""

from __future__ import annotations

import os
import re


def human_time(seconds: float) -> str:
    """``92`` -> ``1m32s``; ``3720`` -> ``1h02m``."""
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h{minutes:02d}m"
    if minutes:
        return f"{minutes}m{secs:02d}s"
    return f"{secs}s"


def human_duration_short(seconds: float) -> str:
    """Compact estimate used on cards: ``45s`` / ``2m 10s`` / ``1h 05m``."""
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


def plural(count: int, singular: str, plural_form: str | None = None) -> str:
    return f"{count} {singular if count == 1 else (plural_form or singular + 's')}"


def safe_name(value: str, fallback: str = "output") -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", (value or "").strip())
    return cleaned or fallback


def shorten_path(path: str, limit: int = 58) -> str:
    """Middle-ellipsis a long Windows path for narrow labels."""
    if not path or len(path) <= limit:
        return path
    head, tail = os.path.split(path)
    if len(tail) >= limit - 6:
        return "…" + tail[-(limit - 1):]
    room = limit - len(tail) - 6
    return f"{head[:room]}…\\{tail}" if room > 0 else "…" + tail
