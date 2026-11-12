"""Tests for the shared detector cache."""

from __future__ import annotations

import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from anime_mosaic.core.settings import Settings
from anime_mosaic.services.detector_cache import DetectorCache


class FakeDetector:
    instances = 0

    def __init__(self, model_path, **kwargs):
        type(self).instances += 1
        self.model_path = model_path
        self.kwargs = kwargs
        self.loaded = False

    def load(self) -> None:
        self.loaded = True

    def detect(self, rgb):
        return None, []


class FailingDetector(FakeDetector):
    fail = True

    def load(self) -> None:
        if type(self).fail:
            raise RuntimeError("fake load failure")
        super().load()


class DetectorCacheTests(unittest.TestCase):
    def make_settings(self, root: str, **overrides) -> Settings:
        model = Path(root, "mosaic.pt")
        model.write_bytes(b"fake")
        return Settings(
            comfy_dir=root,
            mosaic_model=str(model),
            device="cpu",
            nsfw_mode="off",
            **overrides,
        )

    def test_loads_once_and_reloads_when_signature_changes(self):
        with TemporaryDirectory() as root:
            settings = self.make_settings(root)
            cache = DetectorCache(detector_factory=FakeDetector)
            FakeDetector.instances = 0

            first = cache.get(settings)
            second = cache.get(settings)
            self.assertIs(first, second)
            self.assertEqual(FakeDetector.instances, 1)
            self.assertEqual(cache.model_name, "mosaic.pt")

            changed = settings.merged(conf=settings.conf - 0.1)
            third = cache.get(changed)
            self.assertIsNot(third, first)
            self.assertEqual(FakeDetector.instances, 2)

    def test_failed_load_can_retry(self):
        with TemporaryDirectory() as root:
            settings = self.make_settings(root)
            cache = DetectorCache(detector_factory=FailingDetector)
            FailingDetector.instances = 0
            FailingDetector.fail = True

            with self.assertRaises(RuntimeError):
                cache.get(settings)
            FailingDetector.fail = False
            value = cache.get(settings)
            self.assertEqual(value[2], "mosaic.pt")
            self.assertEqual(FailingDetector.instances, 2)

    def test_concurrent_get_loads_only_once(self):
        with TemporaryDirectory() as root:
            settings = self.make_settings(root)
            cache = DetectorCache(detector_factory=FakeDetector)
            FakeDetector.instances = 0
            barrier = threading.Barrier(2)
            results = []

            def worker():
                barrier.wait()
                results.append(cache.get(settings))

            threads = [threading.Thread(target=worker) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=5)
            self.assertEqual(FakeDetector.instances, 1)
            self.assertEqual(len(results), 2)
            self.assertIs(results[0][0], results[1][0])


if __name__ == "__main__":
    unittest.main()
