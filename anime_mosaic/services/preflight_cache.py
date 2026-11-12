"""Persisted pre-recognition results.

Keeping the results next to the output lets a restart reuse them instead of
running the detector again::

    <output>/_AnimeMosaicStudio_preflight/index.json
    <output>/_AnimeMosaicStudio_preflight/masks/<rel>.mask.png
    <output>/_AnimeMosaicStudio_preflight/masks/<rel>.core.png

The index is rewritten atomically; masks are only rewritten for the images a
run actually revisited.  A missing or unreadable index simply means "no cache"
— the scanner then behaves exactly like before.
"""

from __future__ import annotations

import json
import os
import shutil

from .preflight import PreflightEntry, fingerprint

CACHE_DIRNAME = "_AnimeMosaicStudio_preflight"
INDEX_NAME = "index.json"
MASKS_DIRNAME = "masks"
VERSION = 1

#: fingerprint = (image mtime_ns, image size, manual-mask mtime_ns)
Fingerprint = tuple[int, int, int]


class PreflightCache:
    def __init__(self, output_dir: str):
        self.output_dir = output_dir
        self.root = os.path.join(output_dir, CACHE_DIRNAME) if output_dir else ""
        self.index_path = os.path.join(self.root, INDEX_NAME) if self.root else ""

    # ------------------------------------------------------------------ paths
    @property
    def available(self) -> bool:
        return bool(self.root)

    def mask_path(self, rel: str) -> str:
        return self._path(rel, ".mask.png")

    def core_path(self, rel: str) -> str:
        return self._path(rel, ".core.png")

    def _path(self, rel: str, suffix: str) -> str:
        normalized = os.path.normpath(rel)
        if os.path.isabs(normalized) or normalized.startswith(".."):
            raise ValueError(f"非法的相对路径：{rel}")
        return os.path.join(self.root, MASKS_DIRNAME, normalized + suffix)

    # ------------------------------------------------------------------- load
    def load(self) -> tuple[dict[str, PreflightEntry], dict[str, Fingerprint], tuple | None]:
        """Return ``(entries, fingerprints, signature)``; empty when unusable."""
        if not self.index_path or not os.path.isfile(self.index_path):
            return {}, {}, None
        try:
            with open(self.index_path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            return {}, {}, None
        if not isinstance(data, dict) or data.get("version") != VERSION:
            return {}, {}, None
        raw = data.get("entries")
        if not isinstance(raw, dict):
            return {}, {}, None
        entries: dict[str, PreflightEntry] = {}
        fingerprints: dict[str, Fingerprint] = {}
        for rel, item in raw.items():
            if not isinstance(item, dict):
                continue
            try:
                mask_file = self.mask_path(rel)
                core_file = self.core_path(rel)
            except ValueError:
                continue
            has_mask = bool(item.get("mask"))
            if has_mask and not os.path.isfile(mask_file):
                # The mask payload is gone; force this image to be scanned again.
                continue
            entries[rel] = PreflightEntry(
                path=str(item.get("path") or ""),
                rel=rel,
                width=int(item.get("width") or 0),
                height=int(item.get("height") or 0),
                regions=int(item.get("regions") or 0),
                coverage=float(item.get("coverage") or 0.0),
                detections=str(item.get("detections") or ""),
                nsfw_text=str(item.get("nsfw_text") or ""),
                nsfw_boxes=tuple(
                    tuple(box) for box in (item.get("nsfw_boxes") or ()) if isinstance(box, (list, tuple))
                ),
                error=str(item.get("error") or ""),
                animated=bool(item.get("animated")),
                manual=bool(item.get("manual")),
                mask_file=mask_file if has_mask else "",
                core_file=(
                    core_file
                    if item.get("core") and os.path.isfile(core_file)
                    else ""
                ),
            )
            fingerprints[rel] = (
                int(item.get("mtime") or 0),
                int(item.get("size") or 0),
                int(item.get("manual_mtime") or 0),
            )
        signature = data.get("signature")
        signature = tuple(signature) if isinstance(signature, list) else None
        return entries, fingerprints, signature

    # ------------------------------------------------------------------- save
    def save(
        self,
        entries: dict[str, PreflightEntry],
        fingerprints: dict[str, Fingerprint],
        signature: tuple | None,
        *,
        write_masks: set[str] | None = None,
    ) -> bool:
        """Persist ``entries``; only ``write_masks`` images get mask files."""
        if not self.root:
            return False
        try:
            os.makedirs(os.path.join(self.root, MASKS_DIRNAME), exist_ok=True)
            targets = [
                (rel, entry)
                for rel, entry in entries.items()
                if write_masks is None or rel in write_masks
            ]
            for rel, entry in targets:
                self._write_mask(rel, entry)
            payload = {
                "version": VERSION,
                "signature": list(signature) if signature is not None else None,
                "entries": {
                    rel: self._entry_data(rel, entry, fingerprints.get(rel, (0, 0, 0)))
                    for rel, entry in entries.items()
                },
            }
            self._write_index(payload)
            return True
        except OSError:
            return False

    def clear(self) -> None:
        if self.root:
            shutil.rmtree(self.root, ignore_errors=True)

    # ---------------------------------------------------------------- helpers
    def _entry_data(self, rel: str, entry: PreflightEntry, fp: Fingerprint) -> dict:
        try:
            has_mask = os.path.isfile(self.mask_path(rel))
            has_core = os.path.isfile(self.core_path(rel))
        except ValueError:
            has_mask = has_core = False
        return {
            "path": entry.path,
            "width": entry.width,
            "height": entry.height,
            "regions": entry.regions,
            "coverage": round(float(entry.coverage), 4),
            "detections": entry.detections,
            "nsfw_text": entry.nsfw_text,
            "nsfw_boxes": [list(box) for box in entry.nsfw_boxes],
            "error": entry.error,
            "animated": entry.animated,
            "manual": entry.manual,
            "mask": has_mask,
            "core": has_core,
            "mtime": int(fp[0]),
            "size": int(fp[1]),
            "manual_mtime": int(fp[2]),
        }

    def _write_mask(self, rel: str, entry: PreflightEntry) -> None:
        self._write_payload(self.mask_path(rel), entry.mask_png, entry.mask_file)
        self._write_payload(self.core_path(rel), entry.core_mask_png, entry.core_file)

    @staticmethod
    def _write_payload(path: str, data: bytes | None, existing: str) -> None:
        if data is None:
            if existing and os.path.isfile(existing):
                return  # untouched cached entry
            try:
                os.remove(path)
            except FileNotFoundError:
                pass
            return
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "wb") as handle:
            handle.write(data)
        os.replace(tmp, path)

    def _write_index(self, payload: dict) -> None:
        tmp = self.index_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=1)
        os.replace(tmp, self.index_path)
