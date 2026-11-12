"""Candidate groups for differential reuse, shown in the preprocessing dialog.

The grouping here is intentionally conservative and cheap: it only looks at
the final masks that preprocessing already produced.  The pipeline still does
the exact pixel comparison before it actually reuses a generated crop.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

import numpy as np

from ..core.manual_mask import decode_mask
from .output_state import state_key

STATE_FILENAME = "_AnimeMosaicStudio_reuse_groups.json"
VERSION = 1


@dataclass
class ReuseGroup:
    key: str
    rels: tuple[str, ...]
    regions: int
    coverage: float
    iou: float
    representative: str
    width: int
    height: int
    mask: np.ndarray = field(repr=False, compare=False)
    probe: np.ndarray = field(default=None, repr=False, compare=False)

    @property
    def count(self) -> int:
        return len(self.rels)

    @property
    def summary(self) -> str:
        return (
            f"{self.count} 张 · {self.regions} 处/张 · "
            f"覆盖 {self.coverage:.2f}% · 重合 {self.iou:.0%}"
        )


def mask_iou(left: np.ndarray, right: np.ndarray) -> float:
    if left.shape != right.shape:
        return 0.0
    l = left > 0
    r = right > 0
    union = int(np.logical_or(l, r).sum())
    if not union:
        return 0.0
    return float(np.logical_and(l, r).sum()) / union


def _probe(mask: np.ndarray, max_side: int = 160) -> np.ndarray:
    """Downsample only for candidate search; the pipeline re-checks exact pixels."""
    step = max(1, max(mask.shape[:2]) // max_side)
    return mask[::step, ::step]


def build_groups(
    entries,
    load_mask,
    *,
    min_iou: float = 0.85,
) -> list[ReuseGroup]:
    """Group adjacent preprocessing entries with near-identical masks.

    A group is seeded by the first image and only accepts later images that
    match that seed.  This avoids transitive merging (A≈B, B≈C but A≠C).
    """
    groups: list[ReuseGroup] = []
    for entry in sorted(entries, key=lambda item: item.rel.lower()):
        if getattr(entry, "error", "") or getattr(entry, "animated", False):
            continue
        mask = load_mask(entry)
        if mask is None or not (mask > 0).any():
            continue
        probe = _probe(mask)
        matched: ReuseGroup | None = None
        score = 0.0
        for group in groups:
            if group.width != mask.shape[1] or group.height != mask.shape[0]:
                continue
            if group.regions != int(entry.regions):
                continue
            if abs(group.coverage - float(entry.coverage)) > max(0.75, group.coverage * 0.12):
                continue
            iou = mask_iou(group.probe, probe)
            if iou >= min_iou:
                matched = group
                score = iou
                break
        if matched is None:
            groups.append(
                ReuseGroup(
                    key=f"g{len(groups) + 1}",
                    rels=(entry.rel,),
                    regions=int(entry.regions),
                    coverage=float(entry.coverage),
                    iou=1.0,
                    representative=entry.rel,
                    width=mask.shape[1],
                    height=mask.shape[0],
                    mask=mask.copy(),
                    probe=probe.copy(),
                )
            )
            continue
        count = matched.count
        matched.rels = (*matched.rels, entry.rel)
        matched.coverage = (
            matched.coverage * count + float(entry.coverage)
        ) / (count + 1)
        matched.iou = min(matched.iou, score)
    return [group for group in groups if group.count >= 2]


def load_disabled(output_dir: str) -> set[str]:
    if not output_dir:
        return set()
    path = os.path.join(output_dir, STATE_FILENAME)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError, TypeError):
        return set()
    values = data.get("disabled", []) if isinstance(data, dict) else []
    if isinstance(values, dict):
        values = [key for key, enabled in values.items() if not enabled]
    return {state_key(str(value)) for value in values if str(value).strip()}


def save_disabled(output_dir: str, rels) -> bool:
    if not output_dir:
        return False
    try:
        os.makedirs(output_dir, exist_ok=True)
        path = os.path.join(output_dir, STATE_FILENAME)
        tmp = path + ".tmp"
        payload = {
            "version": VERSION,
            "disabled": sorted(state_key(rel) for rel in rels if str(rel).strip()),
        }
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        return True
    except OSError:
        return False


def load_mask_for_entry(entry, mask_store):
    manual = None
    if mask_store is not None:
        try:
            manual = mask_store.load(entry.rel)
        except (OSError, ValueError):
            manual = None
    if manual is not None and (manual > 0).any():
        return manual
    data = entry.mask_png
    if data is None and getattr(entry, "mask_file", ""):
        try:
            with open(entry.mask_file, "rb") as handle:
                data = handle.read()
        except OSError:
            data = None
    if data:
        try:
            return decode_mask(data)
        except ValueError:
            return None
    return None
