"""Application shell: sidebar, header, page stack, action bar and wiring."""

from __future__ import annotations

import os

from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from ..core.events import STAGE_LABELS, RunSummary
from ..core.settings import CONFIG_PATH, Settings
from ..core.util import human_time
from ..logging_setup import get_logger
from ..services.detector_cache import DetectorCache
from ..services.environment import probe_connection
from . import branding
from .controller import PipelineController
from .log_store import LogStore
from .pages.about import AboutPage
from .pages.logs import LogsPage
from .pages.prompts import PromptsPage
from .pages.settings_page import SettingsPage
from .pages.tuning import TuningPage
from .pages.workspace import WorkspacePage
from .setup_dialog import SetupDialog
from .state import SettingsStore
from .tasks import TaskRunner
from .theme import ThemeManager, Palette
from .widgets.base import ElidedLabel
from .widgets.buttons import Button
from .widgets.sidebar import Sidebar
from .widgets.toast import ToastManager

PAGE_META = (
    ("工作台", "把一整批图片交给 ComfyUI，只重绘被遮挡的地方"),
    ("参数", "微调检测、采样、裁切与融合；不确定时先用预设"),
    ("提示词", "告诉模型要什么、不要什么"),
    ("设置", "连接 ComfyUI、选择模型、配置输出行为"),
    ("运行日志", "完整的运行记录，可筛选、搜索与复制"),
    ("关于", "项目简介、处理流程与开源许可"),
)


class MainWindow(QMainWindow):
    def __init__(
        self,
        store: SettingsStore,
        theme: ThemeManager,
        auto_probe: bool = True,
        persist: bool = True,
    ):
        super().__init__()
        self.store = store
        self.theme = theme
        self._persist = persist
        self._palette: Palette = theme.palette
        self._logger = get_logger()
        self._ui_settings = QSettings("AnimeMosaicStudio", "AnimeMosaicStudio")
        self._probe_url = store.get("comfy_url")
        self.logs = LogStore(parent=self)
        self.runner = TaskRunner(self)
        self.detector_cache = DetectorCache()
        self.controller = PipelineController(self.detector_cache.get, self)
        self._url_timer = QTimer(self)
        self._url_timer.setSingleShot(True)
        self._url_timer.setInterval(700)
        self._url_timer.timeout.connect(self.probe_comfy)
        self._probe_timer = QTimer(self)
        self._probe_timer.setInterval(8000)
        self._probe_timer.timeout.connect(lambda: self.probe_comfy(silent=True))
        self._probe_busy = False
        self._last_probe_state = ""
        self._last_probe_version = ""
        self._pending_start = False

        self.setWindowTitle("AnimeMosaicStudio · 自动去马赛克")
        self.setObjectName("Root")
        self._build()
        self._connect()
        self._restore_geometry()
        self._refresh_theme(self.theme.mode, apply=False)
        self._greet()

        if auto_probe:
            QTimer.singleShot(420, self.probe_comfy)
            QTimer.singleShot(900, self.preload_detectors)
            self._probe_timer.start()

        if persist:
            QTimer.singleShot(0, self._maybe_first_run)

    # ----------------------------------------------------------------- build
    def _build(self) -> None:
        root = QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.sidebar = Sidebar(self._palette)
        layout.addWidget(self.sidebar)

        main = QVBoxLayout()
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(0)
        layout.addLayout(main, 1)

        main.addWidget(self._build_header())

        self.stack = QStackedWidget()
        self.stack.addWidget(
            WorkspacePage(
                self.store,
                self.logs,
                self.runner,
                self._palette,
                detector_cache=self.detector_cache,
            )
        )
        self.stack.addWidget(TuningPage(self.store, self._palette))
        self.stack.addWidget(PromptsPage(self.store, self._palette))
        self.stack.addWidget(SettingsPage(self.store, self.runner, self._palette))
        self.stack.addWidget(LogsPage(self.logs, self._palette))
        self.stack.addWidget(AboutPage(self._palette))
        stack_host = QWidget()
        stack_layout = QVBoxLayout(stack_host)
        stack_layout.setContentsMargins(28, 0, 28, 0)
        stack_layout.setSpacing(0)
        stack_layout.addWidget(self.stack)
        main.addWidget(stack_host, 1)

        self.workspace: WorkspacePage = self.stack.widget(0)
        main.addWidget(self._build_action_bar())
        self.tuning: TuningPage = self.stack.widget(1)
        self.prompts: PromptsPage = self.stack.widget(2)
        self.settings_page: SettingsPage = self.stack.widget(3)
        self.logs_page: LogsPage = self.stack.widget(4)
        self.about_page: AboutPage = self.stack.widget(5)

        self.toasts = ToastManager(self, self._palette)
        self.go_to(0, save=False)

    def _build_header(self) -> QWidget:
        header = QFrame()
        header.setObjectName("Header")
        header.setContentsMargins(28, 20, 28, 12)
        layout = QHBoxLayout(header)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        titles = QVBoxLayout()
        titles.setSpacing(2)
        self._title = QLabel("工作台")
        self._title.setObjectName("PageTitle")
        self._subtitle = QLabel("")
        self._subtitle.setObjectName("PageSubtitle")
        titles.addWidget(self._title)
        titles.addWidget(self._subtitle)
        layout.addLayout(titles, 1)

        self._open_output_button = Button("打开输出", "ghost", "external", self._palette)
        self._open_output_button.clicked.connect(self._open_output)
        layout.addWidget(self._open_output_button, 0, Qt.AlignVCenter)
        return header

    def _build_action_bar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("ActionBar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(28, 8, 28, 8)
        layout.setSpacing(12)

        status = QVBoxLayout()
        status.setSpacing(2)
        status.setContentsMargins(0, 0, 0, 0)
        self._stage_label = QLabel("就绪")
        self._stage_label.setObjectName("CardTitle")
        status.addWidget(self._stage_label)
        self._file_label = ElidedLabel("选择输入与输出目录后开始处理")
        self._file_label.setObjectName("Caption")
        self._file_label.setMinimumWidth(220)
        self._file_label.setMaximumWidth(300)
        status.addWidget(self._file_label)
        layout.addLayout(status, 0)

        progress_box = QVBoxLayout()
        progress_box.setSpacing(5)
        self._progress = QProgressBar()
        self._progress.setRange(0, 1)
        self._progress.setValue(0)
        self._progress.setTextVisible(False)
        progress_box.addWidget(self._progress)
        meta = QHBoxLayout()
        meta.setSpacing(10)
        self._count_label = QLabel("0 / 0")
        self._count_label.setObjectName("Caption")
        meta.addWidget(self._count_label)
        meta.addStretch(1)
        self._eta_label = QLabel("")
        self._eta_label.setObjectName("Caption")
        meta.addWidget(self._eta_label)
        progress_box.addLayout(meta)
        layout.addLayout(progress_box, 1)

        self._preset_picker = self.workspace.preset_picker
        layout.addWidget(self._preset_picker, 0)

        self._preflight_button = Button("预处理", "primary", "scan", self._palette)
        self._preflight_button.setMinimumWidth(108)
        self._preflight_button.setToolTip("调整检测参数、检查遮罩并手动编辑")
        self._preflight_button.clicked.connect(self.workspace.open_preflight)
        layout.addWidget(self._preflight_button, 0)

        self._run_button = Button("开始处理", "primary", "play", self._palette, size="lg")
        self._run_button.setMinimumWidth(132)
        self._run_button.clicked.connect(self._toggle_run)
        layout.addWidget(self._run_button, 0)
        return bar

    # --------------------------------------------------------------- wiring
    def _connect(self) -> None:
        self.sidebar.navigate.connect(self.go_to)
        self.sidebar.themeToggled.connect(self.toggle_theme)

        self.workspace.navigate.connect(self.go_to)
        self.workspace.notice.connect(self.toasts.show)
        self.workspace.preflight.stateChanged.connect(self._on_preflight_state)
        self.workspace.preflight.itemReady.connect(
            lambda *_: self._refresh_preflight_button()
        )
        self.workspace.preflight.progress.connect(
            lambda *_: self._refresh_preflight_button()
        )
        self.workspace.preflight.finished.connect(
            lambda *_: self._refresh_preflight_button()
        )
        self.workspace.preflight.failed.connect(
            lambda *_: self._refresh_preflight_button()
        )
        self.workspace.preflight.itemsChanged.connect(self._refresh_preflight_button)
        self.workspace.modelStatusChanged.connect(
            lambda *_: self._refresh_preflight_button()
        )
        self.tuning.notice.connect(self.toasts.show)
        self.prompts.notice.connect(self.toasts.show)
        self.settings_page.notice.connect(self.toasts.show)
        self.settings_page.setupRequested.connect(self.open_setup_wizard)

        self.store.changed.connect(self._on_store_changed)
        self.store.replaced.connect(self._on_settings_replaced)
        self.logs.appended.connect(self._log_to_file)

        self.controller.log.connect(self._handle_log)
        self.controller.stage.connect(self._handle_stage)
        self.controller.progress.connect(self._handle_progress)
        self.controller.result.connect(self.workspace.handle_result)
        self.controller.done.connect(self._handle_done)
        self.controller.failed.connect(self._handle_failed)
        self.controller.runningChanged.connect(self._on_running_changed)

        self._shortcuts: list[QShortcut] = []
        for index in range(6):
            self._shortcuts.append(self._shortcut(f"Ctrl+{index + 1}", lambda i=index: self.go_to(i)))
        self._shortcuts.append(self._shortcut("Ctrl+Return", self.start_run))
        self._shortcuts.append(self._shortcut("Escape", self.stop_run))
        self._shortcuts.append(self._shortcut("Ctrl+S", self._save_now))
        self._shortcuts.append(self._shortcut("Ctrl+L", self.logs.clear))
        self._shortcuts.append(self._shortcut("Ctrl+,", lambda: self.go_to(3)))
        self._refresh_preflight_button()

    def _shortcut(self, sequence: str, callback) -> QShortcut:
        shortcut = QShortcut(QKeySequence(sequence), self)
        shortcut.activated.connect(callback)
        return shortcut

    def _greet(self) -> None:
        self.logs.add("info", f"欢迎使用 AnimeMosaicStudio {__version__}")
        self.logs.add("info", f"配置文件：{CONFIG_PATH}")
        self.logs.add("success", "选择输入 / 输出目录，然后点击右下角“预处理”，完成后点击开始。")

    # ---------------------------------------------------------- first run
    def _maybe_first_run(self) -> None:
        # A hand-written python_exe is not "configured": the wizard exists to
        # fill in the paths the app cannot work without, and that is mainly the
        # ComfyUI folder.  Only skip it once that folder is known.
        if (self.store.settings.comfy_dir or "").strip():
            return
        self.open_setup_wizard(first_run=True)

    def open_setup_wizard(self, first_run: bool = False) -> None:
        dialog = SetupDialog(self.store, self._palette, self, first_run=first_run)
        if dialog.exec() != QDialog.Accepted:
            return
        self.settings_page.sync_from_store()
        self._refresh_preflight_button()
        self.toasts.show("设置已保存；记得先启动 ComfyUI", "success", 2600)

    # -------------------------------------------------------------- models
    def preload_detectors(self) -> None:
        """Warm the shared detector cache without blocking the first paint."""
        self.logs.add("info", "正在后台预加载检测模型…")
        self.runner.run(
            lambda: self.detector_cache.get(self.store.settings),
            self._on_detectors_loaded,
            self._on_detectors_failed,
        )

    def _on_detectors_loaded(self, value) -> None:
        name = value[2] if value else ""
        self.logs.add("success", f"检测模型已就绪：{name or '已加载'}")
        self.workspace.set_model_status(name, ready=True)

    def _on_detectors_failed(self, message: str) -> None:
        self.logs.add("warn", f"检测模型预加载失败：{message}")
        self.workspace.set_model_status("", ready=False)

    # -------------------------------------------------------------- navigation
    def go_to(self, index: int, save: bool = True) -> None:
        index = max(0, min(len(PAGE_META) - 1, int(index)))
        self.stack.setCurrentIndex(index)
        self.sidebar.set_active(index)
        title, subtitle = PAGE_META[index]
        self._title.setText(title)
        self._subtitle.setText(subtitle)
        if save and self._persist:
            self._ui_settings.setValue("page", index)

    def _on_store_changed(self, key: str, value) -> None:
        self._refresh_preflight_button()
        if key == "comfy_url":
            self._url_timer.start()

    def _on_settings_replaced(self, settings: Settings) -> None:
        self._refresh_preflight_button()
        if settings.comfy_url != self._probe_url:
            self._url_timer.start()

    def _log_to_file(self, entry) -> None:
        import logging

        level = {
            "error": logging.ERROR,
            "warn": logging.WARNING,
            "debug": logging.DEBUG,
            "success": logging.INFO,
        }.get(entry.level, logging.INFO)
        self._logger.log(level, entry.message)

    def _save_now(self) -> None:
        self.store.save_now()
        self.toasts.show("设置已保存", "success", 1800)

    # ------------------------------------------------------------------- run
    def _toggle_run(self) -> None:
        if self.controller.running:
            self.stop_run()
        else:
            self.start_run()

    def start_run(self, require_preflight: bool = True) -> None:
        if self.controller.running:
            return
        settings = self.store.settings
        if require_preflight and not self.workspace.preflight_ready():
            if self.workspace.preflight.running:
                self.toasts.show("预处理尚未完成，请等待完成或先在预处理窗口停止", "warning")
            elif self.workspace.preflight.dirty:
                self.toasts.show("有图片或手动遮罩已变化，请在预处理窗口点“继续预处理”", "warning")
                self.workspace.open_preflight()
            elif self.workspace.preflight.has_results() and self.workspace.preflight.is_stale(settings):
                self.toasts.show("检测参数已变化，请继续预处理后再开始处理", "warning")
                self.workspace.open_preflight()
            else:
                self.toasts.show("开始处理前需要先完成预处理", "warning")
                self.workspace.open_preflight()
            return
        problems = settings.validate()
        if problems:
            problem = problems[0]
            self.toasts.show(problem.message, "error")
            self.go_to(self._page_for_field(problem.field))
            return
        if not settings.mosaic_model or not os.path.isfile(settings.mosaic_model):
            self.toasts.show("找不到马赛克检测模型，请到“设置 → 检测模型”指定", "error")
            self.go_to(3)
            return
        if settings.nsfw_mode != "off" and (
            not settings.nsfw_model or not os.path.isfile(settings.nsfw_model)
        ):
            self.toasts.show("NSFW 辅助已开启，但找不到 NSFW 模型", "error")
            self.go_to(3)
            return
        if self.workspace.comparison_running():
            self.toasts.show("结果对比正在重新生成，请等待完成或先停止", "warning")
            return

        self.store.save_now()
        self.workspace.begin_run()
        self._progress.setRange(0, 1)
        self._progress.setValue(0)
        self._count_label.setText("0 / 0")
        self._eta_label.setText("")
        self._stage_label.setText("准备中…")
        self._file_label.setText("正在读取目录与模型…")
        self.go_to(0)
        self.logs.add("info", "=" * 24 + " 开始新任务 " + "=" * 24)
        if not self.controller.start(settings):
            self.toasts.show("任务已经在运行", "warning")

    def stop_run(self) -> None:
        if not self.controller.running:
            return
        self.controller.stop()
        self._run_button.setEnabled(False)
        self._run_button.setText("停止中…")
        self._stage_label.setText("正在停止…")
        self._file_label.setText("当前图片不会被保存，下次运行会重新处理")

    def _on_preflight_state(self, running: bool) -> None:
        self._refresh_preflight_button()
        self._refresh_run_availability()

    def _refresh_run_availability(self) -> None:
        if not hasattr(self, "_run_button"):
            return
        if self.controller.running:
            self._run_button.setEnabled(True)
            self._run_button.setToolTip("停止当前批次")
            return
        ready = self.workspace.preflight_ready()
        self._run_button.setEnabled(ready)
        self._run_button.setToolTip(
            "开始处理" if ready else "先完成预处理，再开始处理"
        )

    def _refresh_preflight_button(self) -> None:
        if not hasattr(self, "_preflight_button"):
            return
        self._refresh_run_availability()
        settings = self.store.settings
        preflight = self.workspace.preflight
        name, ready = self.workspace.model_status()
        model_note = (
            f"检测模型：{name or '已就绪'}"
            if ready
            else "检测模型将在首次使用时加载"
        )
        if self.controller.running:
            self._preflight_button.setText("预处理")
            self._preflight_button.setEnabled(False)
            self._preflight_button.setToolTip("正在处理图片，完成或停止后可预处理")
            return
        if not settings.input_dir or not os.path.isdir(settings.input_dir):
            self._preflight_button.setText("预处理")
            self._preflight_button.setEnabled(False)
            self._preflight_button.setToolTip("先选择输入目录")
            return
        self._preflight_button.setEnabled(not preflight.running)
        if preflight.running:
            total = preflight.total
            done = preflight.done
            self._preflight_button.setText("处理中…")
            self._preflight_button.setToolTip(
                f"正在预处理 {done} / {total}\n{model_note}"
                if total
                else f"正在准备检测模型…\n{model_note}"
            )
            return
        if preflight.has_results():
            summary = preflight.summary()
            stale = preflight.is_stale(settings) or preflight.dirty
            self._preflight_button.setText(
                "继续预处理" if stale else f"预处理 {summary['scanned']}/{summary['total']}"
            )
            self._preflight_button.setToolTip(
                ("检测参数或图片有变化，点击继续预处理。" if stale else "点击查看全部检测结果并编辑遮罩。")
                + f"\n已编辑 {summary['edited']} 张 · {model_note}"
            )
            return
        self._preflight_button.setText("预处理")
        self._preflight_button.setToolTip(
            "先调检测参数，再查看全部图片的遮罩并手动编辑。\n" + model_note
        )

    def _on_running_changed(self, running: bool) -> None:
        self._run_button.setEnabled(True)
        if running:
            self._run_button.setText("停止")
            self._run_button.set_variant("danger")
            self._run_button.set_icon_name("stop")
            self._progress.setValue(0)
        else:
            self._run_button.setText("开始处理")
            self._run_button.set_variant("primary")
            self._run_button.set_icon_name("play")
        self._refresh_preflight_button()
        self._refresh_run_availability()

    def _handle_log(self, level: str, message: str) -> None:
        self.logs.add(level, message)

    def _handle_stage(self, rel_path: str, stage: str, detail: str) -> None:
        self.workspace.handle_stage(rel_path, stage, detail)
        label = STAGE_LABELS.get(stage, stage)
        self._stage_label.setText(label)
        if rel_path:
            self._file_label.setText(f"{rel_path}" + (f" · {detail}" if detail else ""))

    def _handle_progress(self, done: int, total: int, rel_path: str, speed: float, eta: float) -> None:
        self.workspace.handle_progress(done, total, rel_path, speed, eta)
        self._progress.setRange(0, max(1, total))
        self._progress.setValue(done)
        self._count_label.setText(f"{done} / {total}")
        self._eta_label.setText(f"{speed:.1f}s/张 · 剩余约 {human_time(eta)}")
        self._file_label.setText(rel_path)

    def _handle_done(self, summary: RunSummary) -> None:
        self.workspace.handle_done(summary)
        self._progress.setRange(0, max(1, summary.total))
        if not summary.stopped:
            self._progress.setValue(summary.total)
        self._count_label.setText(f"{self._progress.value()} / {summary.total}")
        self._eta_label.setText(f"总用时 {human_time(summary.elapsed)}")
        if summary.stopped:
            self._stage_label.setText("已停止")
            self._file_label.setText(
                f"处理 {summary.processed}，跳过 {summary.skipped}，失败 {summary.errors}"
            )
            self.toasts.show("任务已停止，已完成的图片会保留", "warning")
        else:
            self._stage_label.setText("已完成")
            self._file_label.setText(
                f"重绘 {summary.regions} 个区域 · 失败 {summary.errors} 张"
            )
            tone = "success" if summary.errors == 0 else "warning"
            self.toasts.show(
                f"处理完成：{summary.processed} 张，重绘 {summary.regions} 个区域，"
                f"用时 {human_time(summary.elapsed)}",
                tone,
                5000,
            )

    def _handle_failed(self, message: str) -> None:
        self.workspace.handle_failed(message)
        self._stage_label.setText("已中止")
        self._eta_label.setText("")
        self.toasts.show(f"任务中止：{message}", "error", 6000)

    def _page_for_field(self, field: str) -> int:
        if field in ("input_dir", "output_dir"):
            return 0
        if field in ("positive", "negative"):
            return 2
        if field in (
            "comfy_url",
            "comfy_dir",
            "mosaic_model",
            "nsfw_model",
            "unet_name",
            "clip_name",
            "vae_name",
            "lora_name",
        ):
            return 3
        return 1

    # ---------------------------------------------------------------- comfy
    def probe_comfy(self, silent: bool = False) -> None:
        if self._probe_busy:
            return
        url = self.store.get("comfy_url")
        self._probe_url = url
        self._probe_busy = True
        self.runner.run(
            lambda: probe_connection(url),
            lambda report: self._on_probe(report, silent),
            lambda message: self._on_probe_error(message, silent),
        )

    def _on_probe(self, report, silent: bool = False) -> None:
        self._probe_busy = False
        if report.connected:
            changed = (
                self._last_probe_state != "ok"
                or self._last_probe_version != report.version
            )
            self._last_probe_state = "ok"
            self._last_probe_version = report.version
            if changed or not silent:
                self.logs.add(
                    "success",
                    f"ComfyUI 已连接{f'（版本 {report.version}）' if report.version else ''}",
                )
        else:
            changed = self._last_probe_state != "error"
            self._last_probe_state = "error"
            self._last_probe_version = ""
            if changed or not silent:
                self.logs.add("warn", f"ComfyUI 未连接：{report.error},请检查设置")

    def _on_probe_error(self, message: str, silent: bool = False) -> None:
        self._probe_busy = False
        changed = self._last_probe_state != "error"
        self._last_probe_state = "error"
        self._last_probe_version = ""
        if changed or not silent:
            self.logs.add("warn", f"ComfyUI 连接检测失败：{message}")

    # --------------------------------------------------------------- actions
    def _open_output(self) -> None:
        path = self.store.get("output_dir")
        if path and os.path.isdir(path):
            try:
                os.startfile(path)  # type: ignore[attr-defined]
                return
            except Exception:
                pass
        self.toasts.show("输出目录还不存在，开始处理后会自动创建", "info")

    # ---------------------------------------------------------------- theme
    def toggle_theme(self) -> None:
        mode = self.theme.toggle()
        self._refresh_theme(mode, apply=True)
        if self._persist:
            self._ui_settings.setValue("theme", mode)

    def _refresh_theme(self, mode: str, apply: bool = True) -> None:
        palette = self.theme.apply(mode) if apply else self.theme.palette
        self._palette = palette
        self.setWindowIcon(branding.app_icon(palette))
        self.sidebar.apply_palette(palette)
        self.sidebar.set_theme_mode(mode)
        for page in (self.workspace, self.tuning, self.prompts, self.settings_page, self.about_page):
            page.apply_palette(palette)
        self.logs_page.apply_palette(palette)
        self._run_button.set_palette(palette)
        self._preflight_button.set_palette(palette)
        self._open_output_button.set_palette(palette)
        self.toasts.set_palette(palette)

    # -------------------------------------------------------------- geometry
    def _restore_geometry(self) -> None:
        geometry = self._ui_settings.value("geometry") if self._persist else None
        if geometry is not None:
            self.restoreGeometry(geometry)
        else:
            screen = self.screen().availableGeometry()
            width, height = 1360, min(900, screen.height() - 80)
            self.resize(width, height)
            frame = self.frameGeometry()
            frame.moveCenter(screen.center())
            self.move(frame.topLeft())
        self.setMinimumSize(1120, 740)
        page = self._ui_settings.value("page", 0) if self._persist else 0
        try:
            self.go_to(int(page), save=False)
        except (TypeError, ValueError):
            self.go_to(0, save=False)

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        if hasattr(self, "toasts"):
            self.toasts.reposition()

    def closeEvent(self, event):  # noqa: N802
        if self.controller.running:
            answer = QMessageBox.question(
                self,
                "退出",
                "任务还在运行，确定要退出吗？\n当前图片不会被保存。",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                event.ignore()
                return
            self.controller.stop()
        if self._persist:
            self.store.save_now()
            self._ui_settings.setValue("geometry", self.saveGeometry())
            self._ui_settings.setValue("page", self.stack.currentIndex())
            self._ui_settings.setValue("theme", self.theme.mode)
        self._pending_start = False
        self._probe_timer.stop()
        self._url_timer.stop()
        self.workspace.shutdown()
        self.controller.shutdown(2.0)
        event.accept()