"""Pre-recognition: detect masks for every input image before processing.

This is deliberately UI-free.  The desktop preflight dialog drives it on a
worker thread; the CLI could reuse it later for a dry run.

Two kinds of results live side by side:

* automatic ones, produced by the mosaic/NSFW detector and invalidated when a
  detection setting changes;
* manual ones, rebuilt from ``ManualMaskStore`` with ``build_manual_plan``.  A
  hand-edited mask is authoritative, so those images never need the detector —
  the model is loaded lazily on the first image that actually needs it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from typing import Callable

import numpy as np

from ..core.detector import Detector, MosaicDetector
from ..core.discovery import discover_images, find_ultralytics_model
from ..core.errors import AnimeMosaicError
from ..core.imaging import is_animated, open_image, to_rgb_array
from ..core.manual_mask import ManualMaskStore, encode_mask
from ..core.maskplan import build_manual_plan, build_mask_plan
from ..core.settings import Settings

#: fingerprint = (image mtime_ns, image size, manual-mask mtime_ns)
Fingerprint = tuple[int, int, int]


class PreflightError(AnimeMosaicError):
    """Pre-recognition cannot start (missing model, unreadable folder…)."""


@dataclass
class PreflightEntry:
    path: str
    rel: str
    width: int = 0
    height: int = 0
    regions: int = 0
    coverage: float = 0.0
    mask_png: bytes | None = None
    core_mask_png: bytes | None = None
    detections: str = ""
    nsfw_text: str = ""
    nsfw_boxes: tuple[tuple[str, float, int, int, int, int], ...] = ()
    error: str = ""
    animated: bool = False
    manual: bool = False
    #: Set when the entry was restored from the persistent cache; the payload
    #: lives in a file instead of ``mask_png`` so restarts stay cheap.
    mask_file: str = ""
    core_file: str = ""

    @property
    def has_mask(self) -> bool:
        return self.regions > 0

    @property
    def status_key(self) -> str:
        if self.error:
            return "error"
        if self.animated:
            return "animated"
        if self.manual:
            return "manual"
        if self.regions > 0:
            return "mask"
        return "empty"

    @property
    def status_label(self) -> str:
        if self.error:
            return "失败"
        if self.animated:
            return "动图"
        if self.manual:
            return "手动遮罩"
        if self.regions > 0:
            return f"{self.regions} 处"
        return "无马赛克"


def fingerprint(path: str) -> tuple[int, int]:
    """(mtime_ns, size) of a file, or (0, 0) when it cannot be stat'ed."""
    try:
        stat = os.stat(path)
    except OSError:
        return (0, 0)
    return (int(stat.st_mtime_ns), int(stat.st_size))


def entry_mask_png(entry: PreflightEntry) -> bytes | None:
    """Mask payload of ``entry``, reading it from the cache when needed."""
    if entry.mask_png is not None:
        return entry.mask_png
    if entry.mask_file:
        try:
            with open(entry.mask_file, "rb") as handle:
                return handle.read()
        except OSError:
            return None
    return None


def entry_core_png(entry: PreflightEntry) -> bytes | None:
    """Core (uneditable) mask payload of ``entry``, reading from cache."""
    if entry.core_mask_png is not None:
        return entry.core_mask_png
    if entry.core_file:
        try:
            with open(entry.core_file, "rb") as handle:
                return handle.read()
        except OSError:
            return None
    return None


def rebuild_manual_entry(entry: PreflightEntry, mask: np.ndarray) -> PreflightEntry:
    """Return ``entry`` rebuilt from a hand-edited mask."""
    plan = build_manual_plan(mask)
    editable = plan.editable_mask
    core = plan.core_mask
    return replace(
        entry,
        regions=len(plan.regions),
        coverage=plan.editable_coverage_pct,
        detections="",
        nsfw_text="",
        nsfw_boxes=(),
        error="",
        manual=True,
        mask_png=encode_mask(editable) if editable.any() else None,
        core_mask_png=encode_mask(core) if core is not None and core.any() else None,
        mask_file="",
        core_file="",
    )


def detection_signature(settings: Settings) -> tuple:
    """Everything that changes auto-detection results (not output paths)."""
    return (
        settings.input_dir,
        settings.include_subdirs,
        settings.comfy_dir,
        settings.mosaic_model,
        settings.nsfw_model,
        settings.conf,
        settings.imgsz,
        settings.device,
        settings.nsfw_mode,
    )


def load_detectors(
    settings: Settings, detector_factory: Callable[..., Detector] = MosaicDetector
) -> tuple[Detector, Detector | None, str]:
    """Load the mosaic detector (and optional NSFW detector) for preflight."""
    comfy_dir = settings.comfy_dir
    mosaic_path = settings.mosaic_model or find_ultralytics_model(comfy_dir, "mosaic")
    if not mosaic_path or not os.path.isfile(mosaic_path):
        raise PreflightError("找不到马赛克检测模型，请先在“设置 → 检测模型”中指定")
    detector = detector_factory(
        mosaic_path,
        device=settings.device,
        imgsz=settings.imgsz,
        conf=settings.conf,
        iou=0.5,
    )
    detector.load()

    nsfw_detector: Detector | None = None
    if settings.nsfw_mode != "off":
        nsfw_path = settings.nsfw_model or find_ultralytics_model(comfy_dir, "nsfw")
        if not nsfw_path or not os.path.isfile(nsfw_path):
            raise PreflightError("NSFW 辅助已开启，但找不到 NSFW 模型")
        nsfw_detector = detector_factory(
            nsfw_path,
            device=settings.device,
            imgsz=settings.imgsz,
            conf=0.25,
            iou=0.5,
        )
        nsfw_detector.load()
    return detector, nsfw_detector, os.path.basename(mosaic_path)


class PreflightScanner:
    def __init__(
        self,
        settings: Settings,
        detector_factory: Callable[..., Detector] = MosaicDetector,
        discovery: Callable[..., list[str]] = discover_images,
        detector_provider: Callable[[Settings], tuple[Detector, Detector | None, str]]
        | None = None,
        manual_store: ManualMaskStore | None = None,
    ):
        self.settings = settings
        self._detector_factory = detector_factory
        self._discovery = discovery
        self._detector_provider = detector_provider
        if manual_store is not None:
            self.manual_store: ManualMaskStore | None = manual_store
        elif settings.output_dir:
            self.manual_store = ManualMaskStore(settings.output_dir)
        else:
            self.manual_store = None
        self.detector: Detector | None = None
        self.nsfw_detector: Detector | None = None
        self.model_name = ""
        self.total = 0
        self.stopped = False
        self.fingerprints: dict[str, Fingerprint] = {}
        self._loaded = False
        self._log: Callable[[str, str], None] = lambda level, message: None

    # --------------------------------------------------------------- scanning
    def scan(
        self,
        stop_event=None,
        on_total: Callable[[int], None] | None = None,
        on_item: Callable[[PreflightEntry], None] | None = None,
        on_log: Callable[[str, str], None] | None = None,
        mode: str = "all",
        only_rel: str | None = None,
        only_rels: list[str] | None = None,
        cached_entries: dict[str, PreflightEntry] | None = None,
        fingerprints: dict[str, Fingerprint] | None = None,
        cached_signature: tuple | None = None,
    ) -> list[PreflightEntry]:
        """Scan the input folder.

        ``mode`` is ``"all"`` (re-detect everything) or ``"continue"`` (only
        images that are new, changed, or invalidated since the cached run).
        ``only_rel``/``only_rels`` restrict the scan to specific images.
        """
        self._log = on_log or (lambda level, message: None)
        self.stopped = False
        files = self._discovery(
            self.settings.input_dir,
            self.settings.output_dir,
            self.settings.include_subdirs,
        )
        wanted: set[str] | None = None
        if only_rels is not None:
            wanted = {os.path.normcase(os.path.normpath(rel)) for rel in only_rels}
        elif only_rel is not None:
            wanted = {os.path.normcase(os.path.normpath(only_rel))}
        if wanted is not None:
            files = [
                path
                for path in files
                if os.path.normcase(
                    os.path.normpath(os.path.relpath(path, self.settings.input_dir))
                )
                in wanted
            ]

        self.total = len(files)
        targets = self._select_targets(
            files,
            mode="all" if wanted is not None else mode,
            cached_entries=cached_entries or {},
            fingerprints=fingerprints or {},
            cached_signature=cached_signature,
        )
        if wanted is not None:
            missing = wanted - {
                os.path.normcase(
                    os.path.normpath(os.path.relpath(path, self.settings.input_dir))
                )
                for path in files
            }
            if missing:
                self._log("warn", f"有 {len(missing)} 张图片已不在输入目录中，已跳过")
        if on_total:
            on_total(len(targets))
        if self.total:
            reused = self.total - len(targets)
            suffix = f"，其余 {reused} 张使用缓存" if reused > 0 else ""
            self._log("info", f"预识别：共 {self.total} 张，本次处理 {len(targets)} 张{suffix}")
        else:
            self._log("warn", "预识别：输入目录中没有找到图片")

        entries: list[PreflightEntry] = []
        for path in targets:
            if stop_event is not None and stop_event.is_set():
                self.stopped = True
                self._log("warn", "预识别已停止")
                break
            entry = self.scan_one(path)
            entries.append(entry)
            if on_item:
                on_item(entry)
        if not targets and self.total:
            self._log("info", "所有图片都已是最新状态")
        return entries

    def _select_targets(
        self,
        files: list[str],
        *,
        mode: str,
        cached_entries: dict[str, PreflightEntry],
        fingerprints: dict[str, Fingerprint],
        cached_signature: tuple | None,
    ) -> list[str]:
        if mode == "all" or not cached_entries:
            return list(files)
        signatures_differ = (
            cached_signature is not None
            and cached_signature != detection_signature(self.settings)
        )
        targets: list[str] = []
        for path in files:
            rel = os.path.relpath(path, self.settings.input_dir)
            entry = cached_entries.get(rel)
            if entry is None:
                targets.append(path)
                continue
            stamp = fingerprint(path)
            cached_stamp = fingerprints.get(rel, (0, 0, 0))
            if stamp != (cached_stamp[0], cached_stamp[1]):
                targets.append(path)
                continue
            if self._manual_stamp(rel) != cached_stamp[2]:
                targets.append(path)
                continue
            if signatures_differ and not entry.manual:
                targets.append(path)
        return targets

    def scan_one(self, path: str, use_manual: bool = True) -> PreflightEntry:
        rel = os.path.relpath(path, self.settings.input_dir)
        try:
            stamp = fingerprint(path)
            self.fingerprints[rel] = (stamp[0], stamp[1], self._manual_stamp(rel))
            image = open_image(path)
            width, height = image.size
            if is_animated(image):
                return PreflightEntry(
                    path=path, rel=rel, width=width, height=height, animated=True
                )
            manual = self._manual_mask(rel) if use_manual else None
            if manual is not None:
                if manual.shape == (height, width):
                    plan = build_manual_plan(manual)
                    editable = plan.editable_mask
                    core = plan.core_mask
                    return PreflightEntry(
                        path=path,
                        rel=rel,
                        width=width,
                        height=height,
                        regions=len(plan.regions),
                        coverage=plan.editable_coverage_pct,
                        mask_png=encode_mask(editable) if editable.any() else None,
                        core_mask_png=(
                            encode_mask(core)
                            if core is not None and core.any()
                            else None
                        ),
                        detections="",
                        manual=True,
                    )
                self._log(
                    "warn",
                    f"{rel}：手动遮罩尺寸 {manual.shape[1]}×{manual.shape[0]} 与图片 "
                    f"{width}×{height} 不符，已改用自动检测",
                )
            self._ensure_detectors()
            rgb = to_rgb_array(image)
            plan = build_mask_plan(
                rgb, self.detector, self.nsfw_detector, self.settings
            )
            return PreflightEntry(
                path=path,
                rel=rel,
                width=width,
                height=height,
                regions=len(plan.regions),
                coverage=plan.editable_coverage_pct,
                mask_png=encode_mask(plan.editable_mask) if plan.editable_mask.any() else None,
                core_mask_png=(
                    encode_mask(plan.core_mask)
                    if plan.core_mask is not None and plan.core_mask.any()
                    else None
                ),
                detections=plan.detection_text(),
                nsfw_text=plan.nsfw_text,
                nsfw_boxes=tuple(
                    (d.name, round(d.conf, 3), d.x, d.y, d.w, d.h)
                    for d in (plan.nsfw_detections or ())
                ),
            )
        except Exception as exc:  # noqa: BLE001 - one bad image must not stop preflight
            return PreflightEntry(
                path=path, rel=rel, error=f"{type(exc).__name__}: {exc}"[:300]
            )

    # ---------------------------------------------------------------- helpers
    def _ensure_detectors(self) -> None:
        if self._loaded:
            return
        if self._detector_provider is not None:
            self._log("info", "使用已加载的检测模型…")
            self.detector, self.nsfw_detector, self.model_name = self._detector_provider(
                self.settings
            )
        else:
            self._log("info", "正在加载检测模型…")
            self.detector, self.nsfw_detector, self.model_name = load_detectors(
                self.settings, self._detector_factory
            )
        self._loaded = True
        self._log("info", f"预识别模型：{self.model_name}")

    def _manual_mask(self, rel: str) -> np.ndarray | None:
        if self.manual_store is None:
            return None
        try:
            return self.manual_store.load(rel)
        except (OSError, ValueError):
            return None

    def _manual_stamp(self, rel: str) -> int:
        if self.manual_store is None:
            return 0
        try:
            return fingerprint(self.manual_store.path_for(rel))[0]
        except ValueError:
            return 0
