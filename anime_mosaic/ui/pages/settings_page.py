"""Settings page: runtime interpreter, ComfyUI connection, models, detectors, output policy."""

from __future__ import annotations

import os
import platform
import sys

from PySide6.QtCore import QSignalBlocker, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
)

from ...core.settings import (
    APP_DIR,
    GROUP_FILES,
    LOG_PATH,
    Settings,
    spec_for,
    specs_in_group,
)
from ...services.environment import autodetect_paths, inspect_environment
from ..state import SettingsStore
from ..tasks import TaskRunner
from ..theme import Palette
from ..widgets.base import Card, StatusDot, repolish
from ..widgets.buttons import Button, IconButton
from ..widgets.fields import NumberField, PathRow, SwitchField
from ..widgets.page import Page

MODEL_ROWS = (
    ("unet_name", "UNet 模型", "anime-turbo-v1.1.safetensors"),
    ("clip_name", "文本编码器", "qwen_3_06b_base.safetensors"),
    ("vae_name", "VAE", "qwen_image_vae.safetensors"),
    ("lora_name", "Turbo LoRA", "uncensored_lora_v6-000034.safetensors"),
)


class SettingsPage(Page):
    notice = Signal(str, str)
    setupRequested = Signal()

    def __init__(self, store: SettingsStore, runner: TaskRunner, palette: Palette, parent=None):
        super().__init__(spacing=16)
        self.store = store
        self.runner = runner
        self._palette = palette
        self._syncing = False
        self._testing = False
        self._combos: dict[str, QComboBox] = {}
        self._switches: dict[str, SwitchField] = {}

        self._build()
        self._connect()
        self.sync_from_store(store.settings)

    # ----------------------------------------------------------------- build
    def _build(self) -> None:
        self.add(self._build_runtime())
        self.add(self._build_connection())
        self.add(self._build_models())
        self.add(self._build_detectors())
        self.add(self._build_output())
        self.add(self._build_maintenance())

    def _build_runtime(self) -> Card:
        card = Card(
            "运行环境",
            "启动器用哪个 Python 打开界面",
            "zap",
            self._palette,
        )
        self._python_row = PathRow(
            "Python 解释器",
            self.store.get("python_exe"),
            "file",
            "Python (python.exe pythonw.exe);;所有文件 (*.*)",
            self._palette,
        )
        self._python_row.pathChanged.connect(
            lambda path: self.store.set("python_exe", path)
        )
        card.add(self._python_row)

        row = QHBoxLayout()
        row.setSpacing(8)
        self._use_current = Button(
            "使用当前解释器", "secondary", "check", self._palette, size="sm"
        )
        self._use_current.clicked.connect(self._use_current_python)
        row.addWidget(self._use_current)
        row.addStretch(1)
        card.add_layout(row)

        self._runtime_caption = QLabel("")
        self._runtime_caption.setObjectName("Caption")
        self._runtime_caption.setWordWrap(True)
        card.add(self._runtime_caption)

        hint = QLabel(spec_for("python_exe").help)
        hint.setObjectName("FormHelp")
        hint.setWordWrap(True)
        card.add(hint)
        self._refresh_runtime_caption()
        return card

    def _use_current_python(self) -> None:
        self.store.set("python_exe", sys.executable)

    def _refresh_runtime_caption(self) -> None:
        configured = (self.store.get("python_exe") or "").strip()
        current = f"当前进程：{sys.executable}（Python {platform.python_version()}）"
        if configured:
            self._runtime_caption.setText(f"{current}\n启动器将使用：{configured}")
        else:
            self._runtime_caption.setText(
                f"{current}\n尚未指定：双击启动器时会弹出文件选择框，"
                "也可以点“使用当前解释器”或直接填写"
            )

    def _build_connection(self) -> Card:
        card = Card(
            "ComfyUI 连接", "桌面端通过 HTTP API 驱动 ComfyUI 工作流", "power", self._palette
        )
        row = QHBoxLayout()
        row.setSpacing(10)
        label = QLabel("服务地址")
        label.setObjectName("FormLabel")
        label.setFixedWidth(84)
        row.addWidget(label)
        self._url_edit = QLineEdit()
        self._url_edit.setPlaceholderText("http://127.0.0.1:8188")
        self._url_edit.setMinimumHeight(38)
        row.addWidget(self._url_edit, 1)
        self._test_button = Button("测试连接", "secondary", "refresh", self._palette)
        self._test_button.clicked.connect(self._test_connection)
        row.addWidget(self._test_button)
        card.add_layout(row)

        status = QHBoxLayout()
        status.setSpacing(8)
        self._conn_dot = StatusDot(9)
        status.addWidget(self._conn_dot)
        self._conn_label = QLabel("尚未检测")
        self._conn_label.setObjectName("ConnectionState")
        status.addWidget(self._conn_label)
        self._conn_detail = QLabel("")
        self._conn_detail.setObjectName("Caption")
        status.addWidget(self._conn_detail)
        status.addStretch(1)
        card.add_layout(status)

        hint = QLabel(
            "先启动 ComfyUI；如果它监听在其他端口，把地址改成对应端口即可。"
        )
        hint.setObjectName("FormHelp")
        hint.setWordWrap(True)
        card.add(hint)
        self._set_connection("idle", "尚未检测", "")
        return card

    def _build_models(self) -> Card:
        card = Card(
            "模型文件", "名称必须与 ComfyUI 的 models/ 目录中完全一致", "layers", self._palette
        )
        refresh = Button("从 ComfyUI 刷新", "link", "refresh", self._palette, size="sm")
        refresh.clicked.connect(self._test_connection)
        card.add_action(refresh)

        for key, label_text, placeholder in MODEL_ROWS:
            row = QHBoxLayout()
            row.setSpacing(10)
            label = QLabel(label_text)
            label.setObjectName("FormLabel")
            label.setFixedWidth(84)
            row.addWidget(label)
            combo = QComboBox()
            combo.setEditable(True)
            combo.setInsertPolicy(QComboBox.NoInsert)
            combo.setMinimumHeight(36)
            combo.lineEdit().setPlaceholderText(placeholder)
            combo.currentTextChanged.connect(
                lambda text, k=key: self._on_model_text(k, text)
            )
            self._combos[key] = combo
            row.addWidget(combo, 1)
            card.add_layout(row)

        self._lora_strength = NumberField(spec_for("lora_strength"), 0.33, self._palette)
        self._lora_strength.valueChanged.connect(lambda value: self.store.set("lora_strength", value))
        card.add(self._lora_strength)

        self._model_status = QLabel("")
        self._model_status.setObjectName("FormHelp")
        self._model_status.setWordWrap(True)
        self._model_status.hide()
        card.add(self._model_status)
        return card

    def _build_detectors(self) -> Card:
        card = Card(
            "检测模型", "YOLO 分割模型，决定哪些区域会被重绘", "cpu", self._palette
        )
        autodetect = Button("自动检测", "link", "wand", self._palette, size="sm")
        autodetect.clicked.connect(self._autodetect)
        card.add_action(autodetect)

        self._comfy_dir = PathRow("ComfyUI 目录", "", "dir", palette=self._palette)
        self._comfy_dir.pathChanged.connect(lambda path: self.store.set("comfy_dir", path))
        card.add(self._comfy_dir)

        self._mosaic_model = PathRow(
            "马赛克模型", "", "file", "YOLO 模型 (*.pt);;所有文件 (*.*)", self._palette
        )
        self._mosaic_model.pathChanged.connect(
            lambda path: self.store.set("mosaic_model", path)
        )
        card.add(self._mosaic_model)

        self._nsfw_model = PathRow(
            "NSFW 模型", "", "file", "YOLO 模型 (*.pt);;所有文件 (*.*)", self._palette
        )
        self._nsfw_model.pathChanged.connect(lambda path: self.store.set("nsfw_model", path))
        card.add(self._nsfw_model)

        self._imgsz = NumberField(spec_for("imgsz"), 1280, self._palette)
        self._imgsz.valueChanged.connect(lambda value: self.store.set("imgsz", value))
        card.add(self._imgsz)

        hint = QLabel(
            "“自动检测”只会在上面已填写的 ComfyUI 目录下的 models/ultralytics 里，"
            "查找包含 mosaic / nsfw 的 .pt 文件。"
        )
        hint.setObjectName("FormHelp")
        hint.setWordWrap(True)
        card.add(hint)
        return card

    def _build_output(self) -> Card:
        card = Card(
            "输出行为", "控制断点续跑与无马赛克图片的处理方式", "save", self._palette
        )
        for spec in specs_in_group(GROUP_FILES):
            widget = SwitchField(spec, bool(getattr(self.store.settings, spec.key)), self._palette)
            widget.valueChanged.connect(lambda value, key=spec.key: self.store.set(key, value))
            self._switches[spec.key] = widget
            card.add(widget)
        return card

    def _build_maintenance(self) -> Card:
        card = Card(
            "维护", "配置文件与日志都保存在程序目录，便于备份", "settings", self._palette
        )
        row = QHBoxLayout()
        row.setSpacing(8)
        open_config = Button("打开程序目录", "secondary", "folder", self._palette)
        open_config.clicked.connect(lambda: self._open_path(APP_DIR))
        row.addWidget(open_config)
        open_log = Button("打开日志", "secondary", "logs", self._palette)
        open_log.clicked.connect(lambda: self._open_path(LOG_PATH))
        row.addWidget(open_log)
        run_setup = Button("重新运行首次向导", "secondary", "wand", self._palette)
        run_setup.clicked.connect(self.setupRequested.emit)
        row.addWidget(run_setup)
        row.addStretch(1)
        reset = Button("恢复所有默认设置", "danger", "trash", self._palette)
        reset.clicked.connect(self._reset_all)
        row.addWidget(reset)
        card.add_layout(row)
        path = QLabel(f"配置：{os.path.join(APP_DIR, 'config.json')}")
        path.setObjectName("Mono")
        path.setWordWrap(True)
        card.add(path)
        return card

    # --------------------------------------------------------------- wiring
    def _connect(self) -> None:
        self._url_edit.editingFinished.connect(self._commit_url)
        self.store.changed.connect(self._on_store_changed)
        self.store.replaced.connect(self.sync_from_store)

    def _commit_url(self) -> None:
        url = self._url_edit.text().strip().rstrip("/")
        if url != self.store.get("comfy_url"):
            self.store.set("comfy_url", url or "http://127.0.0.1:8188")

    def _on_model_text(self, key: str, text: str) -> None:
        if self._syncing:
            return
        value = text.strip()
        if value and value != getattr(self.store.settings, key):
            self.store.set(key, value)

    def _on_store_changed(self, key: str, value) -> None:
        if key == "python_exe":
            self._python_row.set_path(value)
            self._refresh_runtime_caption()
        elif key == "comfy_url":
            with QSignalBlocker(self._url_edit):
                self._url_edit.setText(value)
        elif key in self._combos:
            combo = self._combos[key]
            with QSignalBlocker(combo):
                if combo.findText(value) >= 0:
                    combo.setCurrentIndex(combo.findText(value))
                else:
                    combo.setEditText(value)
        elif key == "lora_strength":
            self._lora_strength.set_value(value)
        elif key == "imgsz":
            self._imgsz.set_value(value)
        elif key == "comfy_dir":
            self._comfy_dir.set_path(value)
        elif key == "mosaic_model":
            self._mosaic_model.set_path(value)
        elif key == "nsfw_model":
            self._nsfw_model.set_path(value)
        elif key in self._switches:
            self._switches[key].set_value(value)

    def sync_from_store(self, settings: Settings) -> None:
        self._syncing = True
        try:
            with QSignalBlocker(self._url_edit):
                self._url_edit.setText(settings.comfy_url)
            for key, combo in self._combos.items():
                value = getattr(settings, key)
                with QSignalBlocker(combo):
                    index = combo.findText(value)
                    if index >= 0:
                        combo.setCurrentIndex(index)
                    else:
                        combo.setEditText(value)
            self._lora_strength.set_value(settings.lora_strength)
            self._imgsz.set_value(settings.imgsz)
            self._python_row.set_path(settings.python_exe)
            self._comfy_dir.set_path(settings.comfy_dir)
            self._mosaic_model.set_path(settings.mosaic_model)
            self._nsfw_model.set_path(settings.nsfw_model)
            for key, widget in self._switches.items():
                widget.set_value(bool(getattr(settings, key)))
            self._refresh_runtime_caption()
        finally:
            self._syncing = False

    # -------------------------------------------------------------- actions
    def _test_connection(self) -> None:
        if self._testing:
            return
        self._commit_url()
        self._testing = True
        self._test_button.setEnabled(False)
        self._test_button.setText("检测中…")
        self._set_connection("checking", "正在连接 ComfyUI…", "")
        settings = self.store.settings
        self.runner.run(
            lambda: inspect_environment(settings),
            self._on_environment,
            self._on_environment_error,
        )

    def _finish_testing(self) -> None:
        self._testing = False
        self._test_button.setEnabled(True)
        self._test_button.setText("测试连接")

    def _on_environment(self, report) -> None:
        self._finish_testing()
        if not report.connected:
            self._set_connection("error", "无法连接", report.error[:160])
            self._model_status.setText(report.error)
            self._model_status.show()
            self.notice.emit("ComfyUI 连接失败，请确认服务已启动", "error")
            return
        version = f"ComfyUI {report.version}" if report.version else "ComfyUI"
        elapsed = f"{report.elapsed:.1f}s"
        if report.problems:
            self._set_connection("warn", "已连接，但环境不完整", f"{version} · {elapsed}")
            self._model_status.setText("；".join(report.problems))
            self._model_status.show()
            self.notice.emit(f"发现 {len(report.problems)} 个环境问题", "warning")
        else:
            self._set_connection("ok", "已连接 · 模型齐全", f"{version} · {elapsed}")
            self._model_status.hide()
            self.notice.emit("ComfyUI 连接正常，模型齐全", "success")
        if report.models:
            self._populate_models(report.models)

    def _on_environment_error(self, message: str) -> None:
        self._finish_testing()
        self._set_connection("error", "检测失败", message[:160])
        self.notice.emit(f"检测失败：{message}", "error")

    def _populate_models(self, models: dict[str, list[str]]) -> None:
        for key, options in models.items():
            combo = self._combos.get(key)
            if combo is None:
                continue
            current = combo.currentText().strip() or getattr(self.store.settings, key)
            with QSignalBlocker(combo):
                combo.clear()
                combo.addItems(options)
                index = combo.findText(current)
                if index >= 0:
                    combo.setCurrentIndex(index)
                else:
                    combo.setEditText(current)

    def _autodetect(self) -> None:
        settings = self.store.settings
        if not (settings.comfy_dir or "").strip():
            self.notice.emit("请先填写 ComfyUI 目录，再点“自动检测”", "warning")
            return
        changes = {
            key: value
            for key, value in autodetect_paths(settings).items()
            if value and getattr(settings, key) != value
        }
        if not changes:
            self.notice.emit("在已填写的 ComfyUI 目录下没有找到新的模型文件", "warning")
            return
        self.store.update(changes)
        self.notice.emit("已自动填入检测路径", "success")

    def _set_connection(self, state: str, text: str, detail: str) -> None:
        colors = {
            "ok": self._palette.success,
            "error": self._palette.danger,
            "checking": self._palette.warning,
            "warn": self._palette.warning,
        }
        self._conn_dot.set_color(colors.get(state, self._palette.dim), glow=state == "ok")
        self._conn_label.setText(text)
        self._conn_label.setProperty("state", state)
        repolish(self._conn_label)
        self._conn_detail.setText(detail)

    def _open_path(self, path: str) -> None:
        if not os.path.exists(path):
            self.notice.emit("文件还不存在", "warning")
            return
        try:
            os.startfile(path)  # type: ignore[attr-defined]
        except Exception as exc:
            self.notice.emit(f"无法打开：{exc}", "error")

    def _reset_all(self) -> None:
        answer = QMessageBox.question(
            self,
            "恢复默认设置",
            "将清空所有目录、模型与参数设置（不会删除图片）。确定继续吗？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer == QMessageBox.Yes:
            self.store.reset()
            self.notice.emit("所有设置已恢复默认值", "info")

    # -------------------------------------------------------------- palette
    def apply_palette(self, palette: Palette) -> None:
        self._palette = palette
        for card in self.findChildren(Card):
            card.set_palette(palette)
        for widget in self._switches.values():
            widget.set_palette(palette)
        self._use_current.set_palette(palette)
        state = self._conn_label.property("state") or "idle"
        text = self._conn_label.text()
        detail = self._conn_detail.text()
        self._set_connection(state, text, detail)
