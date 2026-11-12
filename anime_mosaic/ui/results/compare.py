"""Result comparison dialog with mask editing, regeneration and post-process UI."""

from __future__ import annotations

import os

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QImage
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QVBoxLayout,
)

from ...core.events import STAGE_LABELS
from ...core.manual_mask import ManualMaskStore
from ...services.output_state import state_key
from ...services.preflight import PreflightEntry, entry_mask_png
from ...services.reuse_groups import build_groups, load_disabled, load_mask_for_entry
from ..preflight.controller import PreflightController
from ..preflight.editor import MaskEditorDialog, load_mask_like
from ..state import SettingsStore
from ..theme import Palette
from ..widgets.base import Badge, Card
from ..widgets.buttons import Button, IconButton
from ..widgets.segmented import SegmentedControl

from .canvas import CompareCanvas
from .controller import ResultItem, SingleRunController
from .postprocess import PostProcessDialog


class ResultCompareDialog(QDialog):
    regenerated = Signal(object)
    log = Signal(str, str)

    def __init__(
        self,
        items: list[ResultItem],
        index: int,
        store: SettingsStore,
        palette: Palette,
        preflight: PreflightController | None = None,
        parent=None,
        detector_provider=None,
    ):
        super().__init__(parent)
        self._items = list(items)
        self._index = max(0, min(len(items) - 1, index)) if items else 0
        self._store = store
        self._palette = palette
        self._preflight = preflight
        self._detector_provider = detector_provider
        self._original: QImage | None = None
        self._result: QImage | None = None

        self.setObjectName("CompareDialog")
        self.setWindowTitle("结果对比 · AnimeMosaicStudio")
        self.setModal(False)
        self.setWindowFlags(
            self.windowFlags()
            | Qt.WindowMinimizeButtonHint
            | Qt.WindowMaximizeButtonHint
            | Qt.WindowCloseButtonHint
        )
        self.resize(1280, 860)
        self.setMinimumSize(860, 600)
        self.setSizeGripEnabled(True)
        self._controller = SingleRunController(
            self, detector_provider=detector_provider
        )
        self._group_cache = None
        self._group_cache_key = None
        self._build()
        self._connect()
        self._load_current()

    # ------------------------------------------------------------------ build
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(12)

        header = QHBoxLayout()
        header.setSpacing(10)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        title = QLabel("结果对比")
        title.setObjectName("PageTitle")
        self._subtitle = QLabel("默认并排查看原图与结果；重新生成会覆盖当前输出，同一复用组会一起更新。")
        self._subtitle.setObjectName("PageSubtitle")
        titles.addWidget(title)
        titles.addWidget(self._subtitle)
        header.addLayout(titles, 1)
        self._position = Badge("", "neutral")
        header.addWidget(self._position, 0, Qt.AlignTop)
        self._max_button = Button("最大化", "ghost", None, self._palette, size="sm")
        self._max_button.clicked.connect(self._toggle_maximize)
        header.addWidget(self._max_button, 0, Qt.AlignTop)
        prev = IconButton("chevron_left", "上一张", self._palette, 34, 17)
        prev.clicked.connect(lambda: self._navigate(-1))
        self._prev_button = prev
        next_button = IconButton("chevron_right", "下一张", self._palette, 34, 17)
        next_button.clicked.connect(lambda: self._navigate(1))
        self._next_button = next_button
        header.addWidget(prev, 0, Qt.AlignTop)
        header.addWidget(next_button, 0, Qt.AlignTop)
        root.addLayout(header)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        self._modes = SegmentedControl(["并排", "滑动对比", "仅结果"], self._palette)
        self._modes.currentChanged.connect(self._on_mode)
        toolbar.addWidget(self._modes)
        toolbar.addSpacing(8)
        fit = Button("适应窗口", "secondary", "scan", self._palette, size="sm")
        fit.clicked.connect(lambda: self._canvas.fit())
        toolbar.addWidget(fit)
        one = Button("1:1", "ghost", None, self._palette, size="sm")
        one.clicked.connect(lambda: self._canvas.zoom_one())
        toolbar.addWidget(one)
        toolbar.addStretch(1)
        self._meta = QLabel("")
        self._meta.setObjectName("Caption")
        toolbar.addWidget(self._meta)
        root.addLayout(toolbar)

        frame = QFrame()
        frame.setObjectName("Inset")
        frame_layout = QVBoxLayout(frame)
        frame_layout.setContentsMargins(2, 2, 2, 2)
        self._canvas = CompareCanvas(self._palette)
        frame_layout.addWidget(self._canvas)
        root.addWidget(frame, 1)

        footer = QHBoxLayout()
        footer.setSpacing(8)
        self._status = QLabel("就绪")
        self._status.setObjectName("Caption")
        footer.addWidget(self._status, 1)
        self._busy = QProgressBar()
        self._busy.setRange(0, 0)
        self._busy.setFixedWidth(120)
        self._busy.hide()
        footer.addWidget(self._busy)
        open_output = Button("打开输出", "ghost", "folder", self._palette, size="sm")
        open_output.clicked.connect(self._open_output)
        footer.addWidget(open_output)
        self._post_button = Button("一键后处理", "secondary", "sparkles", self._palette, size="sm")
        self._post_button.clicked.connect(self._open_postprocess)
        footer.addWidget(self._post_button)
        footer.addWidget(Badge("开发中", "warn"))
        self._edit_button = Button("编辑遮罩", "secondary", "brush", self._palette, size="sm")
        self._edit_button.clicked.connect(lambda: self._edit_mask())
        footer.addWidget(self._edit_button)
        self._regen_button = Button("重新生成", "primary", "refresh", self._palette)
        self._regen_button.clicked.connect(self._toggle_regenerate)
        footer.addWidget(self._regen_button)
        close = Button("关闭", "ghost", None, self._palette)
        close.clicked.connect(self.close)
        footer.addWidget(close)
        root.addLayout(footer)

    def _connect(self) -> None:
        self._controller.log.connect(self.log.emit)
        self._controller.log.connect(self._on_log)
        self._controller.stage.connect(self._on_stage)
        self._controller.progress.connect(self._on_progress)
        self._controller.finished.connect(self._on_finished)
        self._controller.failed.connect(self._on_failed)
        self._controller.cancelled.connect(self._on_cancelled)
        self._controller.runningChanged.connect(self._on_running)

    # ------------------------------------------------------------------ state
    def is_regenerating(self) -> bool:
        return self._controller.running

    def apply_palette(self, palette: Palette) -> None:
        self._palette = palette
        self._canvas.set_palette(palette)
        self._max_button.set_palette(palette)

    def _toggle_maximize(self) -> None:
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def changeEvent(self, event):  # noqa: N802
        if event.type() == QEvent.Type.WindowStateChange:
            button = getattr(self, "_max_button", None)
            if button is not None:
                button.setText("还原" if self.isMaximized() else "最大化")
        super().changeEvent(event)

    def _current(self) -> ResultItem | None:
        if 0 <= self._index < len(self._items):
            return self._items[self._index]
        return None

    def select_rel(self, rel: str) -> bool:
        """Show the given output file, returning False when it is not listed."""
        if self._controller.running:
            return False
        for position, item in enumerate(self._items):
            if item.rel == rel:
                self._index = position
                self._load_current()
                return True
        return False

    def _navigate(self, delta: int) -> None:
        if self._controller.running or not self._items:
            return
        self._index = max(0, min(len(self._items) - 1, self._index + delta))
        self._load_current()

    def _load_current(self) -> None:
        item = self._current()
        if item is None:
            self._subtitle.setText("没有可对比的结果")
            self._position.setText("0 / 0")
            self._canvas.set_images(None, None)
            self._regen_button.setEnabled(False)
            self._edit_button.setEnabled(False)
            return
        self._position.setText(f"{self._index + 1} / {len(self._items)}")
        self._subtitle.setText(item.rel)
        self._original = _read_image(item.input_path)
        self._result = _read_image(item.output_path)
        self._canvas.set_images(self._original, self._result)
        self._prev_button.setEnabled(self._index > 0)
        self._next_button.setEnabled(self._index < len(self._items) - 1)
        record = item.record
        details = []
        if record is not None:
            if record.status_label:
                details.append(record.status_label)
            if record.regions:
                details.append(f"{record.regions} 区域")
            if record.seconds:
                details.append(f"{record.seconds:.1f}s")
            if record.seed:
                details.append(f"seed {record.seed}")
        if self._result is not None:
            details.append(f"{self._result.width()}×{self._result.height()}")
        self._meta.setText(" · ".join(details))
        self._regen_button.setEnabled(
            bool(self._store.get("output_dir"))
            and os.path.isfile(item.input_path)
            and not self._controller.running
        )
        self._edit_button.setEnabled(
            bool(self._store.get("output_dir"))
            and os.path.isfile(item.input_path)
            and not self._controller.running
        )
        self._status.setText("就绪")

    # ------------------------------------------------------------------ modes
    def _on_mode(self, index: int) -> None:
        self._canvas.set_mode(("side", "split", "result")[index])

    # ------------------------------------------------------------- regenerate
    def _toggle_regenerate(self) -> None:
        if self._controller.running:
            self._controller.stop()
            self._regen_button.setEnabled(False)
            self._status.setText("正在停止…")
            return
        if self._preflight is not None and self._preflight.running:
            self._status.setText("预识别仍在运行，请稍候再重新生成")
            return
        item = self._current()
        if item is None:
            return
        settings = self._store.settings
        if not settings.input_dir or not settings.output_dir:
            QMessageBox.warning(self, "无法重新生成", "请先选择输入与输出目录")
            return
        self._status.setText("正在连接 ComfyUI…")
        self._controller.start(settings, item.rel, group_provider=self._reuse_group)

    def _reuse_group(self, rel: str) -> list[str]:
        """Members of ``rel``'s reuse group, in regeneration order (rel first).

        Regenerating the whole group lets the first image generate and the rest
        reuse that result after the usual exact pixel check, so every member
        ends up with the same new content.  Entries the user disabled in
        "差分管理" are left untouched.
        """
        settings = self._store.settings
        if not settings.reuse_enabled or self._preflight is None:
            return [rel]
        entries = self._preflight.entries
        if len(entries) < 2 or not any(entry.rel == rel for entry in entries):
            return [rel]
        store = ManualMaskStore(settings.output_dir)
        cache_key = (len(entries), round(float(settings.reuse_min_group_iou), 4))
        if self._group_cache is None or self._group_cache_key != cache_key:
            groups = build_groups(
                entries,
                lambda entry: load_mask_for_entry(entry, store),
                min_iou=settings.reuse_min_group_iou,
            )
            # Keep only rel → members: the masks are large and no longer needed.
            self._group_cache = {
                member: group.rels for group in groups for member in group.rels
            }
            self._group_cache_key = cache_key
        group_rels = self._group_cache.get(rel)
        if not group_rels:
            return [rel]
        disabled = load_disabled(settings.output_dir)
        members = [
            member
            for member in group_rels
            if member != rel and state_key(member) not in disabled
        ]
        skipped = len(group_rels) - len(members) - 1
        if skipped:
            self.log.emit(
                "info", f"复用组中 {skipped} 张已停用，不参与本次重新生成"
            )
        if members:
            self.log.emit(
                "info", f"复用组共 {len(group_rels)} 张，将一起重新生成"
            )
        return [rel, *members]

    def _on_running(self, running: bool) -> None:
        self._busy.setVisible(running)
        self._regen_button.setText("停止" if running else "重新生成")
        self._regen_button.set_variant("danger" if running else "primary")
        self._regen_button.setEnabled(True)
        self._edit_button.setEnabled(not running)
        self._prev_button.setEnabled(not running and self._index > 0)
        self._next_button.setEnabled(not running and self._index < len(self._items) - 1)
        if running:
            self._status.setText("正在重新生成…")

    def _on_stage(self, rel: str, stage: str, detail: str) -> None:
        label = STAGE_LABELS.get(stage, stage)
        if detail:
            label += f" · {detail}"
        self._status.setText(label)

    def _on_progress(self, done: int, total: int, rel: str, speed: float, eta: float) -> None:
        if total > 1:
            self._status.setText(f"完成 {done}/{total} · 平均 {speed:.1f}s/张")
        else:
            self._status.setText(f"完成 · {speed:.1f}s")

    def _on_log(self, level: str, message: str) -> None:
        if level in ("warn", "error"):
            self._status.setText(message[:120])

    def _on_finished(self, results) -> None:
        records = [record for record, _dst in results]
        by_rel = {record.file: record for record in records}
        for item in self._items:
            if item.rel in by_rel:
                item.record = by_rel[item.rel]
        self._load_current()
        skipped = sum(1 for record in records if record.status == "skipped")
        failed = [record for record in records if record.status == "error"]
        if len(records) == 1:
            record = records[0]
            if record.status == "skipped":
                self._status.setText("没有需要重绘的区域，输出未改变")
            elif record.status == "error":
                self._status.setText(f"重新生成失败：{record.message}"[:180])
            else:
                self._status.setText(f"已重新生成 · {record.seconds:.1f}s")
        else:
            seconds = sum(float(record.seconds or 0.0) for record in records)
            done = len(records) - skipped - len(failed)
            text = (
                f"已重新生成 {done}/{len(records)} 张"
                f"（同一复用组）· {seconds:.1f}s"
            )
            if skipped:
                text += f" · {skipped} 张无需重绘"
            if failed:
                text += f" · {len(failed)} 张失败"
            self._status.setText(text)
        self.regenerated.emit(results)
        if failed:
            lines = "\n".join(f"{record.file}：{record.message}" for record in failed[:5])
            if len(failed) > 5:
                lines += f"\n…另有 {len(failed) - 5} 张"
            QMessageBox.warning(self, "重新生成未全部完成", lines)

    def _on_failed(self, message: str) -> None:
        self._status.setText(f"重新生成失败：{message}"[:180])
        QMessageBox.warning(self, "重新生成失败", message)

    def _on_cancelled(self) -> None:
        self._status.setText("已停止重新生成，已完成的输出保持更新")

    # ------------------------------------------------------------------ masks
    def _edit_mask(self) -> bool:
        item = self._current()
        if item is None or not self._store.get("output_dir"):
            return False
        size = None
        if self._original is not None:
            size = (self._original.height(), self._original.width())
        if size is None:
            QMessageBox.warning(self, "无法编辑", "原图不可用")
            return False
        output_dir = self._store.get("output_dir")
        store = ManualMaskStore(output_dir)
        manual = store.load(item.rel)
        entry: PreflightEntry | None = None
        if self._preflight is not None:
            entry = self._preflight.entry(item.rel)
        auto_png = entry_mask_png(entry) if entry is not None else None
        auto = load_mask_like(auto_png, size)
        initial = manual if manual is not None and manual.shape == size else auto
        preflight = self._preflight
        rel = item.rel

        def _auto_provider():
            return preflight.auto_payload(rel, self._store.settings)

        try:
            dialog = MaskEditorDialog(
                item.input_path,
                auto_png,
                initial,
                self._palette,
                title=f"编辑遮罩 · {item.rel}",
                parent=self,
                auto_provider=_auto_provider if preflight is not None else None,
            )
        except ValueError as exc:
            QMessageBox.warning(self, "无法编辑", str(exc))
            return False
        dialog._manual_badge.setText("保存后处理时优先使用")
        if dialog.exec() != QDialog.Accepted:
            return False
        mask = dialog.result_mask()
        if mask is None:
            return False
        try:
            store.save(item.rel, mask)
        except OSError as exc:
            QMessageBox.warning(self, "保存失败", str(exc))
            return False
        if self._preflight is not None:
            applied = self._preflight.apply_manual(item.rel, mask)
            if applied is None:
                self._preflight.mark_manual(item.rel, True)
        self._group_cache = None
        self._status.setText("遮罩已保存，可重新生成")
        return True

    # ----------------------------------------------------------- postprocess
    def _open_postprocess(self) -> None:
        item = self._current()
        label = item.rel if item is not None else ""
        PostProcessDialog(self._palette, label, self).exec()

    def _open_output(self) -> None:
        item = self._current()
        if item is None:
            return
        folder = os.path.dirname(item.output_path)
        try:
            os.startfile(folder)  # type: ignore[attr-defined]
        except Exception:
            self._status.setText("输出目录不存在")

    # ------------------------------------------------------------------ close
    def closeEvent(self, event):  # noqa: N802
        if self._controller.running:
            answer = QMessageBox.question(
                self,
                "关闭对比",
                "正在重新生成，关闭会停止当前任务。确定吗？\n旧结果不会被覆盖。",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                event.ignore()
                return
            self._controller.stop()
            self._controller.wait(2.0)
        event.accept()
        # QDialog.finished is emitted from done()/reject().  Accepting the
        # close event alone leaves the dialog's owner believing it is still
        # open, which locked the workspace (preflight/compare) forever.
        super().closeEvent(event)


def _read_image(path: str) -> QImage | None:
    if not path or not os.path.isfile(path):
        return None
    image = QImage(path)
    return None if image.isNull() else image
