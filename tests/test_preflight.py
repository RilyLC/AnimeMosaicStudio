"""Preflight scanner and scope option tests (no Qt, fake detector)."""

from __future__ import annotations

import os
import tempfile
import unittest
from dataclasses import replace

import numpy as np
from PIL import Image

from anime_mosaic.core.manual_mask import ManualMaskStore, decode_mask
from anime_mosaic.core.settings import Settings
from anime_mosaic.services.preflight import (
    PreflightScanner,
    detection_signature,
)


class _Detector:
    def __init__(self, box=(100, 80, 60, 50)):
        self.box = box

    def load(self):
        pass

    def detect(self, rgb):
        from anime_mosaic.core.detector import Detection

        height, width = rgb.shape[:2]
        mask = np.zeros((height, width), np.uint8)
        x, y, w, h = self.box
        mask[y : y + h, x : x + w] = 255
        return mask, [Detection(x, y, w, h, 0, "mosaic", 0.9)]


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = self.tmp.name
        self.input_dir = os.path.join(root, "in")
        self.output_dir = os.path.join(root, "out")
        os.makedirs(os.path.join(self.input_dir, "sub"))
        Image.new("RGB", (640, 480)).save(os.path.join(self.input_dir, "a.png"))
        Image.new("RGB", (640, 480)).save(os.path.join(self.input_dir, "sub", "b.png"))
        self.model = os.path.join(root, "mosaic.pt")
        with open(self.model, "wb") as handle:
            handle.write(b"fake")

    def _settings(self, include_subdirs: bool = True) -> Settings:
        return Settings(
            input_dir=self.input_dir,
            output_dir=self.output_dir,
            mosaic_model=self.model,
            include_subdirs=include_subdirs,
            grow=0,
            nsfw_mode="off",
        )

    def _scanner(self, settings: Settings) -> PreflightScanner:
        return PreflightScanner(
            settings, detector_factory=lambda *args, **kwargs: _Detector()
        )

    def test_scans_recursive_images_and_encodes_masks(self):
        entries = self._scanner(self._settings(True)).scan()
        self.assertEqual(len(entries), 2)
        self.assertTrue(all(entry.regions == 1 for entry in entries))
        self.assertTrue(all(entry.mask_png for entry in entries))
        mask = decode_mask(entries[0].mask_png)
        self.assertEqual(mask.shape, (480, 640))
        self.assertGreater(int((mask > 0).sum()), 0)

    def test_flat_scope_only_scans_top_level(self):
        entries = self._scanner(self._settings(False)).scan()
        self.assertEqual([entry.rel for entry in entries], ["a.png"])

    def test_signature_includes_scope(self):
        recursive = detection_signature(self._settings(True))
        flat = detection_signature(self._settings(False))
        self.assertNotEqual(recursive, flat)

    def test_grow_does_not_invalidate_detection(self):
        base = self._settings()
        grown = replace(base, grow=24)
        self.assertEqual(detection_signature(base), detection_signature(grown))

    def test_manual_mask_takes_priority_and_skips_detection(self):
        settings = self._settings(True)
        mask = np.zeros((480, 640), np.uint8)
        mask[40:120, 40:160] = 255
        ManualMaskStore(settings.output_dir).save("a.png", mask)
        loaded = []

        def factory(*args, **kwargs):
            loaded.append(1)
            return _Detector()

        entries = PreflightScanner(settings, detector_factory=factory).scan()
        manual = next(entry for entry in entries if entry.rel == "a.png")
        self.assertTrue(manual.manual)
        self.assertEqual(manual.status_label, "手动遮罩")
        self.assertEqual(manual.regions, 1)
        self.assertEqual(manual.detections, "")
        self.assertTrue(manual.mask_png)
        # Only the image without a manual mask needed the detector.
        self.assertEqual(len(loaded), 1)

    def test_manual_mask_with_wrong_size_falls_back_to_detection(self):
        settings = self._settings(True)
        ManualMaskStore(settings.output_dir).save(
            "a.png", np.zeros((32, 32), np.uint8)
        )
        entries = self._scanner(settings).scan()
        auto = next(entry for entry in entries if entry.rel == "a.png")
        self.assertFalse(auto.manual)
        self.assertEqual(auto.regions, 1)
        self.assertNotEqual(auto.detections, "")

    def test_scan_one_can_ignore_the_manual_mask(self):
        """The editor's "reset to auto" must re-run detection on demand."""
        settings = self._settings(True)
        mask = np.zeros((480, 640), np.uint8)
        mask[40:120, 40:160] = 255
        ManualMaskStore(settings.output_dir).save("a.png", mask)
        scanner = self._scanner(settings)
        manual = scanner.scan_one(os.path.join(self.input_dir, "a.png"))
        self.assertTrue(manual.manual)
        auto = scanner.scan_one(
            os.path.join(self.input_dir, "a.png"), use_manual=False
        )
        self.assertFalse(auto.manual)
        self.assertEqual(auto.regions, 1)
        self.assertNotEqual(auto.detections, "")
        decoded = decode_mask(auto.mask_png)
        self.assertEqual(decoded[80:130, 100:160].max(), 255)
        # The manual mask itself is untouched.
        self.assertTrue(ManualMaskStore(settings.output_dir).has("a.png"))

    def test_continue_only_scans_changed_files(self):
        settings = self._settings(True)
        scanner = self._scanner(settings)
        first = scanner.scan()
        self.assertEqual(len(first), 2)
        cached = {entry.rel: entry for entry in first}
        fingerprints = dict(scanner.fingerprints)
        signature = detection_signature(settings)

        again = self._scanner(settings).scan(
            mode="continue",
            cached_entries=cached,
            fingerprints=fingerprints,
            cached_signature=signature,
        )
        self.assertEqual(again, [])

        os.utime(os.path.join(self.input_dir, "a.png"), (0, 0))
        changed = self._scanner(settings).scan(
            mode="continue",
            cached_entries=cached,
            fingerprints=fingerprints,
            cached_signature=signature,
        )
        self.assertEqual([entry.rel for entry in changed], ["a.png"])


if __name__ == "__main__":
    unittest.main()
