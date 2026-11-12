"""Persistent preflight cache tests (no Qt, no detector)."""

from __future__ import annotations

import json
import os
import tempfile
import unittest

import numpy as np

from anime_mosaic.core.manual_mask import decode_mask, encode_mask
from anime_mosaic.services.preflight import PreflightEntry, entry_mask_png
from anime_mosaic.services.preflight_cache import CACHE_DIRNAME, PreflightCache


def _mask(value: int = 255) -> np.ndarray:
    mask = np.zeros((48, 64), np.uint8)
    mask[8:24, 12:40] = value
    return mask


class PreflightCacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.output_dir = os.path.join(self.tmp.name, "out")
        self.cache = PreflightCache(self.output_dir)

    def _entry(self, rel: str, mask=None, **kwargs) -> PreflightEntry:
        mask = _mask() if mask is None else mask
        return PreflightEntry(
            path=os.path.join(self.tmp.name, "in", rel),
            rel=rel,
            width=64,
            height=48,
            regions=1,
            coverage=12.5,
            mask_png=encode_mask(mask),
            detections="mosaic:1",
            **kwargs,
        )

    def test_round_trip_keeps_entry_and_mask(self):
        entry = self._entry("sub/a.png", manual=True)
        saved = self.cache.save(
            {"sub/a.png": entry}, {"sub/a.png": (11, 22, 33)}, ("sig", 1)
        )
        self.assertTrue(saved)

        entries, fingerprints, signature = PreflightCache(self.output_dir).load()
        got = entries["sub/a.png"]
        self.assertEqual((got.width, got.height, got.regions), (64, 48, 1))
        self.assertAlmostEqual(got.coverage, 12.5, places=3)
        self.assertTrue(got.manual)
        self.assertEqual(got.detections, "mosaic:1")
        self.assertIsNone(got.mask_png)
        self.assertTrue(os.path.isfile(got.mask_file))
        self.assertEqual(
            decode_mask(entry_mask_png(got)).shape, (48, 64)
        )
        self.assertEqual(fingerprints["sub/a.png"], (11, 22, 33))
        self.assertEqual(tuple(signature), ("sig", 1))

    def test_missing_mask_file_drops_the_entry(self):
        entry = self._entry("a.png")
        self.cache.save({"a.png": entry}, {"a.png": (1, 2, 3)}, ("sig", 1))
        entries, _, _ = PreflightCache(self.output_dir).load()
        os.remove(entries["a.png"].mask_file)

        entries, fingerprints, signature = PreflightCache(self.output_dir).load()
        self.assertEqual(entries, {})
        self.assertEqual(fingerprints, {})
        self.assertEqual(tuple(signature), ("sig", 1))

    def test_corrupt_or_old_index_reads_as_empty(self):
        root = os.path.join(self.output_dir, CACHE_DIRNAME)
        os.makedirs(root)
        index = os.path.join(root, "index.json")
        with open(index, "w", encoding="utf-8") as handle:
            handle.write("{not json")
        self.assertEqual(PreflightCache(self.output_dir).load(), ({}, {}, None))

        with open(index, "w", encoding="utf-8") as handle:
            json.dump({"version": 99, "entries": {}}, handle)
        self.assertEqual(PreflightCache(self.output_dir).load(), ({}, {}, None))

    def test_write_masks_only_touches_requested_files(self):
        first = self._entry("a.png", mask=_mask(255))
        second = self._entry("b.png", mask=_mask(200))
        self.cache.save({"a.png": first, "b.png": second}, {}, None)
        entries, _, _ = self.cache.load()
        first_file = entries["a.png"].mask_file
        before = open(first_file, "rb").read()

        changed = self._entry("b.png", mask=_mask(0))
        self.cache.save({"a.png": first, "b.png": changed}, {}, None, write_masks={"b.png"})
        self.assertEqual(open(first_file, "rb").read(), before)

        entries, _, _ = PreflightCache(self.output_dir).load()
        self.assertEqual(int(decode_mask(entry_mask_png(entries["b.png"]))[8, 12]), 0)

    def test_mask_is_removed_when_entry_has_no_payload(self):
        entry = self._entry("a.png")
        self.cache.save({"a.png": entry}, {}, None)
        entries, _, _ = self.cache.load()
        mask_file = entries["a.png"].mask_file

        empty = PreflightEntry(path=entry.path, rel="a.png", width=64, height=48)
        self.cache.save({"a.png": empty}, {}, None, write_masks={"a.png"})
        self.assertFalse(os.path.isfile(mask_file))


if __name__ == "__main__":
    unittest.main()
