"""Compose an image + translucent mask preview and show it with zoom / pan.

The preview has to cope with every aspect ratio a user may throw at it
(portrait scans, panoramas, square avatars…), so the composed pixmap is
always letterboxed to fit the available viewport instead of being placed
into a fixed-size label.  Wheel zooms around the cursor, dragging pans and a
double click snaps back to "fit".
"""

from __future__ import annotations

import cv2
import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QImage, QImageReader, QPainter, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QSizePolicy,
    QStackedLayout,
    QVBoxLayout,
    QWidget,
)

from ...core.manual_mask import decode_mask
from ...core.masking import grow_mask
from .. import icons
from ..theme import Palette

GROW_COLOR = (62, 120, 235)
NSFW_COLOR = (255, 178, 46)

#: Zoom is relative to "fit": 1.0 fills the viewport, MAX_ZOOM is 8x that.
MIN_ZOOM = 1.0
MAX_ZOOM = 8.0
ZOOM_STEP = 1.25
FIT_MARGIN = 10


def compose_preview(
    path: str,
    mask_png: bytes | None,
    max_width: int = 900,
    max_height: int = 640,
    show_mask: bool = True,
    grow: int = 0,
    show_grow: bool = True,
    nsfw_boxes: tuple[tuple[str, float, int, int, int, int], ...] = (),
    show_nsfw: bool = False,
    core_mask_png: bytes | None = None,
) -> QPixmap:
    reader = QImageReader(path)
    size = reader.size()
    original_w = size.width() if size.isValid() else 0
    original_h = size.height() if size.isValid() else 0
    if size.isValid():
        scale = min(max_width / max(1, size.width()), max_height / max(1, size.height()), 1.0)
        reader.setScaledSize(
            size.scaled(int(size.width() * scale), int(size.height() * scale), Qt.KeepAspectRatio)
        )
    image = reader.read()
    if image.isNull():
        return QPixmap()
    image = image.convertToFormat(QImage.Format_RGB888)
    width, height = image.width(), image.height()
    stride = image.bytesPerLine()
    buffer = np.frombuffer(image.constBits(), dtype=np.uint8)
    rgb = buffer.reshape(height, stride)[:, : width * 3].reshape(height, width, 3).copy()

    if show_mask and mask_png:
        try:
            mask = decode_mask(mask_png)
            mask = cv2.resize(mask, (width, height), interpolation=cv2.INTER_NEAREST)
            if core_mask_png:
                core = decode_mask(core_mask_png)
                core = cv2.resize(core, (width, height), interpolation=cv2.INTER_NEAREST)
                core_selected = core > 0
            else:
                # Older entries only have the final mask; do not grow it again.
                core_selected = mask > 0
            if core_selected.any() and show_grow and grow > 0:
                scaled_grow = max(
                    1,
                    int(round(grow * (height / max(1, original_h or height)))),
                )
                band = grow_mask(core_selected.astype(np.uint8) * 255, scaled_grow)
                band_only = (band > 0) & ~core_selected
                if band_only.any():
                    overlay = rgb.astype(np.float32)
                    overlay[band_only] = (
                        overlay[band_only] * 0.55 + np.array(GROW_COLOR) * 0.45
                    )
                    rgb = np.clip(overlay, 0, 255).astype(np.uint8)
            if core_selected.any():
                overlay = rgb.astype(np.float32)
                overlay[core_selected] = (
                    overlay[core_selected] * 0.45 + np.array([235, 62, 84]) * 0.55
                )
                rgb = np.clip(overlay, 0, 255).astype(np.uint8)
        except (ValueError, cv2.error):
            pass

    if show_nsfw and nsfw_boxes:
        sx = width / max(1, original_w or width)
        sy = height / max(1, original_h or height)
        for name, conf, x, y, w, h in nsfw_boxes:
            p1 = (int(x * sx), int(y * sy))
            p2 = (int((x + w) * sx), int((y + h) * sy))
            cv2.rectangle(rgb, p1, p2, NSFW_COLOR, 2, cv2.LINE_AA)
            cv2.putText(
                rgb,
                f"{name} {conf:.2f}",
                (p1[0] + 3, max(12, p1[1] + 14)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.42,
                NSFW_COLOR,
                1,
                cv2.LINE_AA,
            )

    rgb = np.ascontiguousarray(rgb)
    result = QImage(rgb.data, width, height, 3 * width, QImage.Format_RGB888)
    return QPixmap.fromImage(result.copy())


class PreviewCanvas(QWidget):
    """Letterboxed pixmap view with wheel zoom and drag panning."""

    zoomChanged = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmap = QPixmap()
        self._zoom = MIN_ZOOM
        self._offset = QPointF(0.0, 0.0)
        self._drag_from: QPointF | None = None
        self.setMinimumSize(200, 160)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setCursor(Qt.OpenHandCursor)

    # ------------------------------------------------------------ public API
    def set_pixmap(self, pixmap: QPixmap) -> None:
        self._pixmap = pixmap
        self._zoom = MIN_ZOOM
        self._offset = QPointF(0.0, 0.0)
        self._update_cursor()
        self.update()
        self.zoomChanged.emit(self.zoom_percent())

    def clear(self) -> None:
        self._pixmap = QPixmap()
        self._zoom = MIN_ZOOM
        self._offset = QPointF(0.0, 0.0)
        self._update_cursor()
        self.update()

    def has_pixmap(self) -> bool:
        return not self._pixmap.isNull()

    def zoom_percent(self) -> float:
        """Zoom relative to the source pixmap, as a percentage."""
        if self._pixmap.isNull():
            return 0.0
        return self._fit_scale() * self._zoom * 100.0

    def zoom_in(self) -> None:
        self._zoom_at(ZOOM_STEP, self._center())

    def zoom_out(self) -> None:
        self._zoom_at(1.0 / ZOOM_STEP, self._center())

    def fit_to_view(self) -> None:
        if self._zoom == MIN_ZOOM and self._offset == QPointF(0.0, 0.0):
            return
        self._zoom = MIN_ZOOM
        self._offset = QPointF(0.0, 0.0)
        self._update_cursor()
        self.update()
        self.zoomChanged.emit(self.zoom_percent())

    # -------------------------------------------------------------- geometry
    def _center(self) -> QPointF:
        return QPointF(self.width() / 2.0, self.height() / 2.0)

    def _fit_scale(self) -> float:
        if self._pixmap.isNull():
            return 1.0
        available_w = max(1, self.width() - 2 * FIT_MARGIN)
        available_h = max(1, self.height() - 2 * FIT_MARGIN)
        scale = min(
            available_w / self._pixmap.width(), available_h / self._pixmap.height()
        )
        # Never upscale a small image: "fit" means "no larger than native".
        return min(scale, 1.0)

    def _clamp_offset(self) -> None:
        if self._pixmap.isNull():
            self._offset = QPointF(0.0, 0.0)
            return
        scale = self._fit_scale() * self._zoom
        scaled_w = self._pixmap.width() * scale
        scaled_h = self._pixmap.height() * scale
        max_x = max(0.0, (scaled_w - self.width()) / 2.0)
        max_y = max(0.0, (scaled_h - self.height()) / 2.0)
        self._offset = QPointF(
            max(-max_x, min(max_x, self._offset.x())),
            max(-max_y, min(max_y, self._offset.y())),
        )

    def _zoom_at(self, factor: float, anchor: QPointF) -> None:
        if self._pixmap.isNull():
            return
        new_zoom = max(MIN_ZOOM, min(MAX_ZOOM, self._zoom * factor))
        if abs(new_zoom - self._zoom) < 1e-6:
            return
        fit = self._fit_scale()
        pixmap_w = self._pixmap.width()
        pixmap_h = self._pixmap.height()
        scale = fit * self._zoom
        center = self._center()
        left = center.x() - pixmap_w * scale / 2.0 + self._offset.x()
        top = center.y() - pixmap_h * scale / 2.0 + self._offset.y()
        # Image coordinate under the cursor; keep it there after zooming.
        image_x = (anchor.x() - left) / scale
        image_y = (anchor.y() - top) / scale
        scale = fit * new_zoom
        self._zoom = new_zoom
        self._offset = QPointF(
            anchor.x() - (center.x() - pixmap_w * scale / 2.0) - image_x * scale,
            anchor.y() - (center.y() - pixmap_h * scale / 2.0) - image_y * scale,
        )
        self._clamp_offset()
        self._update_cursor()
        self.update()
        self.zoomChanged.emit(self.zoom_percent())

    def _update_cursor(self) -> None:
        if self._zoom > MIN_ZOOM:
            self.setCursor(Qt.OpenHandCursor)
        else:
            self.setCursor(Qt.ArrowCursor)

    # ---------------------------------------------------------------- events
    def paintEvent(self, event):  # noqa: N802
        if self._pixmap.isNull():
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        scale = self._fit_scale() * self._zoom
        width = self._pixmap.width() * scale
        height = self._pixmap.height() * scale
        left = (self.width() - width) / 2.0 + self._offset.x()
        top = (self.height() - height) / 2.0 + self._offset.y()
        painter.drawPixmap(
            QRectF(left, top, width, height),
            self._pixmap,
            QRectF(0, 0, self._pixmap.width(), self._pixmap.height()),
        )
        painter.end()

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        self._clamp_offset()
        self.zoomChanged.emit(self.zoom_percent())

    def wheelEvent(self, event):  # noqa: N802
        if self._pixmap.isNull():
            return
        steps = event.angleDelta().y() / 120.0
        if not steps:
            steps = event.angleDelta().x() / 120.0
        if not steps:
            return
        self._zoom_at(ZOOM_STEP**steps, event.position())
        event.accept()

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.LeftButton and self._zoom > MIN_ZOOM:
            self._drag_from = event.position()
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()

    def mouseMoveEvent(self, event):  # noqa: N802
        if self._drag_from is None:
            return
        delta = event.position() - self._drag_from
        self._drag_from = event.position()
        self._offset += delta
        self._clamp_offset()
        self.update()
        event.accept()

    def mouseReleaseEvent(self, event):  # noqa: N802
        if event.button() == Qt.LeftButton and self._drag_from is not None:
            self._drag_from = None
            self._update_cursor()
            event.accept()

    def mouseDoubleClickEvent(self, event):  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.fit_to_view()
            event.accept()


class MaskPreview(QFrame):
    zoomChanged = Signal(float)

    def __init__(self, palette: Palette, parent=None):
        super().__init__(parent)
        self.setObjectName("Inset")
        self._palette = palette
        self._stack = QStackedLayout(self)
        self._stack.setContentsMargins(0, 0, 0, 0)

        empty = QWidget()
        layout = QVBoxLayout(empty)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(10)
        icon = QLabel()
        icon.setPixmap(icons.pixmap("image", palette.dim, 40))
        icon.setAlignment(Qt.AlignCenter)
        text = QLabel("选择左侧图片查看遮罩")
        text.setObjectName("Caption")
        text.setAlignment(Qt.AlignCenter)
        layout.addWidget(icon)
        layout.addWidget(text)
        self._stack.addWidget(empty)

        self._canvas = PreviewCanvas()
        self._canvas.zoomChanged.connect(self.zoomChanged)
        self._stack.addWidget(self._canvas)

    def show_preview(self, pixmap: QPixmap) -> None:
        if pixmap.isNull():
            self.clear()
            return
        self._canvas.set_pixmap(pixmap)
        self._stack.setCurrentIndex(1)

    def clear(self) -> None:
        self._canvas.clear()
        self._stack.setCurrentIndex(0)

    def zoom_in(self) -> None:
        self._canvas.zoom_in()

    def zoom_out(self) -> None:
        self._canvas.zoom_out()

    def fit_to_view(self) -> None:
        self._canvas.fit_to_view()

    def zoom_percent(self) -> float:
        return self._canvas.zoom_percent()

    def set_palette(self, palette: Palette) -> None:
        self._palette = palette
