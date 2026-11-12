"""Scrollable page container with consistent spacing."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QScrollArea, QVBoxLayout, QWidget


class Page(QScrollArea):
    def __init__(self, spacing: int = 18, margins: tuple[int, int, int, int] = (0, 0, 8, 0), parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setObjectName("PageScroll")

        self._body = QWidget()
        self._body.setObjectName("ScrollBody")
        self._layout = QVBoxLayout(self._body)
        self._layout.setContentsMargins(*margins)
        self._layout.setSpacing(spacing)
        self._layout.setAlignment(Qt.AlignTop)
        self._layout.addStretch(1)
        self.setWidget(self._body)

    def add(self, widget: QWidget, stretch: int = 0) -> QWidget:
        self._layout.insertWidget(self._layout.count() - 1, widget, stretch)
        return widget

    def add_layout(self, layout, stretch: int = 0):
        self._layout.insertLayout(self._layout.count() - 1, layout, stretch)
        return layout

    @property
    def body_layout(self) -> QVBoxLayout:
        return self._layout
