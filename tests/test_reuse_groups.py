"""Differential-reuse candidate groups and their persistent exclusions."""

from __future__ import annotations

import os
import tempfile
import unittest

import numpy as np

from anime_mosaic.services.preflight import PreflightEntry
from anime_mosaic.services.reuse_groups import (
    build_groups,
    load_disabled,
    mask_iou,
    save_disabled,
    state_key,
)


def _mask(x: int) -> np.ndarray:
    mask = np.zeros((100, 100), dtype=np.uint8)
    mask[20:50, x : x + 20] = 255
    return mask


class ReuseGroupTests(unittest.TestCase):
    def test_similar_masks_form_one_group(self) -> None:
        masks = {"a.png": _mask(20), "b.png": _mask(21), "c.png": _mask(70)}
        entries = [
            PreflightEntry("", rel, 100, 100, regions=1, coverage=6.0)
            for rel in ("a.png", "b.png", "c.png")
        ]
        groups = build_groups(entries, lambda entry: masks[entry.rel])
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].rels, ("a.png", "b.png"))
        self.assertEqual(groups[0].representative, "a.png")
        self.assertGreaterEqual(groups[0].iou, 0.85)
        self.assertEqual(groups[0].mask.shape, (100, 100))

    def test_different_masks_do_not_group(self) -> None:
        masks = {"a.png": _mask(10), "b.png": _mask(60)}
        entries = [
            PreflightEntry("", rel, 100, 100, regions=1, coverage=4.0)
            for rel in masks
        ]
        self.assertEqual(build_groups(entries, lambda entry: masks[entry.rel]), [])

    def test_disabled_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            self.assertTrue(save_disabled(root, {"sub\\a.png", "b.png"}))
            self.assertEqual(load_disabled(root), {state_key("sub/a.png"), "b.png"})
            self.assertTrue(os.path.isfile(os.path.join(
                root, "_AnimeMosaicStudio_reuse_groups.json"
            )))

    def test_mask_iou(self) -> None:
        self.assertAlmostEqual(mask_iou(_mask(20), _mask(20)), 1.0)
        self.assertEqual(mask_iou(_mask(20), _mask(70)), 0.0)
        self.assertEqual(mask_iou(_mask(20), np.zeros((10, 10), np.uint8)), 0.0)


if __name__ == "__main__":
    unittest.main()
