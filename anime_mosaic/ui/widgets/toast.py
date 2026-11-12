"""Floating, auto-dismissing notifications."""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QTimer, Qt
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QWidget,
)

from .. import icons
from ..theme import Palette


class Toast(QFrame):
    def __init__(self, message: str, tone: str, palette: Palette, parent=None):
        super().__init__(parent)
        self.setObjectName("Toast")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedWidth(350)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)

        icon_name = {
            "success": "check_circle",
            "error": "alert_circle",
            "warning": "alert",
            "info": "info",
        }.get(tone, "info")
        color = {
            "success": palette.success,
            "error": palette.danger,
            "warning": palette.warning,
            "info": palette.info,
        }.get(tone, palette.muted)
        icon_label = QLabel()
        icon_label.setPixmap(icons.pixmap(icon_name, color, 18))
        icon_label.setAlignment(Qt.AlignTop)
        layout.addWidget(icon_label, 0, Qt.AlignTop)

        text = QLabel(message)
        text.setWordWrap(True)
        text.setObjectName("FormLabel")
        layout.addWidget(text, 1)

        self._effect = QGraphicsOpacityEffect(self)
        self._effect.setOpacity(0.0)
        self.setGraphicsEffect(self._effect)
        self._fade = QPropertyAnimation(self._effect, b"opacity", self)
        self._fade.setDuration(180)
        self._fade.setEasingCurve(QEasingCurve.OutCubic)

    def fade_in(self) -> None:
        self._fade.stop()
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._fade.start()

    def fade_out(self, on_done) -> None:
        self._fade.stop()
        self._fade.setStartValue(self._effect.opacity())
        self._fade.setEndValue(0.0)
        self._fade.finished.connect(on_done)
        self._fade.start()

    def mousePressEvent(self, event):  # noqa: N802
        self.hide()


class ToastManager:
    """Owns toasts and keeps them stacked in the top-right corner."""

    def __init__(self, host: QWidget, palette: Palette):
        self._host = host
        self._palette = palette
        self._toasts: list[Toast] = []

    def set_palette(self, palette: Palette) -> None:
        self._palette = palette

    def show(self, message: str, tone: str = "info", timeout: int = 3800) -> None:
        toast = Toast(message, tone, self._palette, self._host)
        toast.adjustSize()
        self._toasts.append(toast)
        toast.fade_in()
        toast.show()
        toast.raise_()
        self._relayout()
        QTimer.singleShot(timeout, lambda: self._dismiss(toast))

    def _dismiss(self, toast: Toast) -> None:
        if toast not in self._toasts:
            return

        def finish() -> None:
            if toast in self._toasts:
                self._toasts.remove(toast)
            toast.deleteLater()
            self._relayout()

        toast.fade_out(finish)

    def _relayout(self) -> None:
        width = self._host.width()
        y = 78
        for toast in reversed(self._toasts):
            toast.adjustSize()
            toast.move(max(12, width - toast.width() - 26), y)
            y += toast.height() + 10

    def reposition(self) -> None:
        self._relayout()
