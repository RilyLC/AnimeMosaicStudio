"""Compact preset switcher shown in the bottom action bar."""

from __future__ import annotations

from PySide6.QtCore import QPoint, Signal
from PySide6.QtWidgets import QMenu

from ...services.presets import (
    CUSTOM_PRESET,
    CUSTOM_PRESET_ID,
    PRESET_CHOICES,
    preset_by_id,
)
from ..theme import Palette
from .buttons import Button


class PresetPicker(Button):
    """A small dropdown button that always shows the active preset."""

    changed = Signal(str)
    restoreRequested = Signal(str)

    def __init__(self, palette: Palette, parent=None):
        super().__init__(
            "预设: 均衡  ▾",
            "secondary",
            "sliders",
            palette,
            size="md",
            parent=parent,
        )
        self.setMinimumWidth(148)
        self._current = "balanced"
        self._menu = QMenu(self)
        self._actions = {}
        for preset in PRESET_CHOICES:
            if preset.id == CUSTOM_PRESET_ID:
                self._menu.addSeparator()
            action = self._menu.addAction(f"{preset.label}  ·  {preset.tagline}")
            action.setCheckable(True)
            action.setData(preset.id)
            action.triggered.connect(
                lambda _checked=False, preset_id=preset.id: self._choose(preset_id)
            )
            self._actions[preset.id] = action
        self._menu.addSeparator()
        self._restore_action = self._menu.addAction("恢复当前预设默认值")
        self._restore_action.triggered.connect(self._restore_current)
        self.clicked.connect(self._show_menu)
        self.set_current("balanced")

    def current_id(self) -> str:
        return self._current

    def set_current(self, preset_id: str) -> None:
        preset = preset_by_id(preset_id) or CUSTOM_PRESET
        self._current = preset.id
        self.setText(f"预设: {preset.label}  ▾")
        self.setToolTip(f"参数预设：{preset.label}\n{preset.description}")
        for key, action in self._actions.items():
            action.setChecked(key == preset.id)
        self._restore_action.setEnabled(preset.id != CUSTOM_PRESET_ID)

    def _restore_current(self) -> None:
        if self._current != CUSTOM_PRESET_ID:
            self.restoreRequested.emit(self._current)

    def _show_menu(self) -> None:
        self._menu.ensurePolished()
        size = self._menu.sizeHint()
        self._menu.popup(
            self.mapToGlobal(QPoint(0, -size.height() - 6))
        )

    def _choose(self, preset_id: str) -> None:
        if preset_id == self._current:
            return
        self.set_current(preset_id)
        self.changed.emit(preset_id)
