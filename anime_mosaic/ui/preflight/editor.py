"""Full-resolution mask editor with brush, eraser, undo and zoom/pan."""

from __future__ import annotations

from collections.abc import Callable

import cv2
import numpy as np
from PySide6.QtCore import QPointF, Qt, QThread, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QIcon,
    QImage,
    QImageReader,
    QKeySequence,
    QPainter,
    QPen,
    QPixmap,
    QShortcut,
)
from PySide6.QtWidgets import (
    QColorDialog,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressDialog,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from ...core.manual_mask import decode_mask, encode_mask
from ...core.masking import connected_regions
from .. import icons
from ..theme import Palette
from ..widgets.base import Badge
from ..widgets.buttons import Button, IconButton

MASK_COLOR = (235, 62, 84, 110)
GROW_COLOR = (62, 120, 235, 80)
MAX_UNDO = 24


def mask_stats(mask: np.ndarray) -> tuple[int, float]:
    regions = connected_regions(mask)
    coverage = float((mask > 0).mean() * 100.0) if mask.size else 0.0
    return len(regions), coverage


def load_mask_like(mask_png: bytes | None, size: tuple[int, int]) -> np.ndarray:
    if mask_png:
        try:
            mask = decode_mask(mask_png)
            if mask.shape == size:
                return mask
        except ValueError:
            pass
    return np.zeros(size, dtype=np.uint8)


def _qimage_from_mask(mask: np.ndarray, color: tuple[int, int, int, int] = MASK_COLOR) -> QImage:
    rgba = np.zeros((*mask.shape, 4), dtype=np.uint8)
    rgba[mask > 0] = color
    rgba = np.ascontiguousarray(rgba)
    image = QImage(rgba.data, mask.shape[1], mask.shape[0], 4 * mask.shape[1], QImage.Format_RGBA8888)
    return image.copy()


def _qimage_from_band(mask: np.ndarray, core: np.ndarray | None) -> QImage | None:
    if core is None or core.shape != mask.shape or not (mask > 0).any():
        return None
    band = (mask > 0) & ~(core > 0)
    if not band.any():
        return None
    rgba = np.zeros((*mask.shape, 4), dtype=np.uint8)
    rgba[band] = GROW_COLOR
    rgba = np.ascontiguousarray(rgba)
    image = QImage(rgba.data, mask.shape[1], mask.shape[0], 4 * mask.shape[1], QImage.Format_RGBA8888)
    return image.copy()


class MaskCanvas(QWidget):
    strokeStarted = Signal()
    maskChanged = Signal()

    def __init__(self, palette: Palette, parent=None):
        super().__init__(parent)
        self._palette = palette
        self.setMinimumSize(480, 320)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCursor(Qt.CrossCursor)
        self._image: QImage | None = None
        self._mask: np.ndarray | None = None
        self._overlay: QImage | None = None
        self._band: QImage | None = None
        self._core: np.ndarray | None = None
        self._scale = 1.0
        self._offset = QPointF(0, 0)
        self._fit_mode = True
        self._brush = 40
        self._mask_color = MASK_COLOR
        self._drawing = False
        self._drawing_button = Qt.NoButton
        self._panning = False
        self._space = False
        self._last_image_point: QPointF | None = None
        self._last_mouse = QPointF()
        self._pan_origin = QPointF()

    # ------------------------------------------------------------------ setup
    def set_image(
        self,
        image: QImage,
        mask: np.ndarray,
        grow: int = 0,
        core_mask: np.ndarray | None = None,
    ) -> None:
        self._image = image
        self._mask = mask
        self._core = core_mask if core_mask is not None and core_mask.shape == mask.shape else None
        self._fit_mode = True
        self._rebuild_overlay()
        self._fit()

    def set_mask(self, mask: np.ndarray) -> None:
        self._mask = mask
        self._rebuild_overlay()
        self.update()

    def set_core_mask(self, core: np.ndarray | None) -> None:
        """Swap the uneditable core band (used by "reset to auto detection")."""
        mask = self._mask
        self._core = core if core is not None and mask is not None and core.shape == mask.shape else None
        self._rebuild_overlay()
        self.update()

    def mask(self) -> np.ndarray | None:
        return self._mask

    def set_brush(self, size: int) -> None:
        self._brush = max(1, int(size))

    def mask_color(self) -> QColor:
        return QColor(*self._mask_color)

    def set_mask_color(self, color: QColor) -> None:
        if not color.isValid():
            return
        self._mask_color = (color.red(), color.green(), color.blue(), 110)
        self._rebuild_overlay()
        self.update()

    def fit(self) -> None:
        self._fit_mode = True
        self._fit()

    def zoom_one(self) -> None:
        if self._image is None:
            return
        self._fit_mode = False
        self._scale = 1.0
        self._offset = QPointF(
            (self.width() - self._image.width()) / 2,
            (self.height() - self._image.height()) / 2,
        )
        self.update()

    def _fit(self) -> None:
        if self._image is None or not self.width() or not self.height():
            return
        available_w = self.width() - 24
        available_h = self.height() - 24
        self._scale = min(
            available_w / max(1, self._image.width()),
            available_h / max(1, self._image.height()),
            4.0,
        )
        self._offset = QPointF(
            (self.width() - self._image.width() * self._scale) / 2,
            (self.height() - self._image.height() * self._scale) / 2,
        )
        self.update()

    def _rebuild_overlay(self) -> None:
        if self._mask is None:
            self._overlay = None
            self._band = None
        else:
            self._overlay = _qimage_from_mask(self._mask, self._mask_color)
            self._band = _qimage_from_band(self._mask, self._core)

    # ------------------------------------------------------------------ paint
    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(self._palette.bg))
        if self._image is None or self._mask is None:
            painter.setPen(QColor(self._palette.muted))
            painter.setFont(QFont(self.font().family(), 11))
            painter.drawText(self.rect(), Qt.AlignCenter, "没有可编辑的图片")
            painter.end()
            return

        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        painter.save()
        painter.translate(self._offset)
        painter.scale(self._scale, self._scale)
        painter.drawImage(0, 0, self._image)
        if self._band is not None:
            painter.drawImage(0, 0, self._band)
        if self._overlay is not None:
            painter.drawImage(0, 0, self._overlay)
        painter.restore()

        if self.underMouse():
            radius = max(4.0, self._brush * self._scale / 2)
            pen = QPen(QColor("#FFFFFF"), 1.2)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(self._last_mouse, radius, radius)
        painter.end()

    # ------------------------------------------------------------------ input
    def _to_image(self, point: QPointF) -> QPointF:
        return QPointF(
            (point.x() - self._offset.x()) / self._scale,
            (point.y() - self._offset.y()) / self._scale,
        )

    def _apply_stroke(self, start: QPointF, end: QPointF, value: int) -> None:
        if self._mask is None:
            return
        p0 = (int(round(start.x())), int(round(start.y())))
        p1 = (int(round(end.x())), int(round(end.y())))
        cv2.line(self._mask, p0, p1, int(value), self._brush, cv2.LINE_8)
        self._rebuild_overlay()
        self.update()

    def mousePressEvent(self, event):  # noqa: N802
        if self._image is None:
            return
        if event.button() == Qt.MiddleButton or (
            event.button() == Qt.LeftButton and self._space
        ):
            self._panning = True
            self._pan_origin = event.position()
            self.setCursor(Qt.ClosedHandCursor)
            return
        if event.button() in (Qt.LeftButton, Qt.RightButton):
            self._drawing = True
            self._drawing_button = event.button()
            self._fit_mode = False
            self.strokeStarted.emit()
            point = self._to_image(event.position())
            self._last_image_point = point
            self._apply_stroke(point, point, 255 if event.button() == Qt.LeftButton else 0)

    def mouseMoveEvent(self, event):  # noqa: N802
        self._last_mouse = event.position()
        if self._panning:
            delta = event.position() - self._pan_origin
            self._offset += delta
            self._pan_origin = event.position()
            self.update()
            return
        if self._drawing and self._last_image_point is not None:
            point = self._to_image(event.position())
            value = 255 if self._drawing_button == Qt.LeftButton else 0
            self._apply_stroke(self._last_image_point, point, value)
            self._last_image_point = point
        self.update()

    def mouseReleaseEvent(self, event):  # noqa: N802
        if self._panning and event.button() in (Qt.MiddleButton, Qt.LeftButton):
            self._panning = False
            self.setCursor(Qt.CrossCursor)
            return
        if self._drawing and event.button() == self._drawing_button:
            self._drawing = False
            self._drawing_button = Qt.NoButton
            self._last_image_point = None
            self.maskChanged.emit()

    def wheelEvent(self, event):  # noqa: N802
        if self._image is None:
            return
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        new_scale = max(0.05, min(12.0, self._scale * factor))
        if abs(new_scale - self._scale) < 1e-6:
            return
        point = event.position()
        image_point = self._to_image(point)
        self._scale = new_scale
        self._offset = QPointF(
            point.x() - image_point.x() * self._scale,
            point.y() - image_point.y() * self._scale,
        )
        self._fit_mode = False
        self.update()

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        if self._fit_mode:
            self._fit()

    def keyPressEvent(self, event):  # noqa: N802
        if event.key() == Qt.Key_Space:
            self._space = True
            self.setCursor(Qt.OpenHandCursor)
        else:
            super().keyPressEvent(event)

    def keyReleaseEvent(self, event):  # noqa: N802
        if event.key() == Qt.Key_Space:
            self._space = False
            self.setCursor(Qt.CrossCursor)
        else:
            super().keyReleaseEvent(event)


class _AutoDetectWorker(QThread):
    """Runs a slow detector lookup for "reset to auto detection" off-thread."""

    done = Signal(object)
    failed = Signal(str)

    def __init__(self, provider: Callable[[], tuple[bytes | None, bytes | None]], parent=None):
        super().__init__(parent)
        self._provider = provider

    def run(self) -> None:  # noqa: D401 - Qt override
        try:
            self.done.emit(self._provider())
        except Exception as exc:  # noqa: BLE001 - surfaced in a message box
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class MaskEditorDialog(QDialog):
    def __init__(
        self,
        image_path: str,
        auto_mask_png: bytes | None,
        initial_mask: np.ndarray | None,
        palette: Palette,
        title: str = "编辑遮罩",
        parent=None,
        grow: int = 0,
        core_mask_png: bytes | None = None,
        auto_provider: Callable[[], tuple[bytes | None, bytes | None]] | None = None,
    ):
        super().__init__(parent)
        self.setObjectName("MaskEditor")
        self.setWindowTitle(title)
        self.setModal(True)
        self.resize(1200, 820)
        self._palette = palette
        self._result_mask: np.ndarray | None = None
        self._undo: list[bytes] = []
        self._redo: list[bytes] = []
        #: Reads the persisted preflight result, detecting on demand when the
        #: cache has nothing for this image.
        self._auto_provider = auto_provider
        self._detect_worker: _AutoDetectWorker | None = None
        self._progress: QProgressDialog | None = None

        reader = QImageReader(image_path)
        reader.setAutoTransform(False)
        image = reader.read()
        if image.isNull():
            raise ValueError(f"无法读取图片：{image_path}")
        self._image = image
        size = (image.height(), image.width())
        self._auto_mask = load_mask_like(auto_mask_png, size)
        core_mask = load_mask_like(core_mask_png, size) if core_mask_png else None
        self._core_mask = core_mask
        if initial_mask is not None and initial_mask.shape == size:
            self._mask = np.where(initial_mask > 127, 255, 0).astype(np.uint8)
        else:
            self._mask = self._auto_mask.copy()

        self._build()
        self._canvas.set_image(image, self._mask, core_mask=core_mask)
        self._refresh_info()
        self._shortcuts = []
        for sequence, callback in (
            ("Ctrl+Z", self.undo),
            ("Ctrl+Y", self.redo),
            ("Ctrl+Shift+Z", self.redo),
            ("F", lambda: self._canvas.fit()),
            ("[", lambda: self._nudge_brush(-8)),
            ("]", lambda: self._nudge_brush(8)),
        ):
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.activated.connect(callback)
            self._shortcuts.append(shortcut)

    def _nudge_brush(self, delta: int) -> None:
        value = max(2, min(240, self._brush_slider.value() + delta))
        self._brush_slider.setValue(value)

    # ------------------------------------------------------------------ build
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(12)

        title = QLabel("编辑遮罩")
        title.setObjectName("PageTitle")
        root.addWidget(title)
        subtitle = QLabel(
            "左键绘制 · 右键擦除 · 中键拖拽 · 滚轮缩放 · 空格 + 左键也可平移"
        )
        subtitle.setObjectName("PageSubtitle")
        root.addWidget(subtitle)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        self._color_button = Button("遮罩颜色", "ghost", None, self._palette, size="sm")
        self._color_button.setToolTip("只改变编辑预览的显示颜色，保存的遮罩仍是黑白")
        self._color_button.clicked.connect(self._choose_color)
        toolbar.addWidget(self._color_button)
        self._update_color_button()
        toolbar.addSpacing(8)
        size_label = QLabel("笔刷")
        size_label.setObjectName("Caption")
        toolbar.addWidget(size_label)
        self._brush_slider = QSlider(Qt.Horizontal)
        self._brush_slider.setRange(2, 240)
        self._brush_slider.setValue(40)
        self._brush_slider.setFixedWidth(150)
        self._brush_slider.valueChanged.connect(self._on_brush)
        toolbar.addWidget(self._brush_slider)
        self._brush_value = QLabel("40 px")
        self._brush_value.setObjectName("Caption")
        self._brush_value.setFixedWidth(48)
        toolbar.addWidget(self._brush_value)
        toolbar.addStretch(1)
        undo = IconButton("undo", "撤销 Ctrl+Z", self._palette, 34, 17)
        undo.clicked.connect(self.undo)
        redo = IconButton("redo", "重做 Ctrl+Y", self._palette, 34, 17)
        redo.clicked.connect(self.redo)
        toolbar.addWidget(undo)
        toolbar.addWidget(redo)
        clear = Button("清空", "ghost", "trash", self._palette, size="sm")
        clear.clicked.connect(self._clear)
        toolbar.addWidget(clear)
        reset = Button("重置为自动检测", "ghost", "refresh", self._palette, size="sm")
        reset.clicked.connect(self._reset_auto)
        toolbar.addWidget(reset)
        fit = Button("适应窗口", "secondary", "scan", self._palette, size="sm")
        fit.clicked.connect(lambda: self._canvas.fit())
        toolbar.addWidget(fit)
        actual = Button("1:1", "ghost", None, self._palette, size="sm")
        actual.clicked.connect(lambda: self._canvas.zoom_one())
        toolbar.addWidget(actual)
        root.addLayout(toolbar)

        frame = QFrame()
        frame.setObjectName("Inset")
        frame_layout = QVBoxLayout(frame)
        frame_layout.setContentsMargins(2, 2, 2, 2)
        self._canvas = MaskCanvas(self._palette)
        self._canvas.strokeStarted.connect(self._snapshot)
        self._canvas.maskChanged.connect(self._refresh_info)
        frame_layout.addWidget(self._canvas)
        root.addWidget(frame, 1)

        footer = QHBoxLayout()
        footer.setSpacing(10)
        self._info = QLabel("")
        self._info.setObjectName("Caption")
        footer.addWidget(self._info, 1)
        self._manual_badge = Badge("保存后处理时优先使用", "accent")
        footer.addWidget(self._manual_badge)
        cancel = Button("取消", "ghost", None, self._palette)
        cancel.clicked.connect(self.reject)
        footer.addWidget(cancel)
        save = Button("保存遮罩", "primary", "save", self._palette)
        save.clicked.connect(self._save)
        footer.addWidget(save)
        root.addLayout(footer)

    # ------------------------------------------------------------------ state
    def _choose_color(self) -> None:
        color = QColorDialog.getColor(
            self._canvas.mask_color(), self, "选择遮罩显示颜色"
        )
        if not color.isValid():
            return
        self._canvas.set_mask_color(color)
        self._update_color_button()

    def _update_color_button(self) -> None:
        color = self._canvas.mask_color() if hasattr(self, "_canvas") else QColor(*MASK_COLOR)
        pixmap = QPixmap(14, 14)
        pixmap.fill(color)
        self._color_button.setIcon(QIcon(pixmap))

    def _on_brush(self, value: int) -> None:
        self._canvas.set_brush(value)
        self._brush_value.setText(f"{value} px")

    def _snapshot(self) -> bytes:
        snapshot = encode_mask(self._canvas.mask())
        self._undo.append(snapshot)
        if len(self._undo) > MAX_UNDO:
            self._undo.pop(0)
        self._redo.clear()
        return snapshot

    def undo(self) -> None:
        if not self._undo:
            return
        self._redo.append(encode_mask(self._canvas.mask()))
        self._canvas.set_mask(decode_mask(self._undo.pop()))
        self._refresh_info()

    def redo(self) -> None:
        if not self._redo:
            return
        self._undo.append(encode_mask(self._canvas.mask()))
        self._canvas.set_mask(decode_mask(self._redo.pop()))
        self._refresh_info()

    def _clear(self) -> None:
        self._undo.append(encode_mask(self._canvas.mask()))
        self._redo.clear()
        empty = np.zeros((self._image.height(), self._image.width()), dtype=np.uint8)
        self._canvas.set_mask(empty)
        self._refresh_info()

    def _reset_auto(self) -> None:
        if self._auto_provider is None:
            self._apply_auto(self._auto_mask, self._core_mask)
            return
        if self._detect_worker is not None:
            return
        progress = QProgressDialog("正在自动识别马赛克，请稍候…", "", 0, 0, self)
        progress.setWindowTitle("自动检测")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.setCancelButton(None)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        progress.show()
        worker = _AutoDetectWorker(self._auto_provider, self)
        worker.done.connect(self._on_detected)
        worker.failed.connect(self._on_detect_failed)
        self._progress = progress
        self._detect_worker = worker
        worker.start()

    def _on_detected(self, payload) -> None:
        self._finish_detect()
        if payload is None:
            QMessageBox.information(
                self, "自动检测", "没有可用的自动检测结果，请先检查检测模型设置。"
            )
            return
        mask_png, core_png = payload
        size = (self._image.height(), self._image.width())
        # A successful detection without mosaic legitimately has no payload:
        # "reset" then means an empty mask, not an error.
        if mask_png:
            mask = load_mask_like(mask_png, size)
        else:
            mask = np.zeros(size, dtype=np.uint8)
        core = load_mask_like(core_png, size) if core_png else None
        self._auto_mask = mask
        self._core_mask = core
        self._apply_auto(mask, core)

    def _on_detect_failed(self, message: str) -> None:
        self._finish_detect()
        QMessageBox.warning(self, "自动检测失败", message)

    def _finish_detect(self) -> None:
        if self._progress is not None:
            self._progress.close()
            self._progress.deleteLater()
            self._progress = None
        worker = self._detect_worker
        self._detect_worker = None
        if worker is not None:
            worker.wait(1000)
            worker.deleteLater()

    def _detach_detect_worker(self) -> None:
        """Let an in-flight detection finish without touching a closing dialog."""
        worker = self._detect_worker
        self._detect_worker = None
        if self._progress is not None:
            self._progress.close()
            self._progress.deleteLater()
            self._progress = None
        if worker is None:
            return
        try:
            worker.done.disconnect(self._on_detected)
            worker.failed.disconnect(self._on_detect_failed)
        except (RuntimeError, TypeError):
            pass
        worker.setParent(None)
        worker.finished.connect(worker.deleteLater)

    def _apply_auto(self, mask: np.ndarray, core: np.ndarray | None) -> None:
        self._undo.append(encode_mask(self._canvas.mask()))
        self._redo.clear()
        self._canvas.set_core_mask(core)
        self._canvas.set_mask(mask.copy())
        self._refresh_info()

    def done(self, result: int) -> None:  # noqa: N802 - Qt override
        self._detach_detect_worker()
        super().done(result)

    def _refresh_info(self) -> None:
        mask = self._canvas.mask()
        if mask is None:
            return
        regions, coverage = mask_stats(mask)
        self._info.setText(
            f"遮罩覆盖 {coverage:.2f}% · {regions} 个区域 · 笔刷 {self._brush_slider.value()} px"
        )

    def _save(self) -> None:
        self._result_mask = self._canvas.mask().copy()
        self.accept()

    def result_mask(self) -> np.ndarray | None:
        return self._result_mask
