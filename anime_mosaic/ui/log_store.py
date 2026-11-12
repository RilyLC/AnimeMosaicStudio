"""In-memory log buffer shared by the workspace and the full log page."""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal

LEVELS = ("debug", "info", "success", "warn", "error")
LEVEL_LABELS = {
    "debug": "调试",
    "info": "信息",
    "success": "成功",
    "warn": "警告",
    "error": "错误",
}
SEVERITY = {"debug": 0, "info": 1, "success": 2, "warn": 3, "error": 4}


@dataclass(frozen=True)
class LogEntry:
    timestamp: str
    level: str
    message: str
    seq: int


class LogStore(QObject):
    appended = Signal(object)
    cleared = Signal()

    def __init__(self, capacity: int = 4000, parent: QObject | None = None):
        super().__init__(parent)
        self._entries: deque[LogEntry] = deque(maxlen=capacity)
        self._seq = 0

    @property
    def entries(self) -> list[LogEntry]:
        return list(self._entries)

    def add(self, level: str, message: str) -> LogEntry:
        level = level if level in LEVELS else "info"
        self._seq += 1
        entry = LogEntry(time.strftime("%H:%M:%S"), level, message, self._seq)
        self._entries.append(entry)
        self.appended.emit(entry)
        return entry

    def clear(self) -> None:
        self._entries.clear()
        self.cleared.emit()

    def filtered(self, minimum_level: str = "debug", search: str = "") -> list[LogEntry]:
        threshold = SEVERITY.get(minimum_level, 0)
        needle = search.strip().lower()
        return [
            entry
            for entry in self._entries
            if SEVERITY.get(entry.level, 0) >= threshold
            and (not needle or needle in entry.message.lower())
        ]
