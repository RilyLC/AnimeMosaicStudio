"""New package tests plus a byte-level parity check against the legacy app."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

import numpy as np
from PIL import Image

from anime_mosaic.core.events import ProcessRecord, Reporter, RunSummary
from anime_mosaic.core.geometry import CropPlan
from anime_mosaic.core.manual_mask import ManualMaskStore
from anime_mosaic.core.pipeline import Pipeline
from anime_mosaic.core.settings import Settings

from .helpers import (
    FakeComfyClient,
    FakeDetector,
    LegacyFakeDetector,
    make_test_image,
    normalise_manifest,
    read_csv_rows,
)

LEGACY_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "AutoMosaicStudio")
)


class ListReporter(Reporter):
    def __init__(self):
        self.logs: list[tuple[str, str]] = []
        self.results: list[ProcessRecord] = []
        self.summary: RunSummary | None = None
        self.stages: list[tuple[str, str]] = []

    def log(self, level, message):
        self.logs.append((level, message))

    def stage(self, rel_path, stage, detail=""):
        self.stages.append((rel_path, stage))

    def result(self, record, dst_path):
        self.results.append(record)

    def done(self, summary):
        self.summary = summary


def _build_fixture(root: str) -> tuple[str, str, str]:
    input_dir = os.path.join(root, "input")
    make_test_image(os.path.join(input_dir, "a.png"), 640, 480)
    make_test_image(os.path.join(input_dir, "sub", "b.png"), 800, 600)
    make_test_image(os.path.join(input_dir, "sub", "c.png"), 512, 512)
    return input_dir, os.path.join(root, "out"), os.path.join(root, "models")


class PipelineBehaviourTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.input_dir, self.output_dir, self.model_dir = _build_fixture(self.tmp.name)
        os.makedirs(self.model_dir, exist_ok=True)
        self.model_path = os.path.join(self.model_dir, "mosaic_detection_seg_L.pt")
        with open(self.model_path, "wb") as handle:
            handle.write(b"fake")

    def _settings(self, **overrides) -> Settings:
        base = Settings(
            input_dir=self.input_dir,
            output_dir=self.output_dir,
            comfy_dir=self.model_dir,
            mosaic_model=self.model_path,
            size=256,
            steps=4,
            seed=1234,
            conf=0.25,
            device="cpu",
        )
        return base.merged(**overrides) if overrides else base

    def _run(self, settings: Settings):
        reporter = ListReporter()
        client = FakeComfyClient()
        detector = FakeDetector(640, (100, 80, 60, 50))
        pipeline = Pipeline(
            settings,
            reporter,
            client_factory=lambda url: client,
            detector_factory=lambda *args, **kwargs: detector,
        )
        summary = pipeline.run()
        return summary, reporter, client

    def test_batch_counts_and_outputs(self):
        summary, reporter, client = self._run(self._settings(blend="seamless"))
        self.assertEqual(summary.total, 3)
        self.assertEqual(summary.processed, 1)
        self.assertEqual(summary.copied, 2)
        self.assertEqual(summary.errors, 0)
        self.assertEqual(summary.regions, 1)
        self.assertTrue(os.path.isfile(os.path.join(self.output_dir, "a.png")))
        self.assertTrue(os.path.isfile(os.path.join(self.output_dir, "sub", "b.png")))
        self.assertTrue(os.path.isfile(os.path.join(self.output_dir, "sub", "c.png")))
        self.assertTrue(reporter.summary is summary)
        self.assertTrue(any("马赛克 1 处" in message for _, message in reporter.logs))
        self.assertEqual(len(client.prompts), 1)
        self.assertEqual(client.prompts[0]["12"]["inputs"]["seed"], 1234)
        self.assertEqual(client.prompts[0]["12"]["inputs"]["steps"], 4)

    def test_manifest_is_written(self):
        self._run(self._settings())
        path = os.path.join(self.output_dir, "_AnimeMosaicStudio_manifest.csv")
        rows = read_csv_rows(path)
        self.assertEqual(rows[0][0], "file")
        self.assertEqual(len(rows), 4)

    def test_skip_existing_reruns_nothing(self):
        first, _, _ = self._run(self._settings())
        self.assertEqual(first.processed, 1)
        second, _, client = self._run(self._settings())
        self.assertEqual(second.skipped, 3)
        self.assertEqual(second.processed, 0)
        self.assertEqual(client.prompts, [])

    def test_copy_disabled_marks_skipped(self):
        summary, _, _ = self._run(self._settings(copy_if_no_mosaic=False))
        self.assertEqual(summary.processed, 1)
        self.assertEqual(summary.copied, 0)
        self.assertEqual(summary.skipped, 2)
        self.assertFalse(os.path.isfile(os.path.join(self.output_dir, "sub", "b.png")))

    def test_stop_event_discards_current_image(self):
        import threading

        stop = threading.Event()
        stop.set()
        reporter = ListReporter()
        pipeline = Pipeline(
            self._settings(),
            reporter,
            stop,
            client_factory=lambda url: FakeComfyClient(),
            detector_factory=lambda *args, **kwargs: FakeDetector(640, (10, 10, 20, 20)),
        )
        summary = pipeline.run()
        self.assertTrue(summary.stopped)
        self.assertEqual(summary.processed, 0)

    def test_manual_mask_overrides_detector(self):
        import numpy as np

        mask = np.zeros((480, 640), np.uint8)
        mask[100:160, 120:180] = 255
        ManualMaskStore(self.output_dir).save("a.png", mask)
        reporter = ListReporter()
        client = FakeComfyClient()
        detector = FakeDetector(0, (0, 0, 0, 0))
        pipeline = Pipeline(
            self._settings(seed=77),
            reporter,
            client_factory=lambda url: client,
            detector_factory=lambda *args, **kwargs: detector,
        )
        summary = pipeline.run()
        self.assertEqual(summary.processed, 1)
        self.assertEqual(summary.regions, 1)
        self.assertEqual(len(client.prompts), 1)
        self.assertEqual(client.prompts[0]["12"]["inputs"]["seed"], 77)
        self.assertTrue(any("手动遮罩" in message for _, message in reporter.logs))

    def test_overlapping_crops_are_repainted_once(self):
        import numpy as np

        mask = np.zeros((480, 640), np.uint8)
        mask[100:140, 100:140] = 255
        mask[100:140, 180:220] = 255
        ManualMaskStore(self.output_dir).save("a.png", mask)
        reporter = ListReporter()
        client = FakeComfyClient()
        pipeline = Pipeline(
            self._settings(),
            reporter,
            client_factory=lambda url: client,
            detector_factory=lambda *args, **kwargs: FakeDetector(0, (0, 0, 0, 0)),
        )
        summary = pipeline.run()
        self.assertEqual(summary.processed, 1)
        self.assertEqual(summary.regions, 2)
        # Both regions fit in one 256px crop, so they share one generation.
        self.assertEqual(len(client.prompts), 1)
        self.assertEqual(len(client.generated), 1)
        self.assertTrue(any("区域组" in message for _, message in reporter.logs))

    def test_empty_manual_mask_copies_original(self):
        import numpy as np

        ManualMaskStore(self.output_dir).save("a.png", np.zeros((480, 640), np.uint8))
        reporter = ListReporter()
        client = FakeComfyClient()
        pipeline = Pipeline(
            self._settings(),
            reporter,
            client_factory=lambda url: client,
            detector_factory=lambda *args, **kwargs: FakeDetector(640, (100, 80, 60, 50)),
        )
        summary = pipeline.run()
        self.assertEqual(summary.processed, 0)
        self.assertEqual(summary.copied, 3)
        self.assertEqual(client.prompts, [])

    def test_run_single_regenerates_existing_output(self):
        first, _, _ = self._run(self._settings())
        self.assertEqual(first.processed, 1)
        reporter = ListReporter()
        client = FakeComfyClient()
        pipeline = Pipeline(
            self._settings(seed=99),
            reporter,
            client_factory=lambda url: client,
            detector_factory=lambda *args, **kwargs: FakeDetector(640, (100, 80, 60, 50)),
        )
        record, dst = pipeline.run_single("a.png")
        self.assertEqual(record.status, "processed")
        self.assertEqual(record.regions, 1)
        self.assertTrue(os.path.isfile(dst))
        self.assertEqual(len(client.prompts), 1)
        self.assertEqual(reporter.summary.total, 1)
        self.assertTrue(any("重新生成" in message for _, message in reporter.logs))

    def test_rgba_is_preserved(self):
        rgba_path = os.path.join(self.input_dir, "alpha.png")
        make_test_image(rgba_path, 640, 480, mode="RGBA")
        self._run(self._settings())
        with Image.open(os.path.join(self.output_dir, "alpha.png")) as result:
            self.assertEqual(result.mode, "RGBA")


class ReuseTests(unittest.TestCase):
    def test_reuse_compares_only_mask_context(self):
        with tempfile.TemporaryDirectory() as root:
            settings = Settings(
                comfy_dir=root,
                output_dir=root,
                mosaic_model=os.path.join(root, "x.pt"),
                reuse_enabled=True,
                reuse_max_diff=2.0,
                reuse_context_px=2,
            )
            pipeline = Pipeline(
                settings,
                ListReporter(),
                client_factory=lambda url: object(),
            )
            plan = CropPlan(0, 0, 64, 64, 64, 64, True)
            mask = np.zeros((64, 64), np.uint8)
            mask[20:40, 20:40] = 255
            crop = np.full((64, 64, 3), 100, np.uint8)
            generated = np.full((64, 64, 3), 200, np.uint8)
            key = pipeline._reuse_key(plan, "")

            pipeline._remember_reuse(key, crop, mask, generated, 42)
            hit = pipeline._find_reuse(key, crop.copy(), mask.copy())
            self.assertIsNotNone(hit)
            self.assertEqual(hit[2], 42)

            outside = crop.copy()
            outside[:5] = 250
            self.assertIsNotNone(pipeline._find_reuse(key, outside, mask.copy()))

            inside = crop.copy()
            inside[18:42] += 10
            self.assertIsNone(pipeline._find_reuse(key, inside, mask.copy()))


@unittest.skipUnless(os.path.isdir(os.path.join(LEGACY_ROOT, "ams")), "legacy app not present")
class LegacyParityTests(unittest.TestCase):
    """Run the original and new pipelines on identical fakes.

    Crop geometry now follows the area rules, so only the manifest, the output
    file set and the untouched copies are compared against the legacy app.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.input_dir, self.output_dir, self.model_dir = _build_fixture(self.tmp.name)
        os.makedirs(self.model_dir, exist_ok=True)

        if LEGACY_ROOT not in sys.path:
            sys.path.insert(0, LEGACY_ROOT)
        import ams.pipeline as legacy_pipeline

        self.legacy = legacy_pipeline

    def _legacy_cfg(self, output_dir: str, blend: str) -> dict:
        from ams.config import DEFAULTS

        cfg = dict(DEFAULTS)
        cfg.update(
            input_dir=self.input_dir,
            output_dir=output_dir,
            comfy_dir=self.model_dir,
            mosaic_model="fake.pt",
            size=256,
            steps=4,
            seed=1234,
            conf=0.25,
            device="cpu",
            blend=blend,
            nsfw_mode="off",
        )
        return cfg

    def _run_legacy(self, output_dir: str, blend: str, client: FakeComfyClient):
        class Harness(self.legacy.Pipeline):
            def __init__(self, cfg):
                super().__init__(cfg, ListReporter())
                self.client = client
                self.detector = LegacyFakeDetector(640, (100, 80, 60, 50))

            def _check(self):
                os.makedirs(self.cfg["output_dir"], exist_ok=True)

        return Harness(self._legacy_cfg(output_dir, blend)).run()

    def _run_new(self, output_dir: str, blend: str, client: FakeComfyClient):
        settings = Settings(
            input_dir=self.input_dir,
            output_dir=output_dir,
            comfy_dir=self.model_dir,
            mosaic_model=os.path.join(self.model_dir, "fake.pt"),
            size=256,
            steps=4,
            seed=1234,
            conf=0.25,
            device="cpu",
            blend=blend,
            nsfw_mode="off",
        )
        with open(settings.mosaic_model, "wb") as handle:
            handle.write(b"fake")

        class Harness(Pipeline):
            def check(self):
                os.makedirs(self.settings.output_dir, exist_ok=True)
                self.detector = FakeDetector(640, (100, 80, 60, 50))

        pipeline = Harness(
            settings,
            ListReporter(),
            client_factory=lambda url: client,
        )
        return pipeline.run()

    def _compare(self, blend: str):
        legacy_out = os.path.join(self.tmp.name, f"legacy_{blend}")
        new_out = os.path.join(self.tmp.name, f"new_{blend}")
        legacy_client = FakeComfyClient()
        new_client = FakeComfyClient()
        self._run_legacy(legacy_out, blend, legacy_client)
        self._run_new(new_out, blend, new_client)

        for relative in ("a.png", "sub/b.png", "sub/c.png"):
            legacy_path = os.path.join(legacy_out, relative)
            new_path = os.path.join(new_out, relative)
            self.assertTrue(os.path.isfile(legacy_path))
            self.assertTrue(os.path.isfile(new_path))
            with Image.open(legacy_path) as legacy_image, Image.open(new_path) as new_image:
                self.assertEqual(legacy_image.size, new_image.size)
                # ``a.png`` is repainted through a crop whose geometry changed on
                # purpose (area rules), so pixels are no longer comparable. The
                # two copied images must still be byte-identical.
                if relative != "a.png":
                    self.assertEqual(
                        legacy_image.convert("RGB").tobytes(),
                        new_image.convert("RGB").tobytes(),
                    )

        legacy_rows = normalise_manifest(
            read_csv_rows(os.path.join(legacy_out, "_AutoMosaicStudio_manifest.csv"))
        )
        new_rows = normalise_manifest(
            read_csv_rows(os.path.join(new_out, "_AnimeMosaicStudio_manifest.csv"))
        )
        self.assertEqual(legacy_rows, new_rows)

    def test_seamless_matches_legacy(self):
        self._compare("seamless")

    def test_laplacian_matches_legacy(self):
        self._compare("laplacian")


if __name__ == "__main__":
    unittest.main()
