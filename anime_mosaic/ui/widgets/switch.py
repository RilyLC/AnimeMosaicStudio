"""An animated iOS-style toggle switch."""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QRectF, Qt, Property
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QAbstractButton

from ..theme import Palette


class Switch(QAbstractButton):
    def __init__(self, checked: bool = False, palette: Palette | None = None, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.PointingHandCursor)
        self._palette = palette
        self._position = 1.0 if checked else 0.0
        self._animation = QPropertyAnimation(self, b"position", self)
        self._animation.setDuration(160)
        self._animation.setEasingCurve(QEasingCurve.OutCubic)
        self.toggled.connect(self._animate)
        self.setFixedSize(40, 22)

    def set_palette(self, palette: Palette) -> None:
        self._palette = palette
        self.update()

    def get_position(self) -> float:
        return self._position

    def set_position(self, value: float) -> None:
        self._position = float(value)
        self.update()

    position = Property(float, get_position, set_position)

    def _animate(self, checked: bool) -> None:
        self._animation.stop()
        self._animation.setStartValue(self._position)
        self._animation.setEndValue(1.0 if checked else 0.0)
        self._animation.start()

    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        palette = self._palette
        track_off = QColor(palette.surface_3) if palette else QColor("#334155")
        track_on = QColor(palette.accent) if palette else QColor("#6d8dff")
        track = QColor(
            int(track_off.red() + (track_on.red() - track_off.red()) * self._position),
            int(track_off.green() + (track_on.green() - track_off.green()) * self._position),
            int(track_off.blue() + (track_on.blue() - track_off.blue()) * self._position),
        )
        painter.setPen(Qt.NoPen)
        painter.setBrush(track)
        painter.drawRoundedRect(QRectF(0, 0, 40, 22), 11, 11)

        knob_color = QColor("#FFFFFF")
        knob_x = 3 + self._position * (40 - 22 + 3 - 3)
        painter.setBrush(knob_color)
        painter.drawEllipse(QRectF(knob_x, 3, 16, 16))
        painter.end()
