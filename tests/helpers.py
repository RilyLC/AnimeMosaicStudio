"""Test-only fakes: deterministic detector and ComfyUI client."""

from __future__ import annotations

import io
import os
from typing import Any

import numpy as np
from PIL import Image

from anime_mosaic.core.detector import Detection


class FakeDetector:
    """Paints one fixed rectangle when the image has the expected width."""

    def __init__(self, trigger_width: int, box: tuple[int, int, int, int]):
        self.trigger_width = trigger_width
        self.box = box
        self.active_device = "cpu"
        self.loaded = False

    def load(self) -> None:
        self.loaded = True

    def detect(self, rgb: np.ndarray):
        height, width = rgb.shape[:2]
        mask = np.zeros((height, width), np.uint8)
        detections: list[Detection] = []
        if width != self.trigger_width:
            return mask, detections
        x, y, w, h = self.box
        mask[y : y + h, x : x + w] = 255
        detections.append(
            Detection(float(x), float(y), float(w), float(h), 0, "mosaic", 0.91)
        )
        return mask, detections


class LegacyFakeDetector:
    """Same mask, but returns the dict shape the legacy pipeline expects."""

    def __init__(self, trigger_width: int, box: tuple[int, int, int, int]):
        self.trigger_width = trigger_width
        self.box = box
        self.active_device = "cpu"

    def load(self) -> None:
        pass

    def detect(self, rgb: np.ndarray):
        height, width = rgb.shape[:2]
        mask = np.zeros((height, width), np.uint8)
        detections = []
        if width != self.trigger_width:
            return mask, detections
        x, y, w, h = self.box
        mask[y : y + h, x : x + w] = 255
        detections.append({"x": x, "y": y, "w": w, "h": h, "cls": 0, "name": "mosaic", "conf": 0.91})
        return mask, detections


class FakeComfyClient:
    """In-memory ComfyUI: echoes an altered crop as the generated image."""

    def __init__(self):
        self.uploads: dict[str, Image.Image] = {}
        self.generated: dict[str, Image.Image] = {}
        self.prompts: list[dict] = []
        self.interrupted = False
        self._counter = 0

    # --- environment -----------------------------------------------------
    def ping(self) -> dict:
        return {"system": {"comfyui_version": "fake-1.0"}}

    def check_environment(self, names) -> list[str]:
        return []

    # --- upload/run/download --------------------------------------------
    def upload_png(self, image: Image.Image, subfolder: str, filename: str) -> str:
        name = f"{subfolder}/{filename}"
        self.uploads[name] = image.copy()
        return name

    def run_prompt(self, prompt: dict, timeout: float = 900, stop_event=None) -> dict:
        self.prompts.append(prompt)
        image_name = prompt["5"]["inputs"]["image"]
        source = self.uploads[image_name].convert("RGB")
        array = np.array(source).astype(np.int16)
        altered = np.stack(
            [array[..., 2], np.clip(array[..., 1] + 25, 0, 255), array[..., 0]], axis=-1
        ).astype(np.uint8)
        generated = Image.fromarray(altered)
        self._counter += 1
        output_name = f"gen_{self._counter}.png"
        self.generated[output_name] = generated
        return {"filename": output_name, "subfolder": "", "type": "output"}

    def download(self, info: dict) -> Image.Image:
        return self.generated[info["filename"]].copy()

    def interrupt(self) -> None:
        self.interrupted = True


def make_test_image(path: str, width: int, height: int, mode: str = "RGB") -> None:
    """Deterministic gradient image with enough structure for blending."""
    x = np.linspace(0, 255, width, dtype=np.float32)
    y = np.linspace(0, 255, height, dtype=np.float32)
    grid = (x[None, :] * 0.6 + y[:, None] * 0.4).astype(np.uint8)
    rgb = np.stack([grid, np.clip(255 - grid, 0, 255), (grid // 2 + 40)], axis=-1)
    image = Image.fromarray(rgb, "RGB")
    if mode == "RGBA":
        image = image.convert("RGBA")
        alpha = Image.linear_gradient("L").resize((width, height))
        image.putalpha(alpha)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    image.save(path)


def png_bytes(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def read_csv_rows(path: str) -> list[list[str]]:
    import csv

    with open(path, "r", encoding="utf-8-sig", newline="") as handle:
        return [row for row in csv.reader(handle)]


def normalise_manifest(rows: list[list[str]]) -> list[list[str]]:
    """Drop timing columns so two runs are comparable."""
    return [[row[0], row[1], row[2], row[4], row[5], row[6]] for row in rows[1:]]


def first_difference(a: Any, b: Any) -> str | None:
    if isinstance(a, dict) and isinstance(b, dict):
        if set(a) != set(b):
            return f"key mismatch {set(a) ^ set(b)}"
        for key in a:
            diff = first_difference(a[key], b[key])
            if diff:
                return f"{key}: {diff}"
        return None
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return f"length {len(a)} != {len(b)}"
        for index, (item_a, item_b) in enumerate(zip(a, b)):
            diff = first_difference(item_a, item_b)
            if diff:
                return f"[{index}] {diff}"
        return None
    return None if a == b else f"{a!r} != {b!r}"
