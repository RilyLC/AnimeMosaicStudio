"""Read past run timings so the UI can estimate batch duration."""

from __future__ import annotations

import csv
import os
from statistics import median

from ..core.manifest import FILENAME, LEGACY_FILENAME


def recent_average_seconds(output_dir: str, sample: int = 200) -> float | None:
    """Median seconds-per-image from the manifest, or ``None`` if unknown."""
    for name in (FILENAME, LEGACY_FILENAME):
        path = os.path.join(output_dir, name)
        if not os.path.isfile(path):
            continue
        values = _read_durations(path, sample)
        if values:
            return median(values)
    return None


def _read_durations(path: str, sample: int) -> list[float]:
    durations: list[float] = []
    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                if row.get("status") not in ("processed", "copied"):
                    continue
                try:
                    seconds = float(row.get("seconds") or 0)
                except ValueError:
                    continue
                if seconds > 0:
                    durations.append(seconds)
    except OSError:
        return []
    return durations[-sample:]


def last_run_stats(output_dir: str) -> dict:
    path = os.path.join(output_dir, FILENAME)
    if not os.path.isfile(path):
        path = os.path.join(output_dir, LEGACY_FILENAME)
    stats = {"files": 0, "regions": 0, "seconds": 0.0}
    if not os.path.isfile(path):
        return stats
    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                stats["files"] += 1
                try:
                    stats["regions"] += int(row.get("regions") or 0)
                    stats["seconds"] += float(row.get("seconds") or 0)
                except ValueError:
                    pass
    except OSError:
        pass
    return stats
