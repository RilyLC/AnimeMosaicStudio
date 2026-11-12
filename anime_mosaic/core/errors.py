"""Domain errors, kept in one place so every layer can catch them."""

from __future__ import annotations


class AnimeMosaicError(RuntimeError):
    """Base class for every error this application raises deliberately."""


class PipelineError(AnimeMosaicError):
    """A batch cannot start or an image cannot be processed."""


class DetectorError(AnimeMosaicError):
    """The YOLO detector is missing or failed to load."""


class ComfyError(AnimeMosaicError):
    """ComfyUI is unreachable, rejected the workflow or failed to finish."""


class Cancelled(AnimeMosaicError):
    """The user asked to stop; the current image is intentionally discarded."""
