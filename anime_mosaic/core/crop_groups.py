"""Group mosaic regions so each one is repainted exactly once.

Regions are detected independently, but their context windows can overlap.  If
two windows overlap, processing them separately would feed the same mosaic
pixels to the model twice (and could blend two different generations into each
other).  This module builds one crop window per connected group instead.

Every window is square: the model only accepts a standard square input, and a
square crop scaled 1:1 to a square latent never distorts the art.  A group's
window is grown around the group's *regions* (not around the sum of their
individual context windows, which is what used to overflow the frame and fall
back to a non-square crop).  A square may therefore contain a neighbouring
group's mosaic; that is harmless because each group's mask only covers its own
regions.  Only when a single region is longer than the frame's short side is the
region split into overlapping square tiles.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .geometry import CropPlan, plan_crop

Box = tuple[int, int, int, int]


@dataclass(frozen=True)
class CropGroup:
    """One model call covering one or more complete mosaic regions."""

    plan: CropPlan
    indexes: tuple[int, ...]
    boxes: tuple[Box, ...]


def _intersects(a: CropPlan, b: CropPlan) -> bool:
    return a.left < b.right and b.left < a.right and a.top < b.bottom and b.top < a.bottom


def _bbox(boxes: list[Box]) -> Box:
    left = min(box[0] for box in boxes)
    top = min(box[1] for box in boxes)
    right = max(box[0] + box[2] for box in boxes)
    bottom = max(box[1] + box[3] for box in boxes)
    return left, top, right - left, bottom - top


def _fits(boxes: list[Box], limit: int) -> bool:
    _, _, width, height = _bbox(boxes)
    return width <= limit and height <= limit


def _square_plan(
    box: Box,
    image_w: int,
    image_h: int,
    min_pct: float,
    background_ratio: float,
) -> CropPlan:
    """A square window covering ``box``, grown by the area rule, inside the frame."""
    x, y, width, height = box
    limit = min(image_w, image_h)
    area = width * height
    target = max(
        image_w * image_h * min(max(float(min_pct), 0.0), 100.0) / 100.0,
        area * (1.0 + max(float(background_ratio), 0.0)),
    )
    side = max(int(math.ceil(math.sqrt(target))), width, height)
    side = min(side, limit)
    left = min(max(0, x - (side - width) // 2), image_w - side)
    top = min(max(0, y - (side - height) // 2), image_h - side)
    return CropPlan(left, top, left + side, top + side, side, side, True)


def _slice(box: Box, limit: int) -> list[Box]:
    """Cut a region that is longer than the frame's short side into square tiles.

    Neighbouring tiles overlap so no mosaic pixel falls between two crops.
    """
    x, y, width, height = box
    if width <= limit and height <= limit:
        return [box]

    step = max(1, limit - limit // 4)
    parts: list[Box] = []
    if width >= height:
        offset = 0
        while offset < width:
            parts.append((x + offset, y, min(limit, width - offset), height))
            offset += step
    else:
        offset = 0
        while offset < height:
            parts.append((x, y + offset, width, min(limit, height - offset)))
            offset += step

    pieces: list[Box] = []
    for part in parts:
        pieces.extend(_slice(part, limit))
    return pieces


def _chunks(pieces: list[tuple[Box, int]], limit: int) -> list[list[tuple[Box, int]]]:
    """Greedily pack tiles into groups whose bounding box is still squareable."""
    chunks: list[list[tuple[Box, int]]] = []
    for piece in sorted(pieces, key=lambda item: (item[0][0], item[0][1])):
        if chunks and _fits([box for box, _ in chunks[-1]] + [piece[0]], limit):
            chunks[-1].append(piece)
        else:
            chunks.append([piece])
    return chunks


def group_crops(
    boxes: list[tuple[int, int, int, int]],
    image_w: int,
    image_h: int,
    min_pct: float = 25.0,
    *,
    background_ratio: float = 2.0,
) -> list[CropGroup]:
    """Plan crop groups for a list of region boxes.

    Groups are ordered by their first region, which keeps logs and seeds
    deterministic.  A region longer than the frame's short side appears in more
    than one group (its tiles), otherwise every index appears exactly once.
    """
    if not boxes:
        return []

    limit = min(image_w, image_h)
    plans = [
        plan_crop(box, image_w, image_h, min_pct, background_ratio=background_ratio)
        for box in boxes
    ]

    parent = list(range(len(boxes)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(a: int, b: int) -> None:
        root_a, root_b = find(a), find(b)
        if root_a != root_b:
            parent[root_b] = root_a

    # Context windows that overlap are processed together so one mosaic area is
    # never fed to the model twice by two different groups.
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            if _intersects(plans[i], plans[j]):
                union(i, j)

    grouped: dict[int, list[int]] = {}
    for index in range(len(boxes)):
        grouped.setdefault(find(index), []).append(index)

    result: list[CropGroup] = []
    for indexes in sorted(grouped.values(), key=lambda items: min(items)):
        pieces: list[tuple[Box, int]] = []
        for index in indexes:
            for piece in _slice(boxes[index], limit):
                pieces.append((piece, index))
        for chunk in _chunks(pieces, limit):
            chunk_indexes = tuple(sorted({index for _, index in chunk}))
            plan = _square_plan(
                _bbox([box for box, _ in chunk]),
                image_w,
                image_h,
                min_pct,
                background_ratio,
            )
            result.append(
                CropGroup(
                    plan=plan,
                    indexes=chunk_indexes,
                    boxes=tuple(boxes[index] for index in chunk_indexes),
                )
            )
    return result
