"""Mask growth and connected-region extraction."""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(frozen=True)
class Region:
    x: int
    y: int
    w: int
    h: int
    area: int
    label: int = -1

    @property
    def box(self) -> tuple[int, int, int, int]:
        return self.x, self.y, self.w, self.h


def grow_mask(mask: np.ndarray, px: int) -> np.ndarray:
    """Dilate a binary mask with a round kernel of radius ``px``."""
    px = int(px)
    if px <= 0:
        return mask
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (px * 2 + 1, px * 2 + 1))
    return cv2.dilate(mask, kernel)


def connected_regions(mask: np.ndarray, min_area: int = 24) -> list[Region]:
    """Split a mask into bounding boxes, largest first, ignoring specks."""
    num, labels, stats, _ = cv2.connectedComponentsWithStats((mask > 0).astype(np.uint8), 8)
    regions: list[Region] = []
    for index in range(1, num):
        x, y, w, h, area = stats[index]
        if area < min_area:
            continue
        regions.append(Region(int(x), int(y), int(w), int(h), int(area), int(index)))
    regions.sort(key=lambda region: region.area, reverse=True)
    return regions
