"""Post-processing dialog — UI only for now, the pipeline is not implemented."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
)

from ..theme import Palette
from ..widgets.base import Badge, Card, IconTile
from ..widgets.buttons import Button

PLANNED = (
    ("超分辨率", "2× / 4× 放大并重建细节（Real-ESRGAN 等）", "image"),
    ("锐化与细节", "轻量锐化，不放大噪点", "wand"),
    ("去噪", "处理生成结果中的轻微噪点与色块", "sparkles"),
    ("色彩与对比度", "统一色调、亮度和对比度", "sun"),
    ("导出格式", "PNG / WebP / JPEG 与质量设置", "save"),
)


class _ModuleRow(QFrame):
    def __init__(self, title: str, detail: str, icon: str, palette: Palette, parent=None):
        super().__init__(parent)
        self.setObjectName("Inset")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(11)
        layout.addWidget(IconTile(icon, palette, 32), 0, Qt.AlignTop)
        texts = QVBoxLayout()
        texts.setSpacing(2)
        title_label = QLabel(title)
        title_label.setObjectName("FormLabel")
        detail_label = QLabel(detail)
        detail_label.setObjectName("FormHelp")
        detail_label.setWordWrap(True)
        texts.addWidget(title_label)
        texts.addWidget(detail_label)
        layout.addLayout(texts, 1)
        badge = Badge("计划中", "warn")
        layout.addWidget(badge, 0, Qt.AlignTop)


class PostProcessDialog(QDialog):
    def __init__(self, palette: Palette, file_label: str = "", parent=None):
        super().__init__(parent)
        self._palette = palette
        self.setObjectName("PostProcessDialog")
        self.setWindowTitle("一键后处理 · 开发中")
        self.setModal(True)
        self.resize(800, 680)
        self._build(file_label)

    def _build(self, file_label: str) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(12)

        header = QHBoxLayout()
        header.setSpacing(10)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        title = QLabel("一键后处理")
        title.setObjectName("PageTitle")
        subtitle = QLabel("对生成结果做放大、锐化、色彩等二次处理。")
        subtitle.setObjectName("PageSubtitle")
        titles.addWidget(title)
        titles.addWidget(subtitle)
        header.addLayout(titles, 1)
        header.addWidget(Badge("开发中", "warn"), 0, Qt.AlignTop)
        root.addLayout(header)

        info = Card("当前对象", "此页面仅确定交互与选项，不会修改任何文件", "info", self._palette)
        self._file_label = QLabel(file_label or "尚未选择结果")
        self._file_label.setObjectName("Mono")
        self._file_label.setWordWrap(True)
        info.add(self._file_label)
        root.addWidget(info)

        options = Card("后处理模块", "以下能力在后续版本开放", "layers", self._palette)
        for title_text, detail, icon in PLANNED:
            options.add(_ModuleRow(title_text, detail, icon, self._palette))
        root.addWidget(options, 1)

        note = QLabel(
            "开发计划：先做超分辨率与导出格式，再接入锐化 / 去噪 / 色彩链路；"
            "所有后处理都会写成新文件，默认不覆盖原始结果。"
        )
        note.setObjectName("FormHelp")
        note.setWordWrap(True)
        root.addWidget(note)

        footer = QHBoxLayout()
        footer.setSpacing(8)
        hint = QLabel("后处理逻辑尚未实现；本页按钮只用于界面预览。")
        hint.setObjectName("Caption")
        footer.addWidget(hint, 1)
        close = Button("关闭", "secondary", None, self._palette)
        close.clicked.connect(self.accept)
        footer.addWidget(close)
        start = Button("开始后处理", "primary", "sparkles", self._palette)
        start.setEnabled(False)
        start.setToolTip("后处理功能开发中")
        footer.addWidget(start)
        root.addLayout(footer)
