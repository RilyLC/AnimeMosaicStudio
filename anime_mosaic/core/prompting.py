"""Prompt helpers shared by the pipeline and the prompt page."""

from __future__ import annotations

from .settings import NSFW_PROMPT_CLASSES, Settings

NSFW_LABELS = {
    "pussy": "小穴",
    "anus": "肛门",
    "penis": "阴茎",
    "testicles": "睾丸",
}


def split_prompt(value: str) -> list[str]:
    """Split a comma separated prompt and drop empty/duplicate fragments."""
    seen: set[str] = set()
    parts: list[str] = []
    for raw in value.replace("\n", ",").split(","):
        item = raw.strip()
        key = item.casefold()
        if item and key not in seen:
            seen.add(key)
            parts.append(item)
    return parts


def join_prompt(parts: list[str]) -> str:
    return ", ".join(part for part in parts if part.strip())


def detected_nsfw_classes(nsfw_text: str) -> list[str]:
    """Map a free-form detector string onto the four fixed model classes."""
    text = nsfw_text.casefold()
    found: list[str] = []
    for name in NSFW_PROMPT_CLASSES:
        if name in text:
            found.append(name)
    return found


def append_nsfw_prompts(positive: str, nsfw_text: str, settings: Settings) -> str:
    """Append the enabled, currently detected NSFW class prompts.

    The four classes are fixed because the bundled NSFW detector emits exactly
    these labels.  Each class still has its own editable prompt text.
    """
    if not settings.nsfw_prompt_enabled:
        return positive
    parts = split_prompt(positive)
    existing = {part.casefold() for part in parts}
    for name in detected_nsfw_classes(nsfw_text):
        text = str(getattr(settings, f"nsfw_prompt_{name}", "")).strip()
        if text and text.casefold() not in existing:
            parts.append(text)
            existing.add(text.casefold())
    return join_prompt(parts)
