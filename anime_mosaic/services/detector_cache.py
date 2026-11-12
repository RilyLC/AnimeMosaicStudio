"""Shared, thread-safe cache for the detection models.

Loading the YOLO weights takes several seconds and happens in three places:
the startup warm-up, pre-recognition and the batch pipeline.  Keep one loaded
pair per model/device configuration so opening pre-recognition after launch is
instant and starting a batch does not load the same weights again.
"""

from __future__ import annotations

import threading
from typing import Callable

from ..core.detector import Detector, MosaicDetector
from ..core.settings import Settings
from .preflight import load_detectors


def model_signature(settings: Settings) -> tuple:
    """Settings that require a fresh detector instance."""
    return (
        settings.comfy_dir,
        settings.mosaic_model,
        settings.nsfw_model,
        settings.device,
        settings.imgsz,
        settings.conf,
        settings.nsfw_mode,
    )


class DetectorCache:
    """Lazily load and reuse detectors; concurrent callers share one load."""

    def __init__(
        self,
        detector_factory: Callable[..., Detector] = MosaicDetector,
    ):
        self._factory = detector_factory
        self._condition = threading.Condition()
        self._loading = False
        self._signature: tuple | None = None
        self._value: tuple[Detector, Detector | None, str] | None = None

    @property
    def model_name(self) -> str:
        return self._value[2] if self._value else ""

    def get(self, settings: Settings) -> tuple[Detector, Detector | None, str]:
        """Return ``(mosaic, nsfw, model_name)``, loading them if necessary."""
        signature = model_signature(settings)
        with self._condition:
            while self._loading:
                self._condition.wait()
            if self._signature == signature and self._value is not None:
                return self._value
            self._loading = True
        try:
            value = load_detectors(settings, self._factory)
        except Exception:
            with self._condition:
                self._loading = False
                self._condition.notify_all()
            raise
        with self._condition:
            self._signature = signature
            self._value = value
            self._loading = False
            self._condition.notify_all()
        return value

    def invalidate(self) -> None:
        with self._condition:
            self._signature = None
            self._value = None
