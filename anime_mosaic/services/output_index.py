"""Pair every input image with its output file, without depending on a run."""

from __future__ import annotations

import csv
import os
from dataclasses import dataclass
from typing import Iterable

from ..core.discovery import discover_images
from ..core.manifest import FILENAME, LEGACY_FILENAME
from .output_state import state_key


@dataclass(frozen=True)
class OutputEntry:
    rel: str
    input_path: str
    output_path: str
    size: int
    mtime: float
    status: str = "unknown"
    reused: bool = False

    @property
    def is_processed(self) -> bool:
        """True for a real mosaic.

        Unknown historical outputs are treated as processed because we cannot
        prove they are byte-identical copies; only an explicit ``copied``
        manifest row becomes "未处理（原图复制）".
        """
        return self.status != "copied"

    @property
    def status_label(self) -> str:
        if self.status == "copied":
            return "未处理（原图复制）"
        if self.reused:
            return "已处理（复用）"
        return "已处理"


@dataclass(frozen=True)
class OutputScan:
    entries: list[OutputEntry]
    total_input: int


_STATUS_MAP = {
    "processed": "processed",
    "copied": "copied",
    "skipped": "processed",
}


_SAMPLE_BYTES = 64 * 1024


def _looks_copied(input_path: str, output_path: str) -> bool:
    """Cheap byte-identity check for outputs without a manifest row.

    A copied output is byte-identical.  Comparing three samples (start,
    middle, end) catches that without reading every large image in full, and
    avoids treating two unrelated files with the same size as copies.
    """
    try:
        size = os.path.getsize(input_path)
        if size != os.path.getsize(output_path):
            return False
        if size <= 0:
            return False
        offsets = {
            0,
            max(0, size // 2 - _SAMPLE_BYTES // 2),
            max(0, size - _SAMPLE_BYTES),
        }
        with open(input_path, "rb") as left, open(output_path, "rb") as right:
            for offset in offsets:
                left.seek(offset)
                right.seek(offset)
                if left.read(_SAMPLE_BYTES) != right.read(_SAMPLE_BYTES):
                    return False
        return True
    except OSError:
        return False


def _manifest_status(output_dir: str) -> dict[str, tuple[str, bool]]:
    """Read both manifest generations; the newer row wins."""
    if not output_dir:
        return {}
    table: dict[str, tuple[str, bool]] = {}
    for name in (LEGACY_FILENAME, FILENAME):
        path = os.path.join(output_dir, name)
        try:
            handle = open(path, "r", encoding="utf-8-sig", newline="")
        except OSError:
            continue
        with handle:
            try:
                rows = csv.DictReader(handle)
                for row in rows:
                    rel = (row.get("file") or "").strip()
                    status = _STATUS_MAP.get((row.get("status") or "").strip().lower())
                    if rel and status:
                        reused = (row.get("reused") or "").strip().lower() in ("1", "true", "yes")
                        table[state_key(rel)] = (status, reused)
            except (csv.Error, OSError, UnicodeError):
                continue
    return table


def scan_outputs(
    input_dir: str,
    output_dir: str,
    include_subdirs: bool = True,
) -> OutputScan:
    """Scan input and pair each existing output, sorted by relative path.

    The output directory is never treated as an input source.  Only non-empty
    output files are listed; inputs that have not been processed yet remain in
    ``total_input`` so the UI can show progress.  ``status`` comes from the run
    manifest when available.
    """
    if not input_dir or not os.path.isdir(input_dir):
        return OutputScan([], 0)
    files = discover_images(input_dir, output_dir, include_subdirs)
    out_abs = os.path.abspath(output_dir) if output_dir else ""
    statuses = _manifest_status(output_dir)
    entries: list[OutputEntry] = []
    for input_path in files:
        rel = os.path.relpath(input_path, input_dir)
        if not out_abs:
            continue
        output_path = os.path.join(output_dir, rel)
        try:
            stat = os.stat(output_path)
        except OSError:
            continue
        if not os.path.isfile(output_path) or stat.st_size <= 0:
            continue
        key = state_key(rel)
        manifest = statuses.get(key)
        if manifest is None:
            status = "copied" if _looks_copied(input_path, output_path) else "unknown"
            reused = False
        else:
            status, reused = manifest
        entries.append(
            OutputEntry(
                rel=rel,
                input_path=input_path,
                output_path=output_path,
                size=stat.st_size,
                mtime=stat.st_mtime,
                status=status,
                reused=reused,
            )
        )
    entries.sort(key=lambda entry: entry.rel.lower())
    return OutputScan(entries, len(files))


def entry_from_paths(
    rel: str,
    input_dir: str,
    output_path: str,
    status: str = "unknown",
    reused: bool = False,
) -> OutputEntry | None:
    """Build one entry after a live result without rescanning the whole tree."""
    try:
        stat = os.stat(output_path)
    except OSError:
        return None
    if not os.path.isfile(output_path) or stat.st_size <= 0:
        return None
    return OutputEntry(
        rel=rel,
        input_path=os.path.join(input_dir, rel),
        output_path=output_path,
        size=stat.st_size,
        mtime=stat.st_mtime,
        status=status,
        reused=reused,
    )


def human_size(size: int) -> str:
    value = float(max(0, size))
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


def merge_entries(existing: Iterable[OutputEntry], updates: Iterable[OutputEntry]) -> list[OutputEntry]:
    """Upsert live results into an already sorted list."""
    table = {entry.rel: entry for entry in existing}
    for entry in updates:
        table[entry.rel] = entry
    return sorted(table.values(), key=lambda entry: entry.rel.lower())
