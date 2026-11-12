"""Manual masks persisted next to the output files.

A mask is a grayscale PNG at full image resolution.  It lives under
``<output>/_AnimeMosaicStudio_masks/<relative path>.mask.png`` so it survives
restarts and stays clearly separate from processed images.
"""

from __future__ import annotations

import os
import shutil

import cv2
import numpy as np

MASK_DIRNAME = "_AnimeMosaicStudio_masks"


def encode_mask(mask: np.ndarray) -> bytes:
    normalized = np.where(mask > 127, 255, 0).astype(np.uint8)
    ok, buffer = cv2.imencode(".png", normalized, [cv2.IMWRITE_PNG_COMPRESSION, 3])
    if not ok:
        raise ValueError("无法编码遮罩")
    return buffer.tobytes()


def decode_mask(data: bytes) -> np.ndarray:
    array = np.frombuffer(data, dtype=np.uint8)
    mask = cv2.imdecode(array, cv2.IMREAD_GRAYSCALE)
    if mask is None:
        raise ValueError("无法解码遮罩")
    return np.where(mask > 127, 255, 0).astype(np.uint8)


class ManualMaskStore:
    def __init__(self, output_dir: str):
        self.output_dir = output_dir
        self.root = os.path.join(output_dir, MASK_DIRNAME)

    # ------------------------------------------------------------------ paths
    def path_for(self, rel: str) -> str:
        normalized = os.path.normpath(rel)
        if os.path.isabs(normalized) or normalized.startswith(".."):
            raise ValueError(f"非法的相对路径：{rel}")
        return os.path.join(self.root, normalized + ".mask.png")

    def has(self, rel: str) -> bool:
        try:
            return os.path.isfile(self.path_for(rel))
        except ValueError:
            return False

    # ------------------------------------------------------------------- I/O
    def load(self, rel: str) -> np.ndarray | None:
        try:
            path = self.path_for(rel)
        except ValueError:
            return None
        if not os.path.isfile(path):
            return None
        try:
            with open(path, "rb") as handle:
                return decode_mask(handle.read())
        except (OSError, ValueError):
            return None

    def save(self, rel: str, mask: np.ndarray) -> str:
        path = self.path_for(rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "wb") as handle:
            handle.write(encode_mask(mask))
        os.replace(tmp, path)
        return path

    def delete(self, rel: str) -> None:
        try:
            path = self.path_for(rel)
        except ValueError:
            return
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        except OSError:
            pass

    def clear(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)
