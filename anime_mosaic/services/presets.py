"""Quality presets: one-click starting points without hiding any setting.

Each of the four presets keeps the whole tuning page (detection, crop, sampling
and blend).  A built-in preset's *factory* values are the ``Settings`` defaults
overridden by the numbers below; edits made while that preset is active are
stored as overrides in :attr:`Settings.preset_values`, so switching presets
never throws away work and switching back restores what was there.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..core.settings import PRESET_VALUE_KEYS, Settings

__all__ = [
    "CUSTOM_PRESET",
    "CUSTOM_PRESET_ID",
    "PRESETS",
    "PRESET_CHOICES",
    "PRESET_VALUE_KEYS",
    "Preset",
    "active_preset_id",
    "factory_values",
    "preset_by_id",
    "preset_values",
    "remember_preset_values",
    "resolve_preset_id",
    "restore_preset_defaults",
]


@dataclass(frozen=True)
class Preset:
    id: str
    label: str
    tagline: str
    description: str
    values: dict

    def apply(self, settings: Settings) -> Settings:
        return settings.merged(preset=self.id, **preset_values(settings, self.id))


PRESETS: tuple[Preset, ...] = (
    Preset(
        id="fast",
        label="快速",
        tagline="先看效果",
        description="更小的重绘尺寸与步数，适合批量试跑。",
        values={
            "size": 768,
            "steps": 12,
            "cfg": 2.5,
            "denoise": 0.85,
            "grow": 6,
        },
    ),
    Preset(
        id="balanced",
        label="均衡",
        tagline="推荐",
        description="默认参数，画质、显存与速度的平衡点。",
        values={
            "size": 1024,
            "steps": 25,
            "cfg": 3.0,
            "denoise": 1.0,
            "grow": 8,
        },
    ),
    Preset(
        id="quality",
        label="精细",
        tagline="最终成品",
        description="更大的尺寸与步数，适合少量精修。",
        values={
            "size": 1280,
            "steps": 32,
            "cfg": 3.5,
            "denoise": 1.0,
            "grow": 10,
        },
    ),
)

CUSTOM_PRESET_ID = "custom"

CUSTOM_PRESET = Preset(
    id=CUSTOM_PRESET_ID,
    label="自定义",
    tagline="手动",
    description="手动参数，和其余预设一样独立保存。",
    values={},
)

PRESET_CHOICES: tuple[Preset, ...] = (*PRESETS, CUSTOM_PRESET)


def preset_by_id(preset_id: str) -> Preset | None:
    for preset in PRESET_CHOICES:
        if preset.id == preset_id:
            return preset
    return None


def factory_values(preset_id: str) -> dict:
    """The full-page factory values for a preset.

    The tuning page is saved as one unit: its defaults come from ``Settings``,
    and a built-in preset only overrides the numbers in ``Preset.values``.
    The custom slot has no factory values -- it starts empty and keeps whatever
    the user saves there.
    """
    preset = preset_by_id(preset_id)
    if preset is None or preset_id == CUSTOM_PRESET_ID:
        return {}
    defaults = Settings()
    return {**{key: getattr(defaults, key) for key in PRESET_VALUE_KEYS}, **preset.values}


def preset_values(settings: Settings, preset_id: str) -> dict:
    """Factory values for ``preset_id`` with that preset's saved edits applied."""
    return {**factory_values(preset_id), **settings.preset_values.get(preset_id, {})}


def remember_preset_values(settings: Settings, preset_id: str | None = None) -> Settings:
    """Snapshot preset-owned values into the active preset's saved overrides.

    Values that still match a built-in preset's factory defaults are not
    stored, so ``restore_preset_defaults`` only has to drop the entry.
    """
    preset_id = settings.preset if preset_id is None else preset_id
    factory = factory_values(preset_id)
    slots = {key: dict(value) for key, value in settings.preset_values.items()}
    entry = slots.setdefault(preset_id, {})
    for key in PRESET_VALUE_KEYS:
        value = getattr(settings, key)
        if key in factory and value == factory[key]:
            entry.pop(key, None)
        else:
            entry[key] = value
    if entry:
        slots[preset_id] = entry
    else:
        slots.pop(preset_id, None)
    return settings.merged(preset_values=slots)


def restore_preset_defaults(settings: Settings, preset_id: str) -> Settings:
    """Drop one preset's saved edits; apply its full factory page if it is active."""
    preset = preset_by_id(preset_id)
    if preset is None or preset_id == CUSTOM_PRESET_ID:
        return settings
    slots = {
        key: dict(value)
        for key, value in settings.preset_values.items()
        if key != preset_id
    }
    cleared = settings.merged(preset_values=slots)
    if settings.preset != preset_id:
        return cleared
    return cleared.merged(preset=preset_id, **factory_values(preset_id))


def resolve_preset_id(settings: Settings) -> str:
    """The preset the UI should highlight: the explicit choice if it is valid."""
    return settings.preset if preset_by_id(settings.preset) is not None else CUSTOM_PRESET_ID


def active_preset_id(settings: Settings) -> str:
    """Value-based fallback kept for callers/tests that ignore explicit choice."""
    for preset in PRESETS:
        values = preset_values(settings, preset.id)
        if all(getattr(settings, key) == value for key, value in values.items()):
            return preset.id
    return CUSTOM_PRESET_ID
