"""Typed progress events shared by the pipeline, the CLI and the desktop UI.

The pipeline never imports Qt.  It talks to a :class:`Reporter`; the desktop UI
implements that interface by re-emitting Qt signals, and the CLI prints.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

LogLevel = Literal["info", "success", "warn", "error", "debug"]
Stage = Literal["scan", "detect", "generate", "blend", "save", "copy"]

STAGE_LABELS: dict[str, str] = {
    "scan": "扫描目录",
    "detect": "检测马赛克",
    "generate": "ComfyUI 重绘",
    "blend": "融合贴回",
    "save": "保存图片",
    "copy": "复制原图",
}

STATUS_LABELS: dict[str, str] = {
    "processed": "已处理",
    "copied": "已复制",
    "skipped": "已跳过",
    "error": "失败",
}


@dataclass
class ProcessRecord:
    """One row of the run manifest and of the UI results table."""

    file: str
    status: str
    regions: int = 0
    seconds: float = 0.0
    seed: str = ""
    detections: str = ""
    message: str = ""
    reused: bool = False

    def to_row(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def status_label(self) -> str:
        if self.reused and self.status == "processed":
            return "已处理（复用）"
        return STATUS_LABELS.get(self.status, self.status)


@dataclass
class RunSummary:
    total: int = 0
    processed: int = 0
    copied: int = 0
    skipped: int = 0
    errors: int = 0
    regions: int = 0
    elapsed: float = 0.0
    stopped: bool = False


class Reporter:
    """Base reporter with no-op defaults; subclasses override what they need."""

    def log(self, level: LogLevel, message: str) -> None:  # noqa: D401
        print(f"[{level}] {message}")

    def stage(self, rel_path: str, stage: Stage, detail: str = "") -> None:
        """Optional fine-grained status for rich front ends."""

    def progress(
        self, done: int, total: int, rel_path: str, speed: float, eta: float
    ) -> None:
        """Called once per finished image with per-image average and ETA."""

    def result(self, record: ProcessRecord, dst_path: str) -> None:
        """Called after each image that produced output (or an error)."""

    def done(self, summary: RunSummary) -> None:
        """Called exactly once when the batch ends."""
