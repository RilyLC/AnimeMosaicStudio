"""YOLO segmentation detector for mosaic / NSFW regions."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol

import cv2
import numpy as np

from .errors import DetectorError


@dataclass(frozen=True)
class Detection:
    x: float
    y: float
    w: float
    h: float
    cls: int
    name: str
    conf: float

    def as_text(self) -> str:
        return f"{self.name}:{self.conf:.2f}"

    def as_dict(self) -> dict:
        return {
            "x": self.x,
            "y": self.y,
            "w": self.w,
            "h": self.h,
            "cls": self.cls,
            "name": self.name,
            "conf": self.conf,
        }


class Detector(Protocol):
    """Anything that can turn an RGB array into (mask, detections)."""

    def detect(self, rgb: np.ndarray) -> tuple[np.ndarray, list[Detection]]: ...


class MosaicDetector:
    """Wraps an Ultralytics segmentation model and produces a binary mask."""

    def __init__(
        self,
        model_path: str,
        device: str = "gpu",
        imgsz: int = 1280,
        conf: float = 0.25,
        iou: float = 0.5,
    ):
        self.model_path = model_path
        self.device = (device or "gpu").lower()
        self.imgsz = int(imgsz)
        self.conf = float(conf)
        self.iou = float(iou)
        self.model = None
        self.names: dict[int, str] = {}
        self.active_device = "cpu"

    def load(self) -> None:
        if self.model is not None:
            return
        if not self.model_path or not os.path.isfile(self.model_path):
            raise DetectorError(f"检测模型不存在：{self.model_path}")
        try:
            from ultralytics import YOLO
        except Exception as exc:  # pragma: no cover - environment dependent
            raise DetectorError(f"无法导入 ultralytics：{exc}") from exc

        self.model = YOLO(self.model_path)
        raw_names = self.model.names
        self.names = raw_names if isinstance(raw_names, dict) else dict(enumerate(raw_names))
        self.active_device = self._pick_device()

    def _pick_device(self):
        if self.device not in ("gpu", "cuda", "0", "auto"):
            return "cpu"
        try:
            import torch

            if torch.cuda.is_available():
                return 0
        except Exception:
            pass
        return "cpu"

    def _predict(self, bgr: np.ndarray):
        return self.model.predict(
            bgr,
            imgsz=self.imgsz,
            conf=self.conf,
            iou=self.iou,
            verbose=False,
            device=self.active_device,
            max_det=100,
        )[0]

    def detect(self, rgb: np.ndarray) -> tuple[np.ndarray, list[Detection]]:
        """Return a 0/255 mask and the detection metadata for one RGB image."""
        self.load()
        bgr = np.ascontiguousarray(rgb[:, :, ::-1])
        try:
            result = self._predict(bgr)
        except Exception as exc:
            message = str(exc)
            gpu_error = (
                self.active_device != "cpu"
                and ("CUDA" in message or "memory" in message.lower() or "cudnn" in message.lower())
            )
            if not gpu_error:
                raise
            self.active_device = "cpu"
            try:
                self.model.to("cpu")
            except Exception:
                pass
            result = self._predict(bgr)

        height, width = rgb.shape[:2]
        mask = np.zeros((height, width), np.uint8)
        detections: list[Detection] = []
        if result.boxes is None or len(result.boxes) == 0:
            return mask, detections

        polygons = result.masks.xy if result.masks is not None else []
        for index, box in enumerate(result.boxes):
            x1, y1, x2, y2 = [float(value) for value in box.xyxy[0].tolist()]
            class_id = int(box.cls[0])
            detections.append(
                Detection(
                    x=x1,
                    y=y1,
                    w=max(1.0, x2 - x1),
                    h=max(1.0, y2 - y1),
                    cls=class_id,
                    name=str(self.names.get(class_id, class_id)),
                    conf=float(box.conf[0]),
                )
            )
            if index < len(polygons) and len(polygons[index]) >= 3:
                cv2.fillPoly(mask, [np.round(polygons[index]).astype(np.int32)], 255)
            else:
                cv2.rectangle(mask, (int(x1), int(y1)), (int(x2), int(y2)), 255, -1)
        return mask, detections


def detections_text(detections: list[Detection], limit: int | None = 300) -> str:
    text = "; ".join(detection.as_text() for detection in detections)
    return text[:limit] if limit is not None else text


def augment_mask_with_nsfw(
    mask: np.ndarray,
    nsfw_mask: np.ndarray,
    detections: list[Detection],
    width: int,
    height: int,
) -> np.ndarray:
    """Union only the genuinely explicit NSFW regions into the mosaic mask."""
    keep = {"pussy", "anus", "penis", "testicles"}
    allowed = np.zeros_like(nsfw_mask)
    for detection in detections:
        if detection.name.lower() not in keep:
            continue
        x0 = int(max(0, detection.x))
        y0 = int(max(0, detection.y))
        x1 = int(min(width, detection.x + detection.w))
        y1 = int(min(height, detection.y + detection.h))
        allowed[y0:y1, x0:x1] = nsfw_mask[y0:y1, x0:x1]
    return cv2.bitwise_or(mask, allowed)
