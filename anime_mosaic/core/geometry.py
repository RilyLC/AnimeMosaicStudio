"""Crop geometry for region inpainting, isolated so it can be tested purely."""

from __future__ import annotations

import math
from dataclasses import dataclass

from .errors import PipelineError

# ComfyUI works on 1/8-scale latents and the SDXL/Cosmos family additionally
# expects the pixel size to be a multiple of 64, so square model inputs are kept
# on that grid to get an exact square latent.
LATENT_MULTIPLE = 64


@dataclass(frozen=True)
class CropPlan:
    """A crop window around a mosaic region plus the size it maps back to."""

    left: int
    top: int
    right: int
    bottom: int
    out_w: int
    out_h: int
    square: bool

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top


def plan_crop(
    region: tuple[int, int, int, int],
    image_w: int,
    image_h: int,
    min_pct: float = 25.0,
    *,
    background_ratio: float = 2.0,
) -> CropPlan:
    """Plan a **square** crop window around ``region`` from two area rules.

    The window area is the larger of:

    * ``min_pct`` percent of the whole image, a floor for small mosaics;
    * the region area times ``1 + background_ratio``, so a larger mosaic keeps
      proportionally more surrounding context.

    The window is forced to a square whose side is
    ``max(sqrt(target_area), region long side)``, capped at the image's short
    side, so the crop keeps its aspect ratio when it is scaled to a square
    latent; a non-square crop would either be stretched or leave the latent
    rectangular.  The square is centred on the region and shifted back inside
    the image.

    When the region's long side exceeds the image's short side (e.g. a 3000x200
    mosaic in a 3840x2160 frame) no square inside the frame can contain the
    region, so the older uniform-ring window is used instead and
    ``CropPlan.square`` is False; the pipeline logs a warning for those.

    Tiny regions are fine: ``min_pct`` is the floor that keeps a 10x10 detection
    from producing a 10x10 crop.  Only a degenerate region (zero width or
    height) is rejected.
    """
    x, y, w, h = region
    if w < 1 or h < 1:
        raise PipelineError("区域无效")

    min_pct = min(max(float(min_pct), 0.0), 100.0)
    ratio = max(float(background_ratio), 0.0)

    region_area = w * h
    frame_area = image_w * image_h
    target = max(frame_area * min_pct / 100.0, region_area * (1.0 + ratio))
    target = min(max(target, float(region_area)), float(frame_area))

    limit = min(image_w, image_h)
    if max(w, h) <= limit:
        # The square can be grown up to the image's short side; when the area
        # rule asks for more than that, the short side is the closest square.
        side = max(int(math.ceil(math.sqrt(target))), w, h)
        side = min(side, limit)
        left = min(max(0, x - (side - w) // 2), image_w - side)
        top = min(max(0, y - (side - h) // 2), image_h - side)
        return CropPlan(left, top, left + side, top + side, side, side, True)

    # Fallback: no square inside the frame can contain the region, so keep the
    # aspect-preserving uniform-ring window and never cut the mosaic.
    # (w + 2d)(h + 2d) = region_area + extra  =>
    # d = (sqrt((w + h)^2 + 4*extra) - (w + h)) / 4
    extra = target - region_area
    half = (math.sqrt((w + h) ** 2 + 4.0 * extra) - (w + h)) / 4.0
    grow = max(0, int(math.ceil(half)))
    cw = min(image_w, w + 2 * grow)
    ch = min(image_h, h + 2 * grow)

    # A window hugging one image edge may hit a cap before reaching the target
    # area; grow the other axis until the rule holds (target <= frame area).
    if cw * ch < target:
        ch = min(image_h, max(ch, math.ceil(target / cw)))
    if cw * ch < target:
        cw = min(image_w, max(cw, math.ceil(target / ch)))

    left = min(max(0, x - (cw - w) // 2), image_w - cw)
    top = min(max(0, y - (ch - h) // 2), image_h - ch)
    return CropPlan(left, top, left + cw, top + ch, cw, ch, cw == ch)


def model_size(plan: CropPlan, size: int, min_side: int = 128) -> tuple[int, int]:
    """Model input size: square plans get a square latent on the 64 grid."""
    if plan.square:
        side = max(int(min_side), int(size))
        side = max(LATENT_MULTIPLE, int(round(side / LATENT_MULTIPLE)) * LATENT_MULTIPLE)
        return side, side
    # Rare non-square fallback: keep the crop aspect on the 32 grid.
    scale = size / float(max(plan.out_w, plan.out_h))
    width = max(int(min_side), int(round(plan.out_w * scale / 32.0)) * 32)
    height = max(int(min_side), int(round(plan.out_h * scale / 32.0)) * 32)
    return width, height
