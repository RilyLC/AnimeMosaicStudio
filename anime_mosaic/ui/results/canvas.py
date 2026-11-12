"""Side-by-side / split comparison canvas for original and processed images."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter
from PySide6.QtWidgets import QWidget

from ..theme import Palette


class CompareCanvas(QWidget):
    """Shared zoom/pan canvas for both comparison images.

    ``side`` mode draws two panes with one shared scale and one shared pan
    offset, so wheel zoom and drag pan move both images together.  ``split``
    and ``result`` keep the original single-scene transform.
    """

    def __init__(self, palette: Palette, parent=None):
        super().__init__(parent)
        self._palette = palette
        self.setMinimumSize(480, 320)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self._original: QImage | None = None
        self._result: QImage | None = None
        self._mode = "side"
        self._split = 0.5
        self._scale = 1.0
        self._offset = QPointF()
        self._pan = QPointF()
        self._fit_mode = True
        self._panning = False
        self._dragging_split = False
        self._pan_origin = QPointF()

    # ------------------------------------------------------------------ setup
    def set_images(self, original: QImage | None, result: QImage | None) -> None:
        self._original = original
        self._result = result
        self._fit_mode = True
        self._fit()

    def set_mode(self, mode: str) -> None:
        self._mode = mode
        self._fit_mode = True
        self._fit()

    def mode(self) -> str:
        return self._mode

    def fit(self) -> None:
        self._fit_mode = True
        self._fit()

    def zoom_one(self) -> None:
        if self._scene_size() is None:
            return
        self._fit_mode = False
        self._scale = 1.0
        self._pan = QPointF()
        width, height = self._scene_size()
        self._offset = QPointF(
            (self.width() - width) / 2,
            (self.height() - height) / 2,
        )
        self.update()

    def _scene_size(self) -> tuple[int, int] | None:
        image = self._result or self._original
        if image is None:
            return None
        return image.width(), image.height()

    def _pane_rects(self) -> tuple[QRectF, QRectF]:
        gap = 12.0
        cell_w = max(1.0, (self.width() - gap) / 2)
        cell_h = max(1.0, self.height() - 48)
        top = 24.0
        return (
            QRectF(0, top, cell_w, cell_h),
            QRectF(cell_w + gap, top, cell_w, cell_h),
        )

    def _fit(self) -> None:
        if self._mode == "side":
            self._fit_side()
            return
        size = self._scene_size()
        if size is None or not self.width() or not self.height():
            return
        width, height = size
        self._scale = min(
            (self.width() - 32) / width,
            (self.height() - 48) / height,
            4.0,
        )
        self._offset = QPointF(
            (self.width() - width * self._scale) / 2,
            (self.height() - height * self._scale) / 2,
        )
        self.update()

    def _fit_side(self) -> None:
        images = [image for image in (self._original, self._result) if image is not None]
        if not images or not self.width() or not self.height():
            return
        left, _right = self._pane_rects()
        max_w = max(image.width() for image in images)
        max_h = max(image.height() for image in images)
        self._scale = max(
            0.01,
            min((left.width() - 16) / max_w, (left.height() - 16) / max_h, 4.0),
        )
        self._pan = QPointF()
        self.update()

    # ------------------------------------------------------------------ paint
    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(self._palette.bg))
        if self._original is None and self._result is None:
            painter.setPen(QColor(self._palette.muted))
            painter.setFont(QFont(self.font().family(), 11))
            painter.drawText(self.rect(), Qt.AlignCenter, "图片不可用")
            painter.end()
            return

        if self._mode == "side":
            self._paint_side(painter)
        elif self._mode == "result":
            self._paint_single(painter, self._result or self._original)
        else:
            self._paint_split(painter)
        painter.end()

    def _paint_single(self, painter: QPainter, image: QImage | None) -> None:
        if image is None:
            return
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        painter.save()
        painter.translate(self._offset)
        painter.scale(self._scale, self._scale)
        painter.drawImage(0, 0, image)
        painter.restore()

    def _paint_side(self, painter: QPainter) -> None:
        panes = self._pane_rects()
        for index, (image, label) in enumerate(
            ((self._original, "原图"), (self._result, "结果"))
        ):
            pane = panes[index]
            painter.save()
            painter.setClipRect(pane)
            if image is None:
                painter.setPen(QColor(self._palette.muted))
                painter.setFont(QFont(self.font().family(), 10))
                painter.drawText(pane, Qt.AlignCenter, "无结果")
            else:
                draw_w = image.width() * self._scale
                draw_h = image.height() * self._scale
                x = pane.x() + (pane.width() - draw_w) / 2 + self._pan.x()
                y = pane.y() + (pane.height() - draw_h) / 2 + self._pan.y()
                painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
                painter.drawImage(QRectF(x, y, draw_w, draw_h), image)
            painter.restore()
            self._label(painter, QRectF(pane.x() + 8, pane.y() + 8, 54, 24), label)

        painter.setPen(QColor(self._palette.dim))
        painter.drawText(
            QRectF(0, self.height() - 22, self.width(), 18),
            Qt.AlignCenter,
            "滚轮缩放 · 拖拽平移 · 两张图同步",
        )

    def _paint_split(self, painter: QPainter) -> None:
        if self._result is not None:
            self._paint_single(painter, self._result)
        if self._original is not None:
            painter.save()
            painter.translate(self._offset)
            painter.scale(self._scale, self._scale)
            split_x = self._split_px()
            image_split = max(0.0, (split_x - self._offset.x()) / self._scale)
            painter.setClipRect(QRectF(0, 0, image_split, self._original.height()))
            painter.drawImage(0, 0, self._original)
            painter.restore()

        split_x = self._split_px()
        painter.setPen(QColor("#FFFFFF"))
        painter.drawLine(QPointF(split_x, 0), QPointF(split_x, self.height()))
        painter.setBrush(QColor(self._palette.accent))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(QPointF(split_x, self.height() / 2), 7, 26)

        self._label(painter, QRectF(18, 16, 54, 24), "原图")
        self._label(
            painter, QRectF(self.width() - 72, 16, 54, 24), "结果"
        )
        painter.setPen(QColor(self._palette.dim))
        painter.drawText(
            QRectF(0, self.height() - 24, self.width(), 20),
            Qt.AlignCenter,
            "拖动中线对比 · 滚轮缩放 · 拖拽平移",
        )

    def _label(self, painter: QPainter, rect: QRectF, text: str) -> None:
        background = QColor(self._palette.surface)
        background.setAlpha(210)
        painter.setPen(Qt.NoPen)
        painter.setBrush(background)
        painter.drawRoundedRect(rect, 7, 7)
        painter.setPen(QColor(self._palette.text))
        painter.setFont(QFont(self.font().family(), 9, QFont.DemiBold))
        painter.drawText(rect, Qt.AlignCenter, text)

    # ------------------------------------------------------------------ input
    def _split_px(self) -> float:
        return self.width() * self._split

    def _pan_by(self, delta: QPointF) -> None:
        if self._mode == "side":
            self._pan += delta
        else:
            self._offset += delta

    def mousePressEvent(self, event):  # noqa: N802
        if self._scene_size() is None:
            return
        if (
            self._mode == "split"
            and event.button() == Qt.LeftButton
            and abs(event.position().x() - self._split_px()) < 14
        ):
            self._dragging_split = True
            return
        if event.button() in (Qt.LeftButton, Qt.RightButton, Qt.MiddleButton):
            self._panning = True
            self._pan_origin = event.position()
            self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, event):  # noqa: N802
        if self._dragging_split:
            self._split = min(0.98, max(0.02, event.position().x() / max(1, self.width())))
            self.update()
            return
        if self._panning:
            delta = event.position() - self._pan_origin
            self._pan_by(delta)
            self._pan_origin = event.position()
            self._fit_mode = False
            self.update()

    def mouseReleaseEvent(self, event):  # noqa: N802
        if self._dragging_split:
            self._dragging_split = False
            return
        if self._panning:
            self._panning = False
            self.setCursor(Qt.ArrowCursor)

    def wheelEvent(self, event):  # noqa: N802
        if self._scene_size() is None:
            return
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        point = event.position()
        new_scale = max(0.05, min(12.0, self._scale * factor))
        if new_scale == self._scale:
            return

        if self._mode == "side":
            panes = self._pane_rects()
            pane_index = 0 if point.x() < self.width() / 2 else 1
            image = (self._original, self._result)[pane_index]
            if image is None:
                return
            pane = panes[pane_index]
            draw_x = pane.x() + (pane.width() - image.width() * self._scale) / 2
            draw_y = pane.y() + (pane.height() - image.height() * self._scale) / 2
            image_x = (point.x() - draw_x - self._pan.x()) / self._scale
            image_y = (point.y() - draw_y - self._pan.y()) / self._scale
            self._scale = new_scale
            base_x = pane.x() + (pane.width() - image.width() * new_scale) / 2
            base_y = pane.y() + (pane.height() - image.height() * new_scale) / 2
            self._pan = QPointF(
                point.x() - base_x - image_x * new_scale,
                point.y() - base_y - image_y * new_scale,
            )
        else:
            image_x = (point.x() - self._offset.x()) / self._scale
            image_y = (point.y() - self._offset.y()) / self._scale
            self._scale = new_scale
            self._offset = QPointF(
                point.x() - image_x * new_scale,
                point.y() - image_y * new_scale,
            )
        self._fit_mode = False
        event.accept()
        self.update()

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        if self._fit_mode:
            self._fit()

    def set_palette(self, palette: Palette) -> None:
        self._palette = palette
        self.update()
