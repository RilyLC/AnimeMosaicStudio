"""Run callables off the GUI thread and deliver results through Qt signals."""

from __future__ import annotations

import threading
import traceback
from typing import Callable

from PySide6.QtCore import QObject, Signal


class BackgroundTask(QObject):
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, fn: Callable[[], object], parent: QObject | None = None):
        super().__init__(parent)
        self._fn = fn

    def start(self) -> None:
        thread = threading.Thread(target=self._run, daemon=True)
        thread.start()

    def _run(self) -> None:
        try:
            result = self._fn()
        except Exception as exc:  # noqa: BLE001 - surface any error to the UI
            traceback.print_exc()
            self.failed.emit(f"{type(exc).__name__}: {exc}")
        else:
            self.finished.emit(result)


class TaskRunner(QObject):
    """Keeps strong references to tasks until they finish."""

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._active: set[BackgroundTask] = set()

    def run(self, fn, on_done=None, on_error=None) -> BackgroundTask:
        task = BackgroundTask(fn)
        self._active.add(task)
        task.finished.connect(lambda result: self._complete(task, on_done, result))
        task.failed.connect(lambda message: self._fail(task, on_error, message))
        task.start()
        return task

    def _complete(self, task, callback, result) -> None:
        self._active.discard(task)
        task.deleteLater()
        if callback is not None:
            callback(result)

    def _fail(self, task, callback, message) -> None:
        self._active.discard(task)
        task.deleteLater()
        if callback is not None:
            callback(message)
