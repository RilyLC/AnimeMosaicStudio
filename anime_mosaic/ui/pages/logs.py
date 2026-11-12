"""Full-page log console with level filtering and search."""

from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from ...core.settings import LOG_PATH
from ..log_store import LogStore
from ..theme import Palette
from ..widgets.base import Card
from ..widgets.buttons import Button
from ..widgets.log_view import LogView
from ..widgets.switch import Switch

LEVEL_CHOICES = (
    ("全部", "debug"),
    ("信息及以上", "info"),
    ("警告及以上", "warn"),
    ("仅错误", "error"),
)


class LogsPage(QWidget):
    def __init__(self, log_store: LogStore, palette: Palette, parent=None):
        super().__init__(parent)
        self.log_store = log_store
        self._palette = palette
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        card = Card("运行日志", "最近 4000 条记录，可筛选、搜索与复制", "logs", palette)
        card.setObjectName("Card")

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        self._level = QComboBox()
        for label, value in LEVEL_CHOICES:
            self._level.addItem(label, value)
        self._level.setCurrentIndex(1)
        self._level.setMinimumWidth(120)
        self._level.currentIndexChanged.connect(self._reload)
        toolbar.addWidget(self._level)

        self._search = QLineEdit()
        self._search.setPlaceholderText("搜索日志内容…")
        self._search.setClearButtonEnabled(True)
        self._search.setMinimumWidth(220)
        self._search.textChanged.connect(self._reload)
        toolbar.addWidget(self._search, 1)

        auto_label = QLabel("自动滚动")
        auto_label.setObjectName("Caption")
        toolbar.addWidget(auto_label)
        self._auto_scroll = Switch(True, palette)
        toolbar.addWidget(self._auto_scroll)
        toolbar.addSpacing(6)

        copy = Button("复制", "secondary", "copy", palette, size="sm")
        copy.clicked.connect(lambda: self.view.copy_all())
        toolbar.addWidget(copy)
        clear = Button("清空", "ghost", "trash", palette, size="sm")
        clear.clicked.connect(self.log_store.clear)
        toolbar.addWidget(clear)
        open_log = Button("打开文件", "ghost", "external", palette, size="sm")
        open_log.clicked.connect(self._open_file)
        toolbar.addWidget(open_log)
        card.add_layout(toolbar)

        self.view = LogView(palette)
        self.view.set_filter("info")
        self._auto_scroll.toggled.connect(self.view.set_auto_scroll)
        card.add(self.view, 1)
        layout.addWidget(card, 1)

        log_store.appended.connect(self._on_appended)
        log_store.cleared.connect(self.view.clear)
        self._reload()

    # ------------------------------------------------------------------ api
    def _current_level(self) -> str:
        return str(self._level.currentData())

    def _on_appended(self, entry) -> None:
        if self.view.matches(entry):
            self.view.append_entry(entry)

    def _reload(self) -> None:
        self.view.set_filter(self._current_level(), self._search.text())
        self.view.reload(self.log_store.filtered(self._current_level(), self._search.text()))

    def _open_file(self) -> None:
        if not os.path.isfile(LOG_PATH):
            self.log_store.add("warn", "日志文件尚未生成")
            return
        try:
            os.startfile(LOG_PATH)  # type: ignore[attr-defined]
        except Exception as exc:
            self.log_store.add("error", f"无法打开日志文件：{exc}")

    def apply_palette(self, palette: Palette) -> None:
        self._palette = palette
        self._auto_scroll.set_palette(palette)
        self.view.set_palette(palette)
        self.view.reload(self.log_store.filtered(self._current_level(), self._search.text()))
