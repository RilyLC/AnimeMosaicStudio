"""First-run setup wizard: interpreter, ComfyUI folder, detection models.

Nothing here is guessed: the user chooses each one, and the values are written
to config.json when the wizard finishes.
"""

from __future__ import annotations

import os
import sys

from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..core.discovery import looks_like_comfy
from ..services.environment import autodetect_paths
from .state import SettingsStore
from .theme import Palette
from .widgets.base import Card
from .widgets.buttons import Button
from .widgets.fields import PathRow

STEPS = (
    ("Python 解释器", "运行本程序（需要 PySide6、torch、ultralytics）"),
    ("ComfyUI 目录", "包含 main.py 与 models 文件夹的根目录"),
    ("检测模型", "YOLO 分割模型，决定哪些区域会被重绘"),
)


class SetupDialog(QDialog):
    """Three-step wizard for the locations AnimeMosaicStudio cannot infer."""

    def __init__(
        self,
        store: SettingsStore,
        palette: Palette,
        parent=None,
        *,
        first_run: bool = False,
    ):
        super().__init__(parent)
        self._store = store
        self._palette = palette
        self._first_run = first_run
        self._step = 0
        self.setObjectName("SetupDialog")
        self.setWindowTitle("首次使用设置")
        self.setModal(True)
        self.resize(760, 460)
        self._build()
        self._goto(0)

    # ------------------------------------------------------------------ build
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 16)
        root.setSpacing(12)

        title = QLabel("首次使用设置" if self._first_run else "首次使用向导")
        title.setObjectName("PageTitle")
        root.addWidget(title)

        subtitle = QLabel(
            "按下面三步填写，"
            "完成后会保存到 config.json；以后可以在 设置 → 维护 里重新打开这个向导。"
        )
        subtitle.setObjectName("PageSubtitle")
        subtitle.setWordWrap(True)
        root.addWidget(subtitle)

        self._step_label = QLabel("")
        self._step_label.setObjectName("Caption")
        root.addWidget(self._step_label)

        self._stack = QStackedWidget()
        self._stack.addWidget(self._build_python_page())
        self._stack.addWidget(self._build_comfy_page())
        self._stack.addWidget(self._build_model_page())
        root.addWidget(self._stack, 1)

        footer = QHBoxLayout()
        footer.setSpacing(8)
        self._status = QLabel("")
        self._status.setObjectName("FormHelp")
        self._status.setWordWrap(True)
        footer.addWidget(self._status, 1)
        self._later = Button("以后再说", "link", None, self._palette)
        self._later.clicked.connect(self.reject)
        footer.addWidget(self._later)
        self._back = Button("上一步", "secondary", None, self._palette)
        self._back.clicked.connect(lambda: self._goto(self._step - 1))
        footer.addWidget(self._back)
        self._next = Button("下一步", "primary", None, self._palette)
        self._next.clicked.connect(self._on_next)
        footer.addWidget(self._next)
        self._finish = Button("完成", "primary", "check", self._palette)
        self._finish.clicked.connect(self._on_finish)
        footer.addWidget(self._finish)
        root.addLayout(footer)

    def _page(self) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        return page, layout

    def _build_python_page(self) -> QWidget:
        page, layout = self._page()
        card = Card(
            "Python 解释器",
            "AnimeMosaicStudio 用这个解释器运行，需要 PySide6、torch 与 ultralytics",
            "cpu",
            self._palette,
        )
        self._python = PathRow(
            "python.exe 或 pythonw.exe",
            self._store.get("python_exe"),
            "file",
            "Python (python.exe pythonw.exe);;所有文件 (*.*)",
            self._palette,
        )
        card.add(self._python)

        row = QHBoxLayout()
        use_current = Button("使用当前解释器", "secondary", "check", self._palette)
        use_current.clicked.connect(lambda: self._python.set_path(sys.executable))
        row.addWidget(use_current)
        row.addStretch(1)
        card.add_layout(row)


        layout.addWidget(card)
        layout.addStretch(1)
        return page

    def _build_comfy_page(self) -> QWidget:
        page, layout = self._page()
        card = Card(
            "ComfyUI 目录",
            "启动器只会使用这里填写的目录",
            "folder",
            self._palette,
        )
        self._comfy_dir = PathRow(
            "ComfyUI 根目录", self._store.get("comfy_dir"), "dir", palette=self._palette
        )
        card.add(self._comfy_dir)

        row = QHBoxLayout()
        check = Button("检查目录", "secondary", "check", self._palette)
        check.clicked.connect(self._check_comfy_dir)
        row.addWidget(check)
        row.addStretch(1)
        card.add_layout(row)
        self._comfy_status = QLabel("")
        self._comfy_status.setObjectName("FormHelp")
        self._comfy_status.setWordWrap(True)
        card.add(self._comfy_status)

        url_row = QHBoxLayout()
        url_label = QLabel("服务地址")
        url_label.setObjectName("FormLabel")
        url_row.addWidget(url_label)
        self._url = QLineEdit()
        self._url.setPlaceholderText("http://127.0.0.1:8188")
        self._url.setText(self._store.get("comfy_url"))
        self._url.setMinimumHeight(38)
        url_row.addWidget(self._url, 1)
        card.add_layout(url_row)
        layout.addWidget(card)
        layout.addStretch(1)
        return page

    def _build_model_page(self) -> QWidget:
        page, layout = self._page()
        card = Card(
            "检测模型",
            "这一步可以跳过，之后在 设置 → 检测模型 里再补",
            "cpu",
            self._palette,
        )
        detect = Button("在已填写的 ComfyUI 目录下检测", "secondary", "wand", self._palette)
        detect.clicked.connect(self._autodetect)
        card.add(detect)
        self._mosaic = PathRow(
            "马赛克模型",
            self._store.get("mosaic_model"),
            "file",
            "YOLO 模型 (*.pt);;所有文件 (*.*)",
            self._palette,
        )
        card.add(self._mosaic)
        self._nsfw = PathRow(
            "NSFW 模型",
            self._store.get("nsfw_model"),
            "file",
            "YOLO 模型 (*.pt);;所有文件 (*.*)",
            self._palette,
        )
        card.add(self._nsfw)
        self._model_status = QLabel("")
        self._model_status.setObjectName("FormHelp")
        self._model_status.setWordWrap(True)
        card.add(self._model_status)
        layout.addWidget(card)
        layout.addStretch(1)
        return page

    # ---------------------------------------------------------------- actions
    def _goto(self, index: int) -> None:
        self._step = max(0, min(len(STEPS) - 1, index))
        self._stack.setCurrentIndex(self._step)
        name, hint = STEPS[self._step]
        self._step_label.setText(f"第 {self._step + 1} 步 / 共 {len(STEPS)} 步 · {name} — {hint}")
        self._back.setVisible(self._step > 0)
        self._next.setVisible(self._step < len(STEPS) - 1)
        self._finish.setVisible(self._step == len(STEPS) - 1)
        self._status.setText("")
        self._status.hide()

    def _commit(self, index: int) -> None:
        if index == 0:
            self._store.set("python_exe", self._python.path())
        elif index == 1:
            self._store.set("comfy_dir", self._comfy_dir.path())
            self._store.set("comfy_url", self._url.text().strip() or "http://127.0.0.1:8188")
        else:
            self._store.set("mosaic_model", self._mosaic.path())
            self._store.set("nsfw_model", self._nsfw.path())

    def _on_next(self) -> None:
        self._commit(self._step)
        self._goto(self._step + 1)

    def _on_finish(self) -> None:
        self._commit(self._step)
        if not (self._store.get("python_exe") or "").strip():
            self._goto(0)
            self._show_status("还没有选择 Python 解释器；可以先选一个，或点“以后再说”。")
            return
        if not (self._store.get("comfy_dir") or "").strip():
            self._goto(1)
            self._show_status("还没有填写 ComfyUI 目录；可以先填一个，或点“以后再说”。")
            return
        self._store.save_now()
        self.accept()

    def _show_status(self, text: str) -> None:
        self._status.setText(text)
        self._status.show()

    def _check_comfy_dir(self) -> None:
        path = self._comfy_dir.path()
        if not path:
            self._comfy_status.setText("还没有选择目录。")
        elif looks_like_comfy(path):
            self._comfy_status.setText("看起来是正确的 ComfyUI 目录。")
        elif os.path.isdir(path) and os.path.isdir(os.path.join(path, "models")):
            self._comfy_status.setText(
                "目录里有 models，但没有 folder_paths.py；如果 ComfyUI 能正常启动，可以继续。"
            )
        else:
            self._comfy_status.setText("目录不存在，或者不像 ComfyUI 的根目录。")

    def _autodetect(self) -> None:
        self._commit(1)
        settings = self._store.settings
        if not (settings.comfy_dir or "").strip():
            self._model_status.setText("请先在第二步填写 ComfyUI 目录。")
            return
        found = {
            key: value
            for key, value in autodetect_paths(settings).items()
            if value and getattr(settings, key) != value
        }
        if not found:
            if settings.mosaic_model or settings.nsfw_model:
                self._model_status.setText("模型路径已填写；如需重新检测，请先清空对应的输入框。")
            else:
                self._model_status.setText(
                    "没有在 models/ultralytics 下找到含 mosaic / nsfw 的 .pt 文件，请手动选择。"
                )
            return
        if found.get("mosaic_model"):
            self._mosaic.set_path(found["mosaic_model"])
        if found.get("nsfw_model"):
            self._nsfw.set_path(found["nsfw_model"])
        self._model_status.setText("已在该目录下找到模型，点“完成”保存。")
