"""Colored, filterable log console widgets."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QApplication, QPlainTextEdit

from ..log_store import SEVERITY, LogEntry
from ..theme import Palette


class LogView(QPlainTextEdit):
    def __init__(self, palette: Palette | None = None, parent=None):
        super().__init__(parent)
        self.setObjectName("LogView")
        self.setReadOnly(True)
        self.setMaximumBlockCount(6000)
        self.setUndoRedoEnabled(False)
        self.setCenterOnScroll(False)
        self.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self._palette = palette
        self._auto_scroll = True
        self._min_level = "info"
        self._search = ""

    # ------------------------------------------------------------------ api
    def set_auto_scroll(self, enabled: bool) -> None:
        self._auto_scroll = enabled
        if enabled:
            self.scroll_to_bottom()

    def auto_scroll(self) -> bool:
        return self._auto_scroll

    def set_filter(self, min_level: str = "debug", search: str = "") -> None:
        self._min_level = min_level if min_level in SEVERITY else "debug"
        self._search = search.strip().lower()

    def matches(self, entry: LogEntry) -> bool:
        if SEVERITY.get(entry.level, 0) < SEVERITY.get(self._min_level, 0):
            return False
        if self._search and self._search not in entry.message.lower():
            return False
        return True

    def append_entry(self, entry: LogEntry) -> None:
        if not self.matches(entry):
            return
        color = self._level_color(entry.level)
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.End)

        time_format = QTextCharFormat()
        time_format.setForeground(QColor(self._palette.dim if self._palette else "#64748b"))
        cursor.insertText(f"{entry.timestamp}  ", time_format)

        badge_format = QTextCharFormat()
        badge_format.setForeground(QColor(color))
        badge_format.setFontWeight(700)
        label = {"debug": "DBG", "info": "INF", "success": "OK ", "warn": "WRN", "error": "ERR"}.get(
            entry.level, "INF"
        )
        cursor.insertText(f"{label}  ", badge_format)

        text_format = QTextCharFormat()
        text_format.setForeground(
            QColor(color) if entry.level in ("warn", "error", "success") else QColor(
                self._palette.text if self._palette else "#e2e8f0"
            )
        )
        cursor.insertText(entry.message + "\n", text_format)
        if self._auto_scroll:
            self.scroll_to_bottom()

    def reload(self, entries: list[LogEntry]) -> None:
        self.clear()
        for entry in entries:
            self.append_entry(entry)

    def scroll_to_bottom(self) -> None:
        bar = self.verticalScrollBar()
        bar.setValue(bar.maximum())

    def copy_all(self) -> None:
        QApplication.clipboard().setText(self.toPlainText())

    def set_palette(self, palette: Palette) -> None:
        self._palette = palette

    def _level_color(self, level: str) -> str:
        if self._palette is None:
            return "#94a3b8"
        return {
            "debug": self._palette.log_debug,
            "info": self._palette.muted,
            "success": self._palette.log_success,
            "warn": self._palette.log_warn,
            "error": self._palette.log_error,
        }.get(level, self._palette.muted)
