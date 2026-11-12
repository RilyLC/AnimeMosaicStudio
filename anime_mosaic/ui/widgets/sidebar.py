"""Left navigation rail with brand and page links."""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .. import icons
from ..branding import draw_logo
from ..theme import Palette
from .buttons import IconButton

NAV_ITEMS: tuple[tuple[str, str], ...] = (
    ("工作台", "home"),
    ("参数", "gauge"),
    ("提示词", "prompt"),
    ("设置", "settings"),
    ("运行日志", "logs"),
    ("关于", "info"),
)


class LogoMark(QWidget):
    def __init__(self, palette: Palette, size: int = 38, parent=None):
        super().__init__(parent)
        self._palette = palette
        self._size = size
        self.setFixedSize(size, size)

    def set_palette(self, palette: Palette) -> None:
        self._palette = palette
        self.update()

    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)
        draw_logo(painter, QRectF(0, 0, self._size, self._size), self._palette)
        painter.end()


class Sidebar(QFrame):
    navigate = Signal(int)
    themeToggled = Signal()

    WIDTH = 228

    def __init__(self, palette: Palette, parent=None):
        super().__init__(parent)
        self.setObjectName("Sidebar")
        self._palette = palette
        self.setFixedWidth(self.WIDTH)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 20, 16, 16)
        root.setSpacing(6)

        brand = QHBoxLayout()
        brand.setSpacing(11)
        self._logo = LogoMark(palette)
        brand.addWidget(self._logo, 0, Qt.AlignVCenter)
        brand_labels = QVBoxLayout()
        brand_labels.setSpacing(0)
        name = QLabel("AnimeMosaic")
        name.setObjectName("BrandName")
        sub = QLabel("STUDIO")
        sub.setObjectName("BrandSub")
        brand_labels.addWidget(name)
        brand_labels.addWidget(sub)
        brand.addLayout(brand_labels, 1)
        root.addLayout(brand)
        root.addSpacing(18)

        section = QLabel("工作区")
        section.setObjectName("NavSection")
        root.addWidget(section)
        root.addSpacing(2)

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: list[QPushButton] = []
        self._nav_icons: list[str] = []
        for index, (label, icon_name) in enumerate(NAV_ITEMS):
            button = QPushButton(label)
            button.setObjectName("NavButton")
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            button.setIconSize(QSize(18, 18))
            button.setFixedHeight(40)
            button.clicked.connect(lambda _checked=False, i=index: self.navigate.emit(i))
            self._group.addButton(button, index)
            self._buttons.append(button)
            self._nav_icons.append(icon_name)
            root.addWidget(button)
            if index == 3:
                root.addSpacing(6)
        self._group.idToggled.connect(lambda *_: self._refresh_nav_icons())

        root.addStretch(1)

        footer = QHBoxLayout()
        footer.setSpacing(6)
        self._theme_button = IconButton("moon", "切换深色 / 浅色主题", palette, size=32, icon_size=17)
        self._theme_button.clicked.connect(self.themeToggled)
        footer.addWidget(self._theme_button)
        version = QLabel("v0.1")
        version.setObjectName("Dim")
        footer.addWidget(version)
        footer.addStretch(1)
        root.addLayout(footer)

        self.set_active(0)

    # ------------------------------------------------------------------ api
    def set_active(self, index: int) -> None:
        if 0 <= index < len(self._buttons):
            self._buttons[index].setChecked(True)
            self._refresh_nav_icons()

    def set_theme_mode(self, mode: str) -> None:
        self._theme_button.set_icon_name("sun" if mode == "dark" else "moon")

    def apply_palette(self, palette: Palette) -> None:
        self._palette = palette
        self._logo.set_palette(palette)
        self._theme_button.set_palette(palette)
        self._refresh_nav_icons()

    def _refresh_nav_icons(self) -> None:
        for button, icon_name in zip(self._buttons, self._nav_icons):
            color = self._palette.accent if button.isChecked() else self._palette.muted
            button.setIcon(icons.icon(icon_name, color, 18))
