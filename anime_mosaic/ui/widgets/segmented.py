"""Compact segmented control used for tabs inside cards."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QButtonGroup, QFrame, QHBoxLayout, QPushButton, QSizePolicy

from ..theme import Palette


class SegmentedControl(QFrame):
    currentChanged = Signal(int)

    def __init__(self, items: list[str], palette: Palette | None = None, parent=None):
        super().__init__(parent)
        self.setObjectName("Segment")
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self._palette = palette
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: list[QPushButton] = []
        layout = QHBoxLayout(self)
        layout.setContentsMargins(3, 3, 3, 3)
        layout.setSpacing(2)
        for index, text in enumerate(items):
            button = QPushButton(text)
            button.setObjectName("SegmentButton")
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            button.setMinimumHeight(30)
            button.clicked.connect(lambda _checked=False, i=index: self._select(i))
            self._group.addButton(button, index)
            self._buttons.append(button)
            layout.addWidget(button)
        if self._buttons:
            self._buttons[0].setChecked(True)

    def set_current(self, index: int) -> None:
        if 0 <= index < len(self._buttons):
            button = self._buttons[index]
            if button.isChecked():
                return
            button.setChecked(True)
            self.currentChanged.emit(index)

    def current_index(self) -> int:
        for index, button in enumerate(self._buttons):
            if button.isChecked():
                return index
        return 0

    def set_text(self, index: int, text: str) -> None:
        if 0 <= index < len(self._buttons):
            button = self._buttons[index]
            button.setText(text)
            button.setMinimumWidth(button.sizeHint().width())
            self.adjustSize()
            self.updateGeometry()

    def _select(self, index: int) -> None:
        self.currentChanged.emit(index)
