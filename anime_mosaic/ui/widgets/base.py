"""Reusable presentation primitives: cards, badges, stats and status dots."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .. import icons
from ..theme import Palette


def repolish(widget: QWidget) -> None:
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


class IconTile(QWidget):
    """A small rounded square holding a tinted vector icon."""

    def __init__(
        self,
        name: str,
        palette: Palette,
        size: int = 36,
        tone: str = "accent",
        parent=None,
    ):
        super().__init__(parent)
        self._name = name
        self._palette = palette
        self._size = size
        self._tone = tone
        self.setFixedSize(size, size)

    def _tone_color(self) -> str:
        return getattr(self._palette, self._tone, self._palette.accent)

    def set_palette(self, palette: Palette) -> None:
        self._palette = palette
        self.update()

    def set_icon(self, name: str) -> None:
        self._name = name
        self.update()

    def paintEvent(self, event):  # noqa: N802 - Qt naming
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(Qt.NoPen)
        color = self._tone_color()
        background = QColor(color)
        background.setAlpha(28)
        painter.setBrush(background)
        painter.drawRoundedRect(QRectF(0, 0, self._size, self._size), 11, 11)
        pixmap = icons.pixmap(self._name, color, int(self._size * 0.58))
        target_x = (self._size - int(self._size * 0.58)) / 2
        target_y = (self._size - int(self._size * 0.58)) / 2
        painter.drawPixmap(int(target_x), int(target_y), pixmap)
        painter.end()


class Card(QFrame):
    """A surface with optional icon + title header and a content column."""

    def __init__(
        self,
        title: str = "",
        subtitle: str = "",
        icon: str = "",
        palette: Palette | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.setObjectName("Card")
        self._palette = palette
        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(20, 18, 20, 18)
        self._root.setSpacing(14)

        self.header_actions = QHBoxLayout()
        self.header_actions.setSpacing(8)
        self._title_label: QLabel | None = None
        self._subtitle_label: QLabel | None = None

        if title:
            header = QHBoxLayout()
            header.setSpacing(12)
            if icon and palette is not None:
                self._icon_tile = IconTile(icon, palette, 36)
                header.addWidget(self._icon_tile, 0, Qt.AlignTop)
            else:
                self._icon_tile = None
            labels = QVBoxLayout()
            labels.setSpacing(2)
            self._title_label = QLabel(title)
            self._title_label.setObjectName("CardTitle")
            labels.addWidget(self._title_label)
            if subtitle:
                self._subtitle_label = QLabel(subtitle)
                self._subtitle_label.setObjectName("CardHint")
                self._subtitle_label.setWordWrap(True)
                labels.addWidget(self._subtitle_label)
            header.addLayout(labels, 1)
            header.addLayout(self.header_actions, 0)
            self._root.addLayout(header)

        self.body = QVBoxLayout()
        self.body.setSpacing(12)
        self._root.addLayout(self.body, 1)

    def add(self, widget: QWidget, stretch: int = 0) -> QWidget:
        self.body.addWidget(widget, stretch)
        return widget

    def add_layout(self, layout, stretch: int = 0):
        self.body.addLayout(layout, stretch)
        return layout

    def add_action(self, widget: QWidget) -> None:
        self.header_actions.addWidget(widget, 0, Qt.AlignVCenter)

    def add_divider(self) -> None:
        self.body.addWidget(Divider())

    def set_dense(self) -> None:
        """Tighten padding for dashboard cards that sit above a large panel."""
        self._root.setContentsMargins(16, 12, 16, 12)
        self._root.setSpacing(8)
        self.body.setSpacing(8)

    def set_palette(self, palette: Palette) -> None:
        self._palette = palette
        if getattr(self, "_icon_tile", None) is not None:
            self._icon_tile.set_palette(palette)


class Inset(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Inset")


class Badge(QLabel):
    def __init__(self, text: str = "", tone: str = "neutral", parent=None):
        super().__init__(text, parent)
        self.setObjectName("Badge")
        self.setProperty("tone", tone)
        self.setAlignment(Qt.AlignCenter)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)

    def set_tone(self, tone: str) -> None:
        if self.property("tone") == tone:
            return
        self.setProperty("tone", tone)
        repolish(self)

    def set_state(self, text: str, tone: str) -> None:
        self.setText(text)
        self.set_tone(tone)


class Divider(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Divider")
        self.setFixedHeight(1)


class StatusDot(QWidget):
    def __init__(self, size: int = 10, parent=None):
        super().__init__(parent)
        self._size = size
        self._color = QColor("#8b98ab")
        self._glow = False
        self.setFixedSize(size + 8, size + 8)

    def set_color(self, color: str, glow: bool = False) -> None:
        self._color = QColor(color)
        self._glow = glow
        self.update()

    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        center = self.rect().center()
        if self._glow:
            glow = QColor(self._color)
            glow.setAlpha(55)
            painter.setPen(Qt.NoPen)
            painter.setBrush(glow)
            painter.drawEllipse(center, self._size / 2 + 4, self._size / 2 + 4)
        painter.setPen(Qt.NoPen)
        painter.setBrush(self._color)
        painter.drawEllipse(center, self._size / 2, self._size / 2)
        painter.end()


class StatTile(QFrame):
    """Compact KPI block used on the workspace dashboard."""

    def __init__(
        self,
        caption: str,
        value: str = "—",
        icon: str = "",
        palette: Palette | None = None,
        compact: bool = False,
        tone: str = "neutral",
        parent=None,
    ):
        super().__init__(parent)
        self.setObjectName("Inset")
        self.setProperty("tone", tone)
        layout = QHBoxLayout(self)
        if compact:
            layout.setContentsMargins(12, 9, 12, 9)
        else:
            layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8 if compact else 10)
        texts = QVBoxLayout()
        texts.setSpacing(2)
        self.value_label = QLabel(value)
        self.value_label.setObjectName("StatValueSmall" if compact else "StatValue")
        self.caption_label = QLabel(caption)
        self.caption_label.setObjectName("StatCaption")
        texts.addWidget(self.value_label)
        texts.addWidget(self.caption_label)
        layout.addLayout(texts, 1)
        self._icon_tile = None
        if icon and palette is not None:
            self._icon_tile = IconTile(
                icon, palette, 26 if compact else 32, tone=tone
            )
            layout.addWidget(self._icon_tile, 0, Qt.AlignTop)

    def set_value(self, text: str) -> None:
        self.value_label.setText(str(text))

    def set_palette(self, palette: Palette) -> None:
        if self._icon_tile is not None:
            self._icon_tile.set_palette(palette)


class ElidedLabel(QLabel):
    """QLabel that middle-elides its text instead of expanding the layout."""

    def __init__(self, text: str = "", parent=None):
        super().__init__(parent)
        self._full_text = text
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self._apply()

    def setText(self, text: str) -> None:  # noqa: N802
        self._full_text = text or ""
        self._apply()

    def full_text(self) -> str:
        return self._full_text

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        self._apply()

    def _apply(self) -> None:
        metrics = self.fontMetrics()
        available = max(20, self.width() - 4)
        text = metrics.elidedText(self._full_text, Qt.ElideMiddle, available)
        super().setText(text)
        self.setToolTip(self._full_text)


def heading(text: str, level: str = "CardTitle") -> QLabel:
    label = QLabel(text)
    label.setObjectName(level)
    return label


def caption(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("Caption")
    label.setWordWrap(True)
    return label


def hline() -> Divider:
    return Divider()


class IconLabel(QWidget):
    """Icon + text pair used inside status rows."""

    def __init__(self, name: str, palette: Palette, text: str = "", parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(7)
        self._icon = QLabel()
        self._icon.setPixmap(icons.pixmap(name, palette.muted, 16))
        self._text = QLabel(text)
        self._text.setObjectName("Caption")
        layout.addWidget(self._icon)
        layout.addWidget(self._text, 1)

    def set_text(self, text: str) -> None:
        self._text.setText(text)
