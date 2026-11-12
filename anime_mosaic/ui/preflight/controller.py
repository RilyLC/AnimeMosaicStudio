"""Qt-facing controller that runs pre-recognition off the UI thread."""

from __future__ import annotations

import os
import threading
import traceback
from collections import OrderedDict

import numpy as np
from PySide6.QtCore import QObject, Signal

from ...core.manual_mask import ManualMaskStore
from ...core.settings import Settings
from ...services.preflight import (
    PreflightEntry,
    PreflightScanner,
    detection_signature,
    entry_core_png,
    entry_mask_png,
    fingerprint,
    rebuild_manual_entry,
)
from ...services.preflight_cache import PreflightCache


class PreflightController(QObject):
    started = Signal(int)
    itemReady = Signal(object)
    progress = Signal(int, int)
    finished = Signal(object)
    failed = Signal(str)
    log = Signal(str, str)
    stateChanged = Signal(bool)
    itemsChanged = Signal()

    def __init__(
        self,
        parent: QObject | None = None,
        detector_provider=None,
    ):
        super().__init__(parent)
        self._detector_provider = detector_provider
        self._entries: "OrderedDict[str, PreflightEntry]" = OrderedDict()
        self._fingerprints: dict[str, tuple[int, int, int]] = {}
        self._thread: threading.Thread | None = None
        self._stop_event: threading.Event | None = None
        self._settings: Settings | None = None
        self._signature: tuple | None = None
        self._cache: PreflightCache | None = None
        self._mode = "all"
        self._only_rels: list[str] | None = None
        self._total = 0
        self._total_files = 0
        self._done = 0
        self._dirty = False
        self._running = False
        self._generation = 0

    # ------------------------------------------------------------------ state
    @property
    def running(self) -> bool:
        return self._running

    @property
    def total(self) -> int:
        return self._total

    @property
    def done(self) -> int:
        return self._done

    @property
    def dirty(self) -> bool:
        """Cached results are loaded, but files changed on disk since."""
        return self._dirty

    @property
    def entries(self) -> list[PreflightEntry]:
        return list(self._entries.values())

    def entry(self, rel: str) -> PreflightEntry | None:
        return self._entries.get(rel)

    def has_results(self) -> bool:
        return bool(self._entries) or self._total > 0

    def is_stale(self, settings: Settings) -> bool:
        if self._signature is None:
            # Results without a recorded signature cannot be trusted.
            return bool(self._entries)
        return self._signature != detection_signature(settings)

    def summary(self) -> dict:
        masks = sum(1 for entry in self._entries.values() if entry.has_mask)
        edited = sum(1 for entry in self._entries.values() if entry.manual)
        errors = sum(1 for entry in self._entries.values() if entry.error)
        return {
            "total": self._total_files,
            "scanned": len(self._entries),
            "masks": masks,
            "empty": len(self._entries) - masks - errors,
            "errors": errors,
            "edited": edited,
        }

    # ----------------------------------------------------------------- control
    def load_cached(self, settings: Settings) -> int:
        """Load persisted results for the current output dir; returns count."""
        if self._running:
            return len(self._entries)
        cache = PreflightCache(settings.output_dir)
        if not cache.available:
            return 0
        entries, fingerprints, signature = cache.load()
        if not entries:
            return 0
        self._settings = settings
        self._cache = cache
        self._entries = OrderedDict(
            (entry.rel, entry)
            for entry in sorted(entries.values(), key=lambda item: item.rel.lower())
        )
        self._fingerprints = dict(fingerprints)
        self._signature = signature
        self._total = len(self._entries)
        self._total_files = len(self._entries)
        self._done = len(self._entries)
        self._dirty = self._check_dirty(settings)
        self.itemsChanged.emit()
        return len(self._entries)

    def start(
        self,
        settings: Settings,
        mode: str = "all",
        only_rel: str | None = None,
        only_rels: list[str] | None = None,
    ) -> bool:
        """Start a scan.

        ``mode="all"`` re-detects every file (or only ``only_rels``);
        ``mode="continue"`` only processes new, changed, or invalidated files.
        """
        if self._running:
            return False
        self._settings = settings
        self._mode = mode
        rels = list(only_rels) if only_rels is not None else None
        if rels is None and only_rel is not None:
            rels = [only_rel]
        self._only_rels = rels
        if rels is None and mode == "all":
            self._entries.clear()
            self._fingerprints.clear()
            self._total = 0
            self._total_files = 0
        self._done = 0
        self._running = True
        self._stop_event = threading.Event()
        self._generation += 1
        self.stateChanged.emit(True)
        self._thread = threading.Thread(
            target=self._run, args=(self._generation,), name="anime-mosaic-preflight", daemon=True
        )
        self._thread.start()
        return True

    def start_if_needed(self, settings: Settings) -> bool:
        if self._running:
            return False
        if self.has_results() and not self.is_stale(settings) and not self._dirty:
            return False
        return self.start(settings, mode="continue")

    def stop(self) -> None:
        if self._running and self._stop_event is not None:
            self._stop_event.set()
            self.log.emit("warn", "正在停止预识别…")

    def wait(self, timeout: float = 5.0) -> None:
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout)

    def clear(self) -> None:
        if self._running:
            return
        self._generation += 1
        self._entries.clear()
        self._fingerprints.clear()
        self._total = 0
        self._total_files = 0
        self._done = 0
        self._signature = None
        self._cache = None
        self._dirty = False
        self.itemsChanged.emit()

    # ------------------------------------------------------------------ manual
    def refresh_manual(self, settings: Settings) -> None:
        store = ManualMaskStore(settings.output_dir)
        changed = False
        for entry in self._entries.values():
            manual = store.has(entry.rel)
            if entry.manual != manual:
                entry.manual = manual
                changed = True
        if changed:
            # A mask appeared/disappeared on disk: the cached result is stale.
            self._dirty = True
        self.itemsChanged.emit()

    def mark_manual(self, rel: str, manual: bool) -> None:
        entry = self._entries.get(rel)
        if entry is not None and entry.manual != manual:
            entry.manual = manual
            self._persist({rel})
            self.itemsChanged.emit()

    def apply_manual(self, rel: str, mask: np.ndarray) -> PreflightEntry | None:
        """Rebuild ``rel`` from a hand-edited mask and persist the result."""
        entry = self._entries.get(rel)
        if entry is None:
            return None
        updated = rebuild_manual_entry(entry, mask)
        self._entries[rel] = updated
        self._persist({rel})
        self.itemsChanged.emit()
        return updated

    def auto_payload(
        self, rel: str, settings: Settings | None = None
    ) -> tuple[bytes | None, bytes | None]:
        """Auto-detected masks for ``rel``, for the editor's reset button.

        Returns the persisted preflight payload when it is an automatic result;
        a hand-edited entry (or a miss) triggers one on-demand detection and
        caches it when the image owns no manual mask.  Runs on a worker thread,
        so it must not touch widgets.
        """
        if self._running:
            raise RuntimeError("预处理正在进行，请等它结束后再重置")
        settings = settings or self._settings
        entry = self._entries.get(rel)
        if entry is not None and not entry.manual:
            cached = entry_mask_png(entry)
            if cached is not None:
                return cached, entry_core_png(entry)
        if settings is None or not settings.input_dir:
            raise RuntimeError("还没有可用的预处理设置，无法自动识别")
        path = (
            entry.path
            if entry is not None and entry.path
            else os.path.join(settings.input_dir, rel)
        )
        if not os.path.isfile(path):
            raise RuntimeError(f"找不到原图：{path}")
        scanner = PreflightScanner(settings, detector_provider=self._detector_provider)
        self.log.emit("info", f"{rel}：正在自动识别马赛克…")
        detected = scanner.scan_one(path, use_manual=False)
        if detected.animated:
            raise RuntimeError("动图不支持自动识别")
        if detected.error:
            raise RuntimeError(detected.error)
        mask = entry_mask_png(detected)
        core = entry_core_png(detected)
        if mask is None and detected.regions > 0:
            raise RuntimeError("自动识别结果不可用")
        store = ManualMaskStore(settings.output_dir) if settings.output_dir else None
        if store is None or not store.has(rel):
            self._settings = settings
            self._entries[rel] = detected
            self._fingerprints.update(scanner.fingerprints)
            self._total_files = max(self._total_files, len(self._entries))
            self._persist({rel})
            self.itemsChanged.emit()
        return mask, core

    def _persist(self, rels: set[str]) -> None:
        settings = self._settings
        if settings is None or not settings.output_dir:
            return
        if self._cache is None:
            self._cache = PreflightCache(settings.output_dir)
        if not self._cache.available:
            return
        manual = ManualMaskStore(settings.output_dir)
        for rel in rels:
            entry = self._entries.get(rel)
            if entry is None:
                continue
            stamp = fingerprint(entry.path)
            try:
                manual_stamp = fingerprint(manual.path_for(rel))[0]
            except (OSError, ValueError):
                manual_stamp = 0
            self._fingerprints[rel] = (stamp[0], stamp[1], manual_stamp)
        self._cache.save(
            self._entries,
            self._fingerprints,
            self._signature,
            write_masks=rels,
        )

    def _check_dirty(self, settings: Settings) -> bool:
        if not settings.input_dir:
            return True
        manual = ManualMaskStore(settings.output_dir)
        for rel, entry in self._entries.items():
            path = entry.path or os.path.join(settings.input_dir, rel)
            stamp = fingerprint(path)
            cached = self._fingerprints.get(rel, (0, 0, 0))
            if stamp != (cached[0], cached[1]):
                return True
            try:
                manual_stamp = fingerprint(manual.path_for(rel))[0]
            except ValueError:
                manual_stamp = 0
            if manual_stamp != cached[2]:
                return True
        return False

    # ------------------------------------------------------------------ worker
    def _run(self, generation: int) -> None:
        try:
            settings = self._settings
            assert settings is not None
            scanner = PreflightScanner(
                settings,
                detector_provider=self._detector_provider,
            )
            cached_entries = {} if self._mode == "all" and self._only_rels is None else dict(
                self._entries
            )
            entries = scanner.scan(
                stop_event=self._stop_event,
                on_total=lambda total: self._on_total(total, generation),
                on_item=lambda entry: self._on_item(entry, generation),
                on_log=lambda level, message: self.log.emit(level, message),
                mode=self._mode,
                only_rels=self._only_rels,
                cached_entries=cached_entries,
                fingerprints=dict(self._fingerprints),
                cached_signature=self._signature,
            )
            if generation != self._generation:
                return
            for entry in entries:
                self._entries[entry.rel] = entry
            self._fingerprints.update(scanner.fingerprints)
            if self._only_rels is None:
                self._total_files = scanner.total
                self._total = scanner.total
            else:
                self._total_files = max(self._total_files, len(self._entries))
            if not scanner.stopped:
                if self._only_rels is None:
                    # Only a full pass may vouch for every entry's settings.
                    self._signature = detection_signature(settings)
                    self._prune_missing(settings)
                self._dirty = self._check_dirty(settings)
            self._done = len(self._entries)
            self._persist({entry.rel for entry in entries})
        except Exception as exc:  # noqa: BLE001 - shown to the user
            self.log.emit("error", f"预识别失败：{exc}")
            self.log.emit("debug", traceback.format_exc())
            self.failed.emit(f"{type(exc).__name__}: {exc}")
        finally:
            if generation == self._generation:
                self._running = False
                self.finished.emit(self.summary())
                self.stateChanged.emit(False)

    def _prune_missing(self, settings: Settings) -> None:
        for rel, entry in list(self._entries.items()):
            path = entry.path or os.path.join(settings.input_dir or "", rel)
            if not os.path.isfile(path):
                del self._entries[rel]
                self._fingerprints.pop(rel, None)

    def _on_total(self, total: int, generation: int) -> None:
        if generation != self._generation:
            return
        self._total = total
        self.started.emit(total)

    def _on_item(self, entry: PreflightEntry, generation: int) -> None:
        if generation != self._generation:
            return
        self._entries[entry.rel] = entry
        self._done = len(self._entries)
        self.itemReady.emit(entry)
        self.progress.emit(self._done, max(1, self._total))
