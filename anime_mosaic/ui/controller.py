"""Bridge between the Qt UI and the Qt-free batch pipeline."""

from __future__ import annotations

import threading
import traceback

from PySide6.QtCore import QObject, Signal

from ..core.events import ProcessRecord, Reporter, RunSummary
from ..core.pipeline import run_batch
from ..core.settings import Settings


class _SignalReporter(Reporter):
    def __init__(self, controller: "PipelineController"):
        self.controller = controller

    def log(self, level, message):
        self.controller.log.emit(level, message)

    def stage(self, rel_path, stage, detail=""):
        self.controller.stage.emit(rel_path, stage, detail)

    def progress(self, done, total, rel_path, speed, eta):
        self.controller.progress.emit(done, total, rel_path, speed, eta)

    def result(self, record: ProcessRecord, dst_path: str):
        self.controller.result.emit(record, dst_path)

    def done(self, summary: RunSummary):
        self.controller.done.emit(summary)


class PipelineController(QObject):
    log = Signal(str, str)
    stage = Signal(str, str, str)
    progress = Signal(int, int, str, float, float)
    result = Signal(object, str)
    done = Signal(object)
    failed = Signal(str)
    finished = Signal()
    runningChanged = Signal(bool)

    def __init__(
        self,
        detector_provider=None,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self._detector_provider = detector_provider
        self._thread: threading.Thread | None = None
        self._stop_event: threading.Event | None = None
        self._settings: Settings | None = None
        self._running = False

    @property
    def running(self) -> bool:
        return self._running

    def start(self, settings: Settings) -> bool:
        if self._running:
            return False
        self._settings = settings
        self._stop_event = threading.Event()
        self._running = True
        self.runningChanged.emit(True)
        self._thread = threading.Thread(target=self._run, name="anime-mosaic-pipeline", daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        if not self._running or self._stop_event is None:
            return
        self._stop_event.set()
        self.log.emit("warn", "正在停止……当前图片不会保存，下次运行会重新处理。")

    def shutdown(self, timeout: float = 2.5) -> None:
        self.stop()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout)

    def _run(self) -> None:
        try:
            from ..services.reuse_groups import load_disabled

            run_batch(
                self._settings,
                _SignalReporter(self),
                self._stop_event,
                detector_provider=self._detector_provider,
                reuse_disabled=load_disabled(self._settings.output_dir),
            )
        except Exception as exc:  # noqa: BLE001 - reported to the UI
            detail = traceback.format_exc()
            self.log.emit("error", f"任务中止：{exc}")
            self.log.emit("debug", detail)
            self.failed.emit(f"{type(exc).__name__}: {exc}")
        finally:
            self._running = False
            self.finished.emit()
            self.runningChanged.emit(False)
