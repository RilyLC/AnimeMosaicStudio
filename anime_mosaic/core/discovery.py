"""Filesystem discovery: images and Ultralytics weights.

ComfyUI and Python locations are never guessed here.  The only folder scanned
for weights is a ``comfy_dir`` the user configured explicitly.
"""

from __future__ import annotations

import glob
import os

from .settings import IMAGE_EXTS


def looks_like_comfy(path: str) -> bool:
    return bool(path) and os.path.isfile(os.path.join(path, "folder_paths.py")) and os.path.isdir(
        os.path.join(path, "models")
    )


def find_ultralytics_model(comfy_dir: str, kind: str) -> str:
    """Find mosaic / nsfw YOLO weights under ``models/ultralytics``."""
    if not comfy_dir:
        return ""
    root = os.path.join(comfy_dir, "models", "ultralytics")
    if not os.path.isdir(root):
        return ""
    files = glob.glob(os.path.join(root, "**", "*.pt"), recursive=True)
    if kind == "mosaic":
        found = [f for f in files if "mosaic" in os.path.basename(f).lower()]
        found.sort(key=lambda f: (0 if "_l." in os.path.basename(f).lower() else 1, -_size(f)))
    else:
        found = [f for f in files if "nsfw" in os.path.basename(f).lower()]
        found.sort(key=lambda f: -_size(f))
    return found[0] if found else ""


def discover_images(
    input_dir: str,
    output_dir: str,
    include_subdirs: bool = True,
    exts: set[str] | None = None,
) -> list[str]:
    """All image files under ``input_dir``, sorted, excluding the output tree.

    ``include_subdirs=False`` only scans the top level of ``input_dir``.
    """
    exts = exts or IMAGE_EXTS
    out_abs = os.path.abspath(output_dir)
    files: list[str] = []

    def consider(path: str) -> None:
        if os.path.splitext(path)[1].lower() not in exts:
            return
        try:
            if os.path.getsize(path) <= 0:
                return
        except OSError:
            return
        files.append(path)

    if include_subdirs:
        for root, dirs, names in os.walk(input_dir):
            dirs[:] = [
                d
                for d in dirs
                if os.path.abspath(os.path.join(root, d)) != out_abs
                and not d.startswith(".")
                and d not in ("__pycache__", "$RECYCLE.BIN", "System Volume Information")
            ]
            for name in names:
                consider(os.path.join(root, name))
    else:
        try:
            with os.scandir(input_dir) as entries:
                for entry in entries:
                    try:
                        if entry.is_file():
                            consider(entry.path)
                    except OSError:
                        continue
        except OSError:
            return []

    files.sort(key=lambda p: p.lower())
    return files


def count_images(input_dir: str, output_dir: str = "", include_subdirs: bool = True) -> int:
    return len(discover_images(input_dir, output_dir, include_subdirs))


def _size(path: str) -> int:
    try:
        return os.path.getsize(path)
    except OSError:
        return 0
