"""Single source of truth for the application mark and window icon.

The mark is a *restored* mosaic: a soft grid dissolving under a sparkle.  It
reads as "pixel blocks giving way to a clean image", which is what the app
does, and it still holds up at 16 px where a literal before/after split turns
to mush.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QIcon,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPixmap,
)

from .theme import Palette

ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)


def _sparkle(cx: float, cy: float, outer: float, inner: float) -> QPainterPath:
    """Four-point star with concave sides — the "clean up" signal in the mark."""
    path = QPainterPath()
    points: list[QPointF] = []
    for index in range(8):
        angle = math.radians(index * 45.0 - 90.0)
        radius = outer if index % 2 == 0 else inner
        points.append(QPointF(cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
    path.moveTo(points[0])
    for point in points[1:]:
        path.lineTo(point)
    path.closeSubpath()
    return path


def draw_logo(painter: QPainter, rect: QRectF, palette: Palette) -> None:
    """Paint the application mark into ``rect``.

    The same drawing is used by the sidebar brand, the About page and the
    window/taskbar icon so the three can never drift apart.
    """
    size = min(rect.width(), rect.height())
    if size <= 0:
        return
    x0 = rect.x() + (rect.width() - size) / 2
    y0 = rect.y() + (rect.height() - size) / 2
    unit = size / 100.0

    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, True)

    badge = QPainterPath()
    badge.addRoundedRect(QRectF(x0, y0, size, size), size * 0.3, size * 0.3)

    gradient = QLinearGradient(x0, y0, x0 + size, y0 + size)
    gradient.setColorAt(0.0, QColor(palette.accent))
    gradient.setColorAt(1.0, QColor(palette.accent_2))
    painter.setPen(Qt.NoPen)
    painter.setBrush(gradient)
    painter.drawPath(badge)

    # Gloss along the top edge keeps the flat gradient from looking like a
    # default placeholder swatch.
    painter.save()
    painter.setClipPath(badge)
    gloss = QLinearGradient(x0, y0, x0, y0 + size * 0.62)
    gloss.setColorAt(0.0, QColor(255, 255, 255, 46))
    gloss.setColorAt(1.0, QColor(255, 255, 255, 0))
    painter.setBrush(gloss)
    painter.drawRect(QRectF(x0, y0, size, size * 0.62))
    painter.restore()

    # Faint mosaic grid: enough to hint at pixel blocks, quiet enough to
    # disappear at small sizes.
    if size >= 24:
        tile = 12.5 * unit
        gap = 4.2 * unit
        origin = 13.0 * unit
        painter.setBrush(QColor(255, 255, 255, 26))
        for row in range(4):
            for column in range(4):
                painter.drawRoundedRect(
                    QRectF(
                        x0 + origin + column * (tile + gap),
                        y0 + origin + row * (tile + gap),
                        tile,
                        tile,
                    ),
                    tile * 0.22,
                    tile * 0.22,
                )

    # Main sparkle, with a soft shadow so white holds up on the teal corner.
    big_outer = 33.0 * unit
    cx, cy = x0 + 47.0 * unit, y0 + 50.0 * unit
    if size >= 32:
        shadow = _sparkle(cx + 1.6 * unit, cy + 2.4 * unit, big_outer, 9.0 * unit)
        painter.setBrush(QColor(16, 26, 48, 55))
        painter.drawPath(shadow)
    painter.setBrush(QColor(255, 255, 255))
    painter.drawPath(_sparkle(cx, cy, big_outer, 9.0 * unit))

    # Secondary sparkle: a small "lens" glint in the free corner.  Below 24 px
    # it only reads as a stray dot, so it is dropped there.
    if size >= 24:
        glint_outer = 11.0 * unit
        painter.setBrush(QColor(255, 255, 255, 205))
        painter.drawPath(_sparkle(x0 + 79.0 * unit, y0 + 23.0 * unit, glint_outer, 3.2 * unit))

    painter.restore()


def logo_pixmap(palette: Palette, size: int = 128) -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    draw_logo(painter, QRectF(0, 0, size, size), palette)
    painter.end()
    return pixmap


def app_icon(palette: Palette, size: int = 256) -> QIcon:
    """Return the one icon used by the window, taskbar and About page.

    Every size is drawn from the vector description rather than downscaled
    from 256 px, so the 16–32 px variants stay crisp in the taskbar and in
    Explorer.
    """
    largest = max(size, max(ICON_SIZES))
    icon = QIcon()
    for edge in sorted({*ICON_SIZES, largest}):
        icon.addPixmap(logo_pixmap(palette, edge))
    return icon
