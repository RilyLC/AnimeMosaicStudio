"""Buttons with semantic variants and palette-aware icons."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QPushButton, QSizePolicy

from .. import icons
from ..theme import Palette
from .base import repolish


class Button(QPushButton):
    def __init__(
        self,
        text: str = "",
        variant: str = "secondary",
        icon_name: str | None = None,
        palette: Palette | None = None,
        size: str = "md",
        parent=None,
    ):
        super().__init__(text, parent)
        self._palette = palette
        self._variant = variant
        self._icon_name = icon_name
        self._size = size
        self.setProperty("variant", variant)
        self.setProperty("size", size)
        self.setCursor(Qt.PointingHandCursor)
        if icon_name:
            self._refresh_icon()
        if size == "lg":
            self.setMinimumHeight(42)
        elif size == "sm":
            self.setMinimumHeight(28)
        else:
            self.setMinimumHeight(36)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)

    @property
    def variant(self) -> str:
        return self._variant

    def set_variant(self, variant: str) -> None:
        self._variant = variant
        self.setProperty("variant", variant)
        self._refresh_icon()
        repolish(self)

    def set_palette(self, palette: Palette) -> None:
        self._palette = palette
        self._refresh_icon()

    def set_icon_name(self, name: str | None) -> None:
        self._icon_name = name
        self._refresh_icon()

    def _icon_color(self) -> str:
        palette = self._palette
        if palette is None:
            return "#ffffff" if self._variant == "primary" else "#94a3b8"
        if self._variant == "primary":
            return palette.on_accent
        if self._variant == "danger":
            return palette.danger
        if self._variant == "link":
            return palette.accent
        if self._variant == "ghost":
            return palette.muted
        return palette.text

    def _refresh_icon(self) -> None:
        if not self._icon_name:
            self.setIcon(QIcon())
            return
        size = 18 if self._size == "lg" else 16
        self.setIcon(icons.icon(self._icon_name, self._icon_color(), size))
        self.setIconSize(QSize(size, size))


class IconButton(QPushButton):
    def __init__(
        self,
        icon_name: str,
        tooltip: str = "",
        palette: Palette | None = None,
        size: int = 34,
        icon_size: int = 18,
        parent=None,
    ):
        super().__init__(parent)
        self.setObjectName("IconButton")
        self._palette = palette
        self._icon_name = icon_name
        self._icon_size = icon_size
        self.setFixedSize(size, size)
        self.setToolTip(tooltip)
        self.setCursor(Qt.PointingHandCursor)
        self._refresh()

    def set_palette(self, palette: Palette) -> None:
        self._palette = palette
        self._refresh()

    def set_icon_name(self, name: str) -> None:
        self._icon_name = name
        self._refresh()

    def _refresh(self) -> None:
        color = self._palette.muted if self._palette else "#94a3b8"
        self.setIcon(icons.icon(self._icon_name, color, self._icon_size))
        self.setIconSize(QSize(self._icon_size, self._icon_size))
