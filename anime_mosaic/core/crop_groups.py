"""Group mosaic regions so each one is repainted exactly once.

Regions are detected independently, but their context windows can overlap.  If
two windows overlap, processing them separately would feed the same mosaic
pixels to the model twice (and could blend two different generations into each
other).  This module builds a crop window per connected group instead:

* every region belongs to exactly one group;
* every group window fully contains every region in that group;
* windows are expanded with the area rules from :func:`plan_crop`;
* a merged window is squared around its bounding box so the model still gets a
  square latent, and only grows when another region's bounding box falls inside
  it, so a group remains as tight as possible while still avoiding duplicate
  work.
"""

from __future__ import annotations

from dataclasses import dataclass

from .geometry import CropPlan, plan_crop


@dataclass(frozen=True)
class CropGroup:
    """One model call covering one or more complete mosaic regions."""

    plan: CropPlan
    indexes: tuple[int, ...]
    boxes: tuple[tuple[int, int, int, int], ...]


def _intersects(a: CropPlan, b: CropPlan) -> bool:
    return a.left < b.right and b.left < a.right and a.top < b.bottom and b.top < a.bottom


def _box_intersects(plan: CropPlan, box: tuple[int, int, int, int]) -> bool:
    x, y, w, h = box
    return plan.left < x + w and x < plan.right and plan.top < y + h and y < plan.bottom


def _union_plan(plans: list[CropPlan], image_w: int, image_h: int) -> CropPlan:
    left = min(plan.left for plan in plans)
    top = min(plan.top for plan in plans)
    right = max(plan.right for plan in plans)
    bottom = max(plan.bottom for plan in plans)
    width, height = right - left, bottom - top
    if width != height:
        # A group must still feed a square image to ComfyUI: expand the
        # bounding box to a square centred on it, then shift it into the frame.
        side = max(width, height)
        if side <= min(image_w, image_h):
            left = min(max(0, left - (side - width) // 2), image_w - side)
            top = min(max(0, top - (side - height) // 2), image_h - side)
            right, bottom = left + side, top + side
            width, height = side, side
    return CropPlan(left, top, right, bottom, width, height, width == height)


def group_crops(
    boxes: list[tuple[int, int, int, int]],
    image_w: int,
    image_h: int,
    min_pct: float = 25.0,
    *,
    background_ratio: float = 2.0,
) -> list[CropGroup]:
    """Plan disjoint-by-region crop groups for a list of region boxes.

    The returned groups cover every input index exactly once.  Groups are
    ordered by their first region, which keeps logs and seeds deterministic.
    """
    if not boxes:
        return []

    plans = [
        plan_crop(
            box,
            image_w,
            image_h,
            min_pct,
            background_ratio=background_ratio,
        )
        for box in boxes
    ]

    parent = list(range(len(boxes)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(a: int, b: int) -> bool:
        root_a, root_b = find(a), find(b)
        if root_a == root_b:
            return False
        parent[root_b] = root_a
        return True

    # Windows that overlap cannot be processed independently: their masks may
    # contain pixels from the neighbouring region.
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            if _intersects(plans[i], plans[j]):
                union(i, j)

    # The bounding rectangle of a group can cover a region whose own window
    # happened to sit in a corner of that rectangle.  Include it as well, then
    # recompute until stable so every masked pixel is covered by exactly one
    # group.
    changed = True
    while changed:
        changed = False
        for i in range(len(boxes)):
            root = find(i)
            members = [index for index in range(len(boxes)) if find(index) == root]
            group_plan = _union_plan(
                [plans[index] for index in members], image_w, image_h
            )
            for j in range(len(boxes)):
                if find(j) == root:
                    continue
                if _box_intersects(group_plan, boxes[j]):
                    union(root, j)
                    changed = True

    grouped: dict[int, list[int]] = {}
    for index in range(len(boxes)):
        grouped.setdefault(find(index), []).append(index)

    result: list[CropGroup] = []
    for indexes in sorted(grouped.values(), key=lambda items: min(items)):
        group_plan = _union_plan(
            [plans[index] for index in indexes], image_w, image_h
        )
        result.append(
            CropGroup(
                plan=group_plan,
                indexes=tuple(indexes),
                boxes=tuple(boxes[index] for index in indexes),
            )
        )
    return result
