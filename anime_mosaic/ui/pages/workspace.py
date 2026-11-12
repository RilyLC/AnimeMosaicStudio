"""Workspace: folders, live progress, logs, results and output browser."""

from __future__ import annotations

import os

from PySide6.QtCore import QSignalBlocker, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ...core.discovery import count_images
from ...core.events import STAGE_LABELS, ProcessRecord, RunSummary
from ...core.settings import default_output_dir
from ...core.util import human_duration_short
from ...services.output_index import entry_from_paths, scan_outputs
from ...services.presets import (
    CUSTOM_PRESET_ID,
    preset_by_id,
    preset_values,
    resolve_preset_id,
    restore_preset_defaults,
)
from ..log_store import LogStore
from ..preflight.controller import PreflightController
from ..preflight.dialog import PreflightDialog
from ..results.compare import ResultCompareDialog
from ..results.controller import ResultItem
from ..state import SettingsStore
from ..tasks import TaskRunner
from ..theme import Palette
from ..widgets.base import Badge, Card, ElidedLabel, StatTile
from ..widgets.buttons import Button
from ..widgets.log_view import LogView
from ..widgets.output_results import OutputResultsPanel
from ..widgets.page import Page
from ..widgets.path_picker import PathPicker
from ..widgets.preset_picker import PresetPicker
from ..widgets.results import ResultsPanel
from ..widgets.segmented import SegmentedControl
from ..widgets.switch import Switch


class WorkspacePage(Page):
    navigate = Signal(int)
    notice = Signal(str, str)
    modelStatusChanged = Signal(str, bool)

    def __init__(
        self,
        store: SettingsStore,
        log_store: LogStore,
        runner: TaskRunner,
        palette: Palette,
        parent=None,
        detector_cache=None,
    ):
        super().__init__(spacing=8, margins=(0, 0, 6, 6))
        self.store = store
        self.log_store = log_store
        self.runner = runner
        self._palette = palette
        self._detector_cache = detector_cache
        self._syncing = False
        self._scan_token = 0
        self._scan_signature: tuple[str, str, bool] | None = None
        self._counts = {"processed": 0, "copied": 0, "skipped": 0, "errors": 0, "regions": 0}
        self._preflight_dialog: PreflightDialog | None = None
        self._compare_dialog: ResultCompareDialog | None = None
        self._last_result_rel: str | None = None
        self._model_name = ""
        self._model_ready = False
        self._output_token = 0
        self._output_signature: tuple[str, str, bool] | None = None
        self.preflight = PreflightController(
            self,
            detector_provider=(
                detector_cache.get if detector_cache is not None else None
            ),
        )
        self._path_timer = QTimer(self)
        self._path_timer.setSingleShot(True)
        self._path_timer.setInterval(320)
        self._path_timer.timeout.connect(self._apply_paths)

        self._build()
        self._connect()
        self.sync_from_store(store.settings)
        self._update_path_status()

    def set_model_status(self, name: str, ready: bool) -> None:
        self._model_name = name or ""
        self._model_ready = bool(ready)
        self.modelStatusChanged.emit(self._model_name, self._model_ready)

    def model_status(self) -> tuple[str, bool]:
        return self._model_name, self._model_ready

    # ------------------------------------------------------------------ build
    def _build(self) -> None:
        self._onboarding = Card(
            "四步开始",
            "第一次使用？按顺序完成即可，其他参数保持默认。",
            "zap",
            self._palette,
        )
        steps = QHBoxLayout()
        steps.setSpacing(18)
        steps.addWidget(self._step("1", "选择输入目录", "可以包含多层子文件夹"), 1)
        steps.addWidget(self._step("2", "确认输出目录", "默认创建 <输入目录>_uncensored"), 1)
        steps.addWidget(self._step("3", "点击预处理", "预处理图片并快速调整"), 1)
        steps.addWidget(self._step("4", "点击开始处理", "进度与日志实时显示在下方"), 1)
        self._onboarding.add_layout(steps)
        self.add(self._onboarding)

        paths = QHBoxLayout()
        paths.setSpacing(8)
        self.subdir_switch = Switch(self.store.settings.include_subdirs, self._palette)
        scope = QWidget()
        scope_layout = QHBoxLayout(scope)
        scope_layout.setContentsMargins(0, 0, 0, 0)
        scope_layout.setSpacing(6)
        scope_label = QLabel("含子目录")
        scope_label.setObjectName("Caption")
        scope_layout.addWidget(scope_label)
        scope_layout.addWidget(self.subdir_switch)
        self.input_picker = PathPicker(
            "输入目录",
            "支持 png / jpg / webp / bmp",
            "选择包含图片的文件夹",
            self._palette,
            header_extra=scope,
            compact=True,
            tone="plain",
        )
        self.output_picker = PathPicker(
            "输出目录",
            "保持与原目录完全相同的结构",
            "选择输出文件夹",
            self._palette,
            icon="save",
            compact=True,
            tone="plain",
        )
        paths.addWidget(self.input_picker, 1)
        paths.addWidget(self.output_picker, 1)
        self.add_layout(paths)

        self.preset_picker = PresetPicker(self._palette, self)

        self._progress_card = Card(
            "运行状态", "", "sparkles", self._palette
        )
        self._progress_card.set_dense()
        self._stage_badge = Badge("等待开始", "neutral")
        self._progress_card.add_action(self._stage_badge)
        self._current = ElidedLabel("尚未开始")
        self._current.setObjectName("Caption")
        self._progress_card.add(self._current)
        run_stats = QHBoxLayout()
        run_stats.setSpacing(8)
        self.stat_tiles = {
            "processed": StatTile("已处理", "0", "check", self._palette, compact=True),
            "copied": StatTile("已复制", "0", "copy", self._palette, compact=True),
            "skipped": StatTile("已跳过", "0", "minus", self._palette, compact=True),
            "errors": StatTile("失败", "0", "alert_circle", self._palette, compact=True),
            "regions": StatTile("重绘区域", "0", "grid", self._palette, compact=True),
        }
        for tile in self.stat_tiles.values():
            run_stats.addWidget(tile, 1)
        self._progress_card.add_layout(run_stats)
        self.add(self._progress_card)

        bottom = QHBoxLayout()
        bottom.setSpacing(12)
        self._output_card = Card(
            "运行输出", "日志、处理记录与输出结果", "logs", self._palette
        )
        self._output_card.set_dense()
        open_logs = Button("日志页", "link", "external", self._palette, size="sm")
        open_logs.clicked.connect(lambda: self.navigate.emit(4))
        self._output_card.add_action(open_logs)
        self._segment = SegmentedControl(
            ["实时日志", "处理记录", "输出结果"], self._palette
        )
        self._auto_scroll = Switch(True, self._palette)
        self._auto_label = QLabel("自动滚动")
        self._auto_label.setObjectName("Caption")
        self._clear_button = Button("清空", "ghost", "trash", self._palette, size="sm")
        self._clear_button.clicked.connect(self.log_store.clear)
        segment_row = QHBoxLayout()
        segment_row.setContentsMargins(0, 0, 0, 0)
        segment_row.setSpacing(8)
        segment_row.addWidget(self._segment, 0)
        segment_row.addStretch(1)
        segment_row.addWidget(self._auto_label)
        segment_row.addWidget(self._auto_scroll)
        segment_row.addWidget(self._clear_button)
        self._output_card.add_layout(segment_row)
        self._tab_stack = QStackedWidget()
        self._tab_stack.addWidget(self._build_log_tab())
        self._results = ResultsPanel(self._palette)
        self._tab_stack.addWidget(self._results)
        self._outputs_panel = OutputResultsPanel(self._palette)
        self._tab_stack.addWidget(self._outputs_panel)
        self._output_card.add(self._tab_stack, 1)
        self._output_card.setMinimumHeight(236)
        bottom.addWidget(self._output_card, 1)
        self.add_layout(bottom, 1)
        # Let the output card absorb spare vertical space instead of leaving a
        # gap below it; Page normally keeps a trailing stretch for top-aligned
        # pages, which is not useful here.
        self._layout.setStretch(self._layout.count() - 1, 0)

    def _build_log_tab(self) -> QWidget:
        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 6, 0, 0)
        layout.setSpacing(0)
        self.log_view = LogView(self._palette)
        layout.addWidget(self.log_view, 1)
        return wrapper

    def _step(self, number: str, title: str, description: str) -> QWidget:
        wrapper = QWidget()
        layout = QHBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        badge = QLabel(number)
        badge.setObjectName("StepNumber")
        badge.setAlignment(Qt.AlignCenter)
        badge.setFixedSize(26, 26)
        layout.addWidget(badge, 0, Qt.AlignTop)
        texts = QVBoxLayout()
        texts.setSpacing(1)
        title_label = QLabel(title)
        title_label.setObjectName("FormLabel")
        desc = QLabel(description)
        desc.setObjectName("FormHelp")
        desc.setWordWrap(True)
        texts.addWidget(title_label)
        texts.addWidget(desc)
        layout.addLayout(texts, 1)
        return wrapper

    def _connect(self) -> None:
        self.input_picker.pathChanged.connect(self._on_path_text)
        self.output_picker.pathChanged.connect(self._on_path_text)
        self.subdir_switch.toggled.connect(self._on_subdirs_toggled)
        self.preset_picker.changed.connect(self._on_preset_selected)
        self.preset_picker.restoreRequested.connect(self._on_restore_preset)
        self.store.changed.connect(self._on_store_changed)
        self.store.replaced.connect(self.sync_from_store)
        self.log_store.appended.connect(self.log_view.append_entry)
        self.log_store.cleared.connect(self.log_view.clear)
        self._auto_scroll.toggled.connect(self.log_view.set_auto_scroll)
        self._segment.currentChanged.connect(self._on_tab_changed)
        self._results.activated.connect(lambda record: self.open_compare(record.file))
        self._outputs_panel.compareRequested.connect(
            lambda entry: self.open_compare(entry.rel)
        )
        self._outputs_panel.refreshRequested.connect(
            lambda: self._refresh_outputs(force=True)
        )
        self.preflight.log.connect(self.log_store.add)

    # ---------------------------------------------------------------- paths
    def _on_path_text(self, _path: str) -> None:
        if self._syncing:
            return
        self._path_timer.start()

    def _apply_paths(self) -> None:
        if self._syncing:
            return
        settings = self.store.settings
        old_input = settings.input_dir
        input_dir = self.input_picker.path()
        output_dir = self.output_picker.path()

        if input_dir != old_input:
            self.store.set("input_dir", input_dir)

        if input_dir and input_dir != old_input:
            if not output_dir or output_dir == default_output_dir(old_input):
                output_dir = default_output_dir(input_dir)
                self._syncing = True
                try:
                    self.output_picker.set_path(output_dir)
                finally:
                    self._syncing = False
        if output_dir != self.store.settings.output_dir:
            self.store.set("output_dir", output_dir)

        self._update_path_status()
        self._schedule_scan()

    def _on_store_changed(self, key: str, value) -> None:
        if key in ("input_dir", "output_dir"):
            self._syncing = True
            try:
                if key == "input_dir":
                    self.input_picker.set_path(value)
                else:
                    self.output_picker.set_path(value)
            finally:
                self._syncing = False
            self._update_path_status()
            if key == "input_dir":
                self._reset_preflight()
            self._refresh_outputs()
        elif key == "include_subdirs":
            with QSignalBlocker(self.subdir_switch):
                self.subdir_switch.setChecked(bool(value))
            self.subdir_switch.set_position(1.0 if value else 0.0)
            self._schedule_scan()
            self._refresh_outputs()
            self._reset_preflight()
        elif key in (
            "size",
            "steps",
            "cfg",
            "grow",
            "preset",
        ):
            self._refresh_preset()

    def sync_from_store(self, settings) -> None:
        self._syncing = True
        try:
            self.input_picker.set_path(settings.input_dir)
            self.output_picker.set_path(settings.output_dir)
            with QSignalBlocker(self.subdir_switch):
                self.subdir_switch.setChecked(bool(settings.include_subdirs))
            self.subdir_switch.set_position(1.0 if settings.include_subdirs else 0.0)
        finally:
            self._syncing = False
        self._update_path_status()
        self._refresh_preset()
        self._schedule_scan()
        self._refresh_outputs()

    def _on_subdirs_toggled(self, checked: bool) -> None:
        if self._syncing:
            return
        self.store.set("include_subdirs", bool(checked))

    def _update_path_status(self) -> None:
        settings = self.store.settings
        input_dir = settings.input_dir
        if not input_dir:
            self.input_picker.set_status("未选择", "neutral")
        elif not os.path.isdir(input_dir):
            self.input_picker.set_status("目录不存在", "danger")

        output_dir = settings.output_dir
        conflict = settings.output_conflicts
        if conflict:
            self.output_picker.set_status("与输入相同", "danger")
        elif not output_dir:
            self.output_picker.set_status("未选择", "warn")
        elif input_dir and os.path.normcase(os.path.abspath(output_dir)) == os.path.normcase(
            os.path.abspath(default_output_dir(input_dir))
        ):
            self.output_picker.set_status("默认目录", "accent")
        else:
            self.output_picker.set_status("已就绪", "ok")

        self._onboarding.setVisible(not (input_dir and os.path.isdir(input_dir) and output_dir and not conflict))

    def _schedule_scan(self) -> None:
        settings = self.store.settings
        input_dir = settings.input_dir
        output_dir = settings.output_dir
        if not input_dir or not os.path.isdir(input_dir):
            self._scan_token += 1
            self._scan_signature = None
            self.input_picker.set_status("目录不存在" if input_dir else "未选择", "danger" if input_dir else "neutral")
            return
        signature = (input_dir, output_dir, settings.include_subdirs)
        if signature == self._scan_signature:
            return
        self._scan_signature = signature
        self._scan_token += 1
        token = self._scan_token
        include_subdirs = settings.include_subdirs
        self.input_picker.set_status("扫描中…", "neutral")
        self.runner.run(
            lambda: count_images(input_dir, output_dir, include_subdirs),
            lambda count: self._on_scan_done(token, input_dir, count),
            lambda _error: self._on_scan_failed(token),
        )

    def _on_scan_done(self, token: int, input_dir: str, count: int) -> None:
        if token != self._scan_token or input_dir != self.store.settings.input_dir:
            return
        self.input_picker.set_status(
            f"{count:,} 张" if count else "0 张",
            "ok" if count else "warn",
        )
        self._update_path_status()

    def _on_scan_failed(self, token: int) -> None:
        if token == self._scan_token:
            self.input_picker.set_status("扫描失败", "warn")

    # ------------------------------------------------------------- preflight
    def open_preflight(self) -> None:
        settings = self.store.settings
        if self._compare_dialog is not None:
            self.notice.emit("请先关闭结果对比窗口，再运行预处理", "warning")
            return
        if self.comparison_running():
            self.notice.emit("结果对比正在重新生成，请先完成或停止", "warning")
            return
        if not settings.input_dir or not os.path.isdir(settings.input_dir):
            self.notice.emit("请先选择输入目录", "error")
            return
        if not settings.output_dir:
            self.notice.emit("预处理需要输出目录来保存手动遮罩", "warning")
            return
        if settings.output_conflicts:
            self.notice.emit("输出目录不能与输入目录相同", "error")
            return
        if self._preflight_dialog is not None:
            self._preflight_dialog.show()
            self._preflight_dialog.raise_()
            self._preflight_dialog.activateWindow()
            return
        dialog = PreflightDialog(self.preflight, self.store, self._palette, self.window())
        dialog.finished.connect(lambda _result: self._on_preflight_closed())
        self._preflight_dialog = dialog
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _on_preflight_closed(self) -> None:
        self._preflight_dialog = None

    def preflight_ready(self) -> bool:
        """True only when every input image has a fresh preprocessing result."""
        settings = self.store.settings
        if self.preflight.running or not self.preflight.has_results():
            return False
        if self.preflight.dirty or self.preflight.is_stale(settings):
            return False
        summary = self.preflight.summary()
        total = int(summary.get("total") or 0)
        return total > 0 and int(summary.get("scanned") or 0) >= total

    def _reset_preflight(self) -> None:
        if self.preflight.running:
            self.preflight.stop()
        elif self.preflight.has_results():
            self.preflight.clear()

    def shutdown(self) -> None:
        if self._compare_dialog is not None:
            if self._compare_dialog.is_regenerating():
                self._compare_dialog._controller.stop()
                self._compare_dialog._controller.wait(2.0)
            self._compare_dialog.close()
            self._compare_dialog = None
        if self.preflight.running:
            self.preflight.stop()
            self.preflight.wait(2.0)

    # --------------------------------------------------------------- outputs
    def _refresh_outputs(self, force: bool = False) -> None:
        settings = self.store.settings
        input_dir = settings.input_dir
        output_dir = settings.output_dir
        if not input_dir or not os.path.isdir(input_dir) or not output_dir:
            self._output_token += 1
            self._output_signature = None
            self._outputs_panel.set_loading(False)
            self._outputs_panel.set_entries([], 0)
            return
        signature = (input_dir, output_dir, settings.include_subdirs)
        if not force and signature == self._output_signature:
            return
        self._output_signature = signature
        self._output_token += 1
        token = self._output_token
        include_subdirs = settings.include_subdirs
        self._outputs_panel.set_loading(True)
        self.runner.run(
            lambda: scan_outputs(input_dir, output_dir, include_subdirs),
            lambda scan: self._on_outputs_scanned(token, signature, scan),
            lambda error: self._on_outputs_failed(token, signature, error),
        )

    def _on_outputs_scanned(self, token: int, signature, scan) -> None:
        if token != self._output_token or signature != self._output_signature:
            return
        self._outputs_panel.set_loading(False)
        self._outputs_panel.set_entries(scan.entries, scan.total_input)
        if self._last_result_rel:
            self._outputs_panel.set_current_rel(self._last_result_rel)

    def _on_outputs_failed(self, token: int, signature, error) -> None:
        if token != self._output_token or signature != self._output_signature:
            return
        self._outputs_panel.set_loading(False)
        self.log_store.add("WARN", f"扫描输出目录失败：{error}")

    def _compare_items(self) -> list[ResultItem]:
        records = {record.file: record for record in self._results.model.records()}
        items: list[ResultItem] = []
        for entry in self._outputs_panel.entries():
            items.append(
                ResultItem(
                    rel=entry.rel,
                    input_path=entry.input_path,
                    output_path=entry.output_path,
                    record=records.get(entry.rel),
                )
            )
        return items

    def open_compare(self, rel: str | None = None) -> None:
        if self.preflight.running:
            self.notice.emit("预识别正在运行，请稍候再查看结果对比", "warning")
            return
        items = self._compare_items()
        if not items:
            # The directory scan is asynchronous; a just-finished result may be
            # clickable before the first scan callback arrives.
            settings = self.store.settings
            for record in self._results.model.records():
                output_path = os.path.join(settings.output_dir, record.file)
                if os.path.isfile(output_path):
                    items.append(
                        ResultItem(
                            rel=record.file,
                            input_path=os.path.join(settings.input_dir, record.file),
                            output_path=output_path,
                            record=record,
                        )
                    )
        if not items:
            self.notice.emit("还没有可对比的输出，先处理图片或等待当前批次完成", "info")
            return
        target_rel = rel
        if target_rel is None:
            target_rel = self._last_result_rel
        available = {item.rel for item in items}
        if target_rel is not None and target_rel not in available:
            if rel is not None:
                self.notice.emit("输出文件不存在，无法对比", "warning")
                return
            target_rel = None
        if target_rel is None:
            selected = self._outputs_panel.selected_entry()
            target_rel = selected.rel if selected is not None else items[-1].rel
        index = next(
            (position for position, item in enumerate(items) if item.rel == target_rel),
            None,
        )
        if index is None:
            self.notice.emit("输出文件不存在，无法对比", "warning")
            return
        if self._compare_dialog is not None:
            if rel is None:
                self._compare_dialog.show()
                self._compare_dialog.raise_()
                self._compare_dialog.activateWindow()
                return
            if self._compare_dialog.select_rel(rel):
                self._compare_dialog.show()
                self._compare_dialog.raise_()
                self._compare_dialog.activateWindow()
                return
            if self._compare_dialog.is_regenerating():
                self.notice.emit("正在重新生成，请稍候再切换结果", "warning")
                return
            self._compare_dialog.close()
            self._compare_dialog = None
        dialog = ResultCompareDialog(
            items,
            index,
            self.store,
            self._palette,
            self.preflight,
            self.window(),
            detector_provider=(
                self._detector_cache.get
                if self._detector_cache is not None
                else None
            ),
        )
        dialog.log.connect(self.log_store.add)
        dialog.regenerated.connect(self._on_regenerated)
        dialog.finished.connect(lambda _result: self._on_compare_closed())
        self._compare_dialog = dialog
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _on_compare_closed(self) -> None:
        self._compare_dialog = None

    def _on_regenerated(self, results) -> None:
        if not results:
            return
        settings = self.store.settings
        self._output_token += 1  # a live result supersedes an in-flight scan
        self._outputs_panel.set_loading(False)
        current_rel = ""
        updated = 0
        skipped = 0
        failed = 0
        for record, dst in results:
            self._results.update_record(record.file, record)
            if record.status == "error":
                failed += 1
                continue
            if record.status == "skipped":
                skipped += 1
                continue
            updated += 1
            current_rel = current_rel or record.file
            self._last_result_rel = record.file
            if not os.path.isfile(dst):
                continue
            status = record.status if record.status in ("processed", "copied") else "unknown"
            entry = entry_from_paths(
                record.file,
                settings.input_dir,
                dst,
                status=status,
                reused=bool(record.reused),
            )
            if entry is not None:
                self._outputs_panel.upsert(entry)
        if current_rel:
            self._outputs_panel.set_current_rel(current_rel)
        if not updated:
            if failed:
                self.notice.emit(f"重新生成失败 {failed} 张，输出保持不变", "error")
            else:
                self.notice.emit("没有需要重绘的区域，输出保持不变", "info")
            return
        if updated == 1:
            record = next(
                rec for rec, _dst in results if rec.status in ("processed", "copied")
            )
            self.notice.emit(
                f"已重新生成 {record.file}（{record.seconds:.1f}s）", "success"
            )
        else:
            text = f"已重新生成 {updated} 张（同一复用组）"
            if failed:
                text += f" · {failed} 张失败"
            self.notice.emit(text, "warning" if failed else "success")

    def comparison_running(self) -> bool:
        return self._compare_dialog is not None and self._compare_dialog.is_regenerating()

    def _on_preset_selected(self, preset_id: str) -> None:
        if self._syncing:
            return
        preset = preset_by_id(preset_id)
        if preset is None:
            return
        values = preset_values(self.store.settings, preset_id)
        self.store.update({"preset": preset_id, **values})
        if preset_id == CUSTOM_PRESET_ID:
            self.notice.emit("已切换到「自定义」", "info")
        else:
            self.notice.emit(f"已应用「{preset.label}」预设", "success")

    def _on_restore_preset(self, preset_id: str) -> None:
        if self._syncing:
            return
        settings = self.store.settings
        applied = restore_preset_defaults(settings, preset_id)
        if applied == settings:
            return
        changes = {
            key: getattr(applied, key)
            for key in applied.to_mapping()
            if getattr(applied, key) != getattr(settings, key)
        }
        self.store.update(changes)
        preset = preset_by_id(preset_id)
        if preset is not None:
            self.notice.emit(f"「{preset.label}」已恢复默认值", "success")

    def _refresh_preset(self) -> None:
        preset_id = resolve_preset_id(self.store.settings)
        preset = preset_by_id(preset_id)
        self.preset_picker.set_current(preset_id)
        self.preset_picker.setToolTip(
            preset.description if preset else "手动调整过的参数"
        )

    # ------------------------------------------------------------- run state
    def begin_run(self) -> None:
        if self._compare_dialog is not None:
            self._compare_dialog.close()
            self._compare_dialog = None
        self._last_result_rel = None
        self._counts = {"processed": 0, "copied": 0, "skipped": 0, "errors": 0, "regions": 0}
        self._render_counts()
        self._results.clear()
        self._results.clear_processing()
        self._segment.set_text(1, "处理记录")
        self._segment.set_current(0)
        self._tab_stack.setCurrentIndex(0)
        self._stage_badge.set_state("运行中", "accent")
        self._current.setText("正在连接 ComfyUI…")

    def handle_stage(self, rel_path: str, stage: str, detail: str) -> None:
        label = STAGE_LABELS.get(stage, stage)
        suffix = f" · {detail}" if detail else ""
        self._current.setText(f"{label}{suffix} · {rel_path}" if rel_path else f"{label}{suffix}")
        if rel_path:
            image_path = os.path.join(self.store.settings.input_dir, rel_path)
            self._results.set_processing(rel_path, f"{label}{suffix}", image_path)
        else:
            self._results.clear_processing()

    def handle_progress(self, done: int, total: int, rel_path: str, speed: float, eta: float) -> None:
        self._current.setText(f"第 {done} / {total} 张 · {rel_path}")

    def handle_result(self, record: ProcessRecord, dst_path: str) -> None:
        self._results.append(record)
        count = len(self._results.model.records())
        self._segment.set_text(1, f"处理记录 ({count})")
        if record.status == "processed":
            self._counts["processed"] += 1
            self._counts["regions"] += record.regions
        elif record.status == "copied":
            self._counts["copied"] += 1
        elif record.status == "skipped":
            self._counts["skipped"] += 1
        elif record.status == "error":
            self._counts["errors"] += 1
        self._render_counts()
        if record.status in ("processed", "copied") and os.path.isfile(dst_path):
            self._last_result_rel = record.file
            self._output_token += 1  # a live result supersedes an in-flight scan
            self._outputs_panel.set_loading(False)
            status = record.status if record.status in ("processed", "copied") else "unknown"
            entry = entry_from_paths(
                record.file,
                self.store.settings.input_dir,
                dst_path,
                status=status,
                reused=bool(record.reused),
            )
            if entry is not None:
                self._outputs_panel.upsert(entry)
                self._outputs_panel.set_current_rel(record.file)

    def handle_done(self, summary: RunSummary) -> None:
        self._counts = {
            "processed": summary.processed,
            "copied": summary.copied,
            "skipped": summary.skipped,
            "errors": summary.errors,
            "regions": summary.regions,
        }
        self._results.clear_processing()
        self._render_counts()
        if summary.stopped:
            self._stage_badge.set_state("已停止", "warn")
            self._current.setText(f"已停止 · 用时 {human_duration_short(summary.elapsed)}")
        else:
            self._stage_badge.set_state("已完成", "ok")
            self._current.setText(
                f"完成 {summary.total} 张 · 用时 {human_duration_short(summary.elapsed)}"
            )
        self._refresh_outputs(force=True)

    def handle_failed(self, message: str) -> None:
        self._results.clear_processing()
        self._stage_badge.set_state("已中止", "danger")
        self._current.setText(message)

    def _render_counts(self) -> None:
        for key, tile in self.stat_tiles.items():
            tile.set_value(f"{self._counts.get(key, 0):,}")

    def _on_tab_changed(self, index: int) -> None:
        self._tab_stack.setCurrentIndex(index)
        log_tab = index == 0
        self._auto_label.setVisible(log_tab)
        self._auto_scroll.setVisible(log_tab)
        self._clear_button.setVisible(log_tab)
        if index == 1:
            self._results.view.scrollToBottom()
        elif index == 2:
            self._refresh_outputs()

    # -------------------------------------------------------------- palette
    def apply_palette(self, palette: Palette) -> None:
        self._palette = palette
        self.input_picker.set_palette(palette)
        self.output_picker.set_palette(palette)
        self.subdir_switch.set_palette(palette)
        for tile in self.stat_tiles.values():
            tile.set_palette(palette)
        self.preset_picker.set_palette(palette)
        self.log_view.set_palette(palette)
        self.log_view.reload(self.log_store.entries)
        self._results.set_palette(palette)
        self._outputs_panel.set_palette(palette)
        self._auto_scroll.set_palette(palette)
        for button in (self._clear_button,):
            button.set_palette(palette)
        if self._preflight_dialog is not None:
            self._preflight_dialog._refresh_palette(palette)
        if self._compare_dialog is not None:
            self._compare_dialog.apply_palette(palette)
