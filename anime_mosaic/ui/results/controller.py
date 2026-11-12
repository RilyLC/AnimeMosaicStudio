"""Data and background controller for result comparison / single-image regeneration."""

from __future__ import annotations

import threading
import traceback
from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal

from ...core.events import Reporter
from ...core.errors import Cancelled
from ...core.pipeline import Pipeline
from ...core.settings import Settings


@dataclass
class ResultItem:
    rel: str
    input_path: str
    output_path: str
    record: object | None = None


class _SingleReporter(Reporter):
    def __init__(self, controller: "SingleRunController"):
        self.controller = controller

    def log(self, level, message):
        self.controller.log.emit(level, message)

    def stage(self, rel_path, stage, detail=""):
        self.controller.stage.emit(rel_path, stage, detail)

    def progress(self, done, total, rel_path, speed, eta):
        self.controller.progress.emit(done, total, rel_path, speed, eta)

    def result(self, record, dst_path):
        self.controller.result.emit(record, dst_path)

    def done(self, summary):
        self.controller.done.emit(summary)


class SingleRunController(QObject):
    log = Signal(str, str)
    stage = Signal(str, str, str)
    progress = Signal(int, int, str, float, float)
    result = Signal(object, str)
    done = Signal(object)
    finished = Signal(object)
    failed = Signal(str)
    cancelled = Signal()
    runningChanged = Signal(bool)

    def __init__(
        self,
        parent: QObject | None = None,
        detector_provider=None,
    ):
        super().__init__(parent)
        self._detector_provider = detector_provider
        self._thread: threading.Thread | None = None
        self._stop_event: threading.Event | None = None
        self._running = False
        self._settings: Settings | None = None
        self._rel = ""
        self._group_provider = None

    @property
    def running(self) -> bool:
        return self._running

    def start(self, settings: Settings, rel: str, group_provider=None) -> bool:
        if self._running:
            return False
        self._settings = settings
        self._rel = rel
        self._group_provider = group_provider
        self._stop_event = threading.Event()
        self._running = True
        self.runningChanged.emit(True)
        self._thread = threading.Thread(
            target=self._run, name="anime-mosaic-single", daemon=True
        )
        self._thread.start()
        return True

    def stop(self) -> None:
        if self._running and self._stop_event is not None:
            self._stop_event.set()
            self.log.emit("warn", "正在停止重新生成…")

    def wait(self, timeout: float = 2.0) -> None:
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout)

    def _run(self) -> None:
        try:
            from ...services.reuse_groups import load_disabled

            rels = [self._rel]
            if self._group_provider is not None:
                try:
                    members = list(self._group_provider(self._rel))
                except Exception as exc:  # noqa: BLE001 - never block regeneration
                    self.log.emit(
                        "warn", f"读取复用组失败，只重新生成当前图片：{exc}"
                    )
                    members = []
                if self._rel not in members:
                    members.insert(0, self._rel)
                rels = members
            pipeline = Pipeline(
                self._settings,
                _SingleReporter(self),
                self._stop_event,
                detector_provider=self._detector_provider,
                reuse_disabled=load_disabled(self._settings.output_dir),
            )
            results = pipeline.run_group(rels)
            self.finished.emit(results)
        except Cancelled as exc:
            partial = getattr(exc, "results", None)
            if partial:
                self.finished.emit(partial)
            self.log.emit("warn", "已停止重新生成，已完成的图片保持更新")
            self.cancelled.emit()
        except Exception as exc:  # noqa: BLE001 - shown in the dialog
            self.log.emit("error", f"重新生成失败：{exc}")
            self.log.emit("debug", traceback.format_exc())
            self.failed.emit(f"{type(exc).__name__}: {exc}")
        finally:
            self._running = False
            self.runningChanged.emit(False)
