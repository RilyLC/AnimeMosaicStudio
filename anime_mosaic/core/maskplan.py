"""Build a mask plan shared by batch processing and pre-recognition.

Keeping this logic in one place guarantees that the mask a user previews (and
edits) is built exactly like the mask the pipeline would use.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from .detector import Detection, Detector, augment_mask_with_nsfw, detections_text
from .masking import Region, connected_regions, grow_mask
from .settings import Settings


@dataclass
class MaskPlan:
    mask: np.ndarray
    editable_mask: np.ndarray
    regions: list[Region]
    detections: list[Detection]
    nsfw_text: str = ""
    nsfw_detections: list[Detection] | None = None
    manual: bool = False
    core_mask: np.ndarray | None = None

    @property
    def empty(self) -> bool:
        return not self.mask.any()

    @property
    def coverage_pct(self) -> float:
        return float((self.mask > 0).mean() * 100.0) if self.mask.size else 0.0

    @property
    def editable_coverage_pct(self) -> float:
        return float((self.editable_mask > 0).mean() * 100.0) if self.editable_mask.size else 0.0

    def detection_text(self, limit: int | None = 300) -> str:
        return detections_text(self.detections, limit=limit)


def build_mask_plan(
    rgb: np.ndarray,
    detector: Detector,
    nsfw_detector: Detector | None,
    settings: Settings,
) -> MaskPlan:
    """Detect, grow, and filter the mask for one image (automatic mode)."""
    mask, detections = detector.detect(rgb)
    nsfw_text = ""
    nsfw_detections: list[Detection] = []

    if nsfw_detector is not None:
        nsfw_mask, nsfw_detections = nsfw_detector.detect(rgb)
        nsfw_text = detections_text(nsfw_detections, limit=None)
        if settings.nsfw_mode == "augment" and nsfw_detections:
            height, width = rgb.shape[:2]
            mask = augment_mask_with_nsfw(mask, nsfw_mask, nsfw_detections, width, height)

    if mask.max() == 0:
        return MaskPlan(
            mask=mask,
            editable_mask=np.zeros_like(mask),
            regions=[],
            detections=detections,
            nsfw_text=nsfw_text,
            nsfw_detections=nsfw_detections,
            core_mask=np.zeros_like(mask),
        )

    core_mask = mask.copy()
    mask = grow_mask(mask, settings.grow)
    regions = connected_regions(mask)

    editable = mask_from_regions(mask, regions)
    core_editable = np.where(editable > 0, core_mask, 0).astype(np.uint8)

    return MaskPlan(
        mask=mask,
        editable_mask=editable,
        regions=regions,
        detections=detections,
        nsfw_text=nsfw_text,
        nsfw_detections=nsfw_detections,
        core_mask=core_editable,
    )


def build_manual_plan(mask: np.ndarray) -> MaskPlan:
    """A mask edited by hand is authoritative: no grow, no area heuristics."""
    normalized = np.where(mask > 127, 255, 0).astype(np.uint8)
    regions = connected_regions(normalized)
    return MaskPlan(
        mask=normalized,
        editable_mask=normalized,
        regions=regions,
        detections=[],
        manual=True,
        core_mask=normalized,
    )


def mask_from_regions(mask: np.ndarray, regions: list[Region]) -> np.ndarray:
    """Keep only the connected components listed in ``regions``."""
    if not regions:
        return np.zeros_like(mask)
    num, labels, _, _ = cv2.connectedComponentsWithStats((mask > 0).astype(np.uint8), 8)
    keep = np.zeros(num, dtype=bool)
    for region in regions:
        if 0 <= region.label < num:
            keep[region.label] = True
    return np.where(keep[labels], mask, 0).astype(np.uint8)
