"""Geometry, masking, blending, discovery and workflow graph tests."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

import numpy as np

from anime_mosaic.core.blending import blend, hard_blend, laplacian_blend, seamless_blend
from anime_mosaic.core.discovery import discover_images, find_ultralytics_model
from anime_mosaic.core.crop_groups import group_crops
from anime_mosaic.core.errors import PipelineError
from anime_mosaic.core.geometry import CropPlan, model_size, plan_crop
from anime_mosaic.core.manual_mask import ManualMaskStore, decode_mask, encode_mask
from anime_mosaic.core.masking import connected_regions, grow_mask
from anime_mosaic.core.maskplan import build_manual_plan, build_mask_plan
from anime_mosaic.core.prompting import append_nsfw_prompts
from anime_mosaic.core.settings import Settings
from anime_mosaic.core.workflow import build_workflow


class PromptTests(unittest.TestCase):
    def test_nsfw_prompts_append_only_detected_enabled_classes(self):
        settings = Settings(
            nsfw_prompt_enabled=True,
            positive="1girl, solo",
            nsfw_prompt_pussy="pussy, detailed",
            nsfw_prompt_anus="anus, detailed",
        )
        result = append_nsfw_prompts(
            settings.positive, "pussy 0.93 at 10,10; penis 0.80 at 20,20", settings
        )
        self.assertIn("1girl", result)
        self.assertIn("pussy, detailed", result)
        self.assertNotIn("anus, detailed", result)

    def test_nsfw_prompt_disabled_is_a_noop(self):
        settings = Settings(nsfw_prompt_enabled=False, nsfw_prompt_pussy="pussy")
        self.assertEqual(
            append_nsfw_prompts("1girl", "pussy 0.9", settings), "1girl"
        )


class GeometryTests(unittest.TestCase):
    def test_min_pct_gives_small_region_a_background_floor(self):
        plan = plan_crop((500, 400, 20, 20), 1920, 1080, 25.0, background_ratio=0.0)
        self.assertEqual(plan, CropPlan(150, 50, 870, 770, 720, 720, True))
        self.assertGreaterEqual(plan.width * plan.height, 1920 * 1080 * 0.25)

    def test_background_ratio_expands_by_region_area(self):
        plan = plan_crop((100, 100, 200, 100), 1000, 800, 5.0, background_ratio=2.0)
        region_area = 200 * 100
        area = plan.width * plan.height
        self.assertGreaterEqual(area, region_area * 3)
        self.assertLessEqual(area, region_area * 3 + 200)
        # The window is squared so it can be scaled to a square latent without
        # stretching; the ceil to a whole pixel is the only slack.
        self.assertTrue(plan.square)
        self.assertEqual(plan.width, plan.height)
        self.assertGreaterEqual(plan.left, 0)
        self.assertGreaterEqual(plan.top, 0)
        self.assertLessEqual(plan.right, 1000)
        self.assertLessEqual(plan.bottom, 800)

    def test_square_window_contains_the_region(self):
        plan = plan_crop((500, 400, 300, 120), 1920, 1080, 5.0, background_ratio=0.0)
        self.assertTrue(plan.square)
        self.assertLessEqual(plan.left, 500)
        self.assertLessEqual(plan.top, 400)
        self.assertGreaterEqual(plan.right, 800)
        self.assertGreaterEqual(plan.bottom, 520)

    def test_region_longer_than_short_side_falls_back(self):
        plan = plan_crop((0, 0, 900, 100), 1000, 400, 5.0, background_ratio=0.0)
        self.assertFalse(plan.square)
        self.assertEqual((plan.left, plan.top), (0, 0))
        self.assertGreaterEqual(plan.right, 900)
        self.assertGreaterEqual(plan.bottom, 100)

    def test_min_pct_wins_for_very_small_regions(self):
        plan = plan_crop((500, 400, 10, 10), 1920, 1080, 25.0, background_ratio=2.0)
        self.assertGreaterEqual(plan.width * plan.height, 1920 * 1080 * 0.25)
        self.assertAlmostEqual(plan.width, plan.height, delta=1)

    def test_window_contains_region_and_stays_in_bounds(self):
        cases = [
            ((0, 0, 20, 20), 300, 200),
            ((250, 150, 40, 30), 300, 200),
            ((0, 0, 300, 200), 300, 200),
            ((1900, 1060, 20, 20), 1920, 1080),
        ]
        for box, width, height in cases:
            plan = plan_crop(box, width, height, 5.0, background_ratio=1.0)
            x, y, w, h = box
            self.assertLessEqual(plan.left, x)
            self.assertLessEqual(plan.top, y)
            self.assertGreaterEqual(plan.right, x + w)
            self.assertGreaterEqual(plan.bottom, y + h)
            self.assertGreaterEqual(plan.left, 0)
            self.assertGreaterEqual(plan.top, 0)
            self.assertLessEqual(plan.right, width)
            self.assertLessEqual(plan.bottom, height)

    def test_region_at_corner_is_pushed_into_bounds(self):
        plan = plan_crop((0, 0, 50, 40), 300, 200, 25.0, background_ratio=0.0)
        self.assertEqual((plan.left, plan.top), (0, 0))
        self.assertGreaterEqual(plan.width * plan.height, 300 * 200 * 0.25)

    def test_full_frame_region_stays_full_frame(self):
        plan = plan_crop((0, 0, 1920, 1080), 1920, 1080, 25.0)
        self.assertEqual((plan.width, plan.height), (1920, 1080))
        self.assertFalse(plan.square)

    def test_tiny_region_uses_the_min_pct_floor(self):
        plan = plan_crop((0, 0, 15, 40), 100, 100, 25.0)
        # 25% of 100x100 = 2500 px², so the window is a 50x50 square.
        self.assertEqual((plan.width, plan.height), (50, 50))
        self.assertTrue(plan.square)

    def test_degenerate_region_raises(self):
        with self.assertRaises(PipelineError):
            plan_crop((0, 0, 0, 40), 100, 100)

    def test_model_size_square(self):
        plan = CropPlan(0, 0, 200, 200, 200, 200, True)
        self.assertEqual(model_size(plan, 1024), (1024, 1024))

    def test_model_size_square_snaps_to_64(self):
        plan = CropPlan(0, 0, 300, 300, 300, 300, True)
        self.assertEqual(model_size(plan, 1000), (1024, 1024))
        self.assertEqual(model_size(plan, 700), (704, 704))
        self.assertEqual(model_size(plan, 64, min_side=128), (128, 128))


class CropGroupTests(unittest.TestCase):
    def test_overlapping_regions_share_one_crop(self):
        boxes = [(10, 10, 20, 20), (40, 10, 20, 20), (300, 300, 20, 20)]
        groups = group_crops(boxes, 500, 400, 5.0, background_ratio=0.0)
        self.assertEqual(len(groups), 2)
        self.assertEqual(groups[0].indexes, (0, 1))
        self.assertEqual(groups[1].indexes, (2,))

    def test_each_region_is_covered_exactly_once(self):
        boxes = [(10, 10, 20, 20), (40, 10, 20, 20), (120, 80, 30, 24)]
        groups = group_crops(boxes, 800, 600, 5.0, background_ratio=0.0)
        covered = [index for group in groups for index in group.indexes]
        self.assertEqual(sorted(covered), list(range(len(boxes))))
        self.assertEqual(len(covered), len(set(covered)))

    def test_group_crop_contains_every_region_box(self):
        boxes = [(10, 10, 20, 20), (40, 10, 20, 20), (120, 80, 30, 24)]
        groups = group_crops(boxes, 800, 600, 5.0, background_ratio=0.0)
        for group in groups:
            for x, y, w, h in group.boxes:
                self.assertLessEqual(group.plan.left, x)
                self.assertLessEqual(group.plan.top, y)
                self.assertGreaterEqual(group.plan.right, x + w)
                self.assertGreaterEqual(group.plan.bottom, y + h)

    def test_group_window_keeps_min_area_rule(self):
        groups = group_crops([(10, 10, 20, 20)], 800, 600, 5.0, background_ratio=1.0)
        plan = groups[0].plan
        self.assertGreaterEqual(plan.width * plan.height, 800 * 600 * 0.05)

    def test_empty_input(self):
        self.assertEqual(group_crops([], 100, 100, 5.0), [])

    def test_group_window_is_squared_for_latent(self):
        boxes = [(10, 10, 20, 20), (120, 10, 20, 20)]
        groups = group_crops(boxes, 800, 400, 5.0, background_ratio=0.0)
        self.assertEqual(len(groups), 1)
        plan = groups[0].plan
        self.assertTrue(plan.square)
        self.assertEqual(plan.width, plan.height)
        for x, y, w, h in boxes:
            self.assertLessEqual(plan.left, x)
            self.assertLessEqual(plan.top, y)
            self.assertGreaterEqual(plan.right, x + w)
            self.assertGreaterEqual(plan.bottom, y + h)
        self.assertLessEqual(plan.right, 800)
        self.assertLessEqual(plan.bottom, 400)

    def test_group_cannot_square_when_region_exceeds_short_side(self):
        groups = group_crops([(0, 0, 900, 100)], 1000, 400, 5.0, background_ratio=0.0)
        plan = groups[0].plan
        self.assertFalse(plan.square)
        self.assertGreaterEqual(plan.right, 900)
        self.assertGreaterEqual(plan.bottom, 100)

    def test_model_size_snaps_to_32(self):
        plan = CropPlan(0, 0, 300, 200, 300, 200, False)
        width, height = model_size(plan, 1024, min_side=128)
        self.assertEqual(width % 32, 0)
        self.assertEqual(height % 32, 0)
        self.assertEqual(width, 1024)
        self.assertEqual(height, 672)


class MaskingTests(unittest.TestCase):
    def test_connected_regions_sorted_by_area(self):
        mask = np.zeros((100, 100), np.uint8)
        mask[10:30, 10:30] = 255
        mask[60:65, 60:65] = 255
        regions = connected_regions(mask)
        self.assertEqual(len(regions), 2)
        self.assertGreater(regions[0].area, regions[1].area)
        self.assertEqual(regions[0].box, (10, 10, 20, 20))

    def test_specks_are_ignored(self):
        mask = np.zeros((100, 100), np.uint8)
        mask[10, 10] = 255
        self.assertEqual(connected_regions(mask, min_area=24), [])

    def test_grow_mask_expands(self):
        mask = np.zeros((50, 50), np.uint8)
        mask[25, 25] = 255
        grown = grow_mask(mask, 3)
        self.assertGreater(int((grown > 0).sum()), 1)


class BlendingTests(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(7)
        self.base = rng.integers(0, 255, (64, 64, 3), dtype=np.uint8)
        self.generated = rng.integers(0, 255, (64, 64, 3), dtype=np.uint8)
        self.mask = np.zeros((64, 64), np.uint8)
        self.mask[20:40, 20:40] = 255

    def test_hard_blend_only_changes_masked_pixels(self):
        result = hard_blend(self.base, self.generated, (self.mask > 127).astype(np.float32))
        np.testing.assert_array_equal(result[self.mask == 0], self.base[self.mask == 0])
        np.testing.assert_array_equal(result[self.mask > 0], self.generated[self.mask > 0])

    def test_seamless_blend_returns_none_when_mask_touches_border(self):
        border = np.zeros((64, 64), np.uint8)
        border[0:10, 10:30] = 255
        self.assertIsNone(seamless_blend(self.base, self.generated, border))

    def test_blend_falls_back_to_hard_for_border_mask(self):
        border = np.zeros((64, 64), np.uint8)
        border[0:10, 10:30] = 255
        result = blend("seamless", self.base, self.generated, border)
        expected = hard_blend(self.base, self.generated, (border > 127).astype(np.float32))
        np.testing.assert_array_equal(result, expected)

    def test_laplacian_keeps_unmasked_detail(self):
        result = laplacian_blend(self.base, self.generated, self.mask.astype(np.float32) / 255.0)
        difference = np.abs(result.astype(np.int16) - self.base.astype(np.int16))
        self.assertLess(int(difference[self.mask == 0].max()), 40)
        self.assertEqual(result.shape, self.base.shape)

    def test_unknown_blend_uses_hard(self):
        result = blend("nope", self.base, self.generated, self.mask)
        expected = hard_blend(self.base, self.generated, (self.mask > 127).astype(np.float32))
        np.testing.assert_array_equal(result, expected)

    def test_advanced_blend_options_are_accepted(self):
        laplacian = blend(
            "laplacian",
            self.base,
            self.generated,
            self.mask,
            laplacian_levels=2,
            laplacian_feather=6,
        )
        self.assertEqual(laplacian.shape, self.base.shape)
        seamless = blend(
            "seamless",
            self.base,
            self.generated,
            self.mask,
            seamless_mode="mixed",
        )
        self.assertEqual(seamless.shape, self.base.shape)

    def test_seamless_strength_zero_matches_hard_paste(self):
        result = blend(
            "seamless", self.base, self.generated, self.mask, seamless_strength=0
        )
        expected = hard_blend(self.base, self.generated, (self.mask > 127).astype(np.float32))
        np.testing.assert_array_equal(result, expected)

    def test_seamless_strength_only_changes_the_masked_area(self):
        full = blend("seamless", self.base, self.generated, self.mask)
        half = blend(
            "seamless", self.base, self.generated, self.mask, seamless_strength=50
        )
        np.testing.assert_array_equal(half[self.mask == 0], full[self.mask == 0])
        self.assertFalse(np.array_equal(half, full))

    def test_seamless_feather_leaves_far_pixels_untouched(self):
        result = blend(
            "seamless", self.base, self.generated, self.mask, seamless_feather=8
        )
        np.testing.assert_array_equal(result[:8, :8], self.base[:8, :8])

    def test_laplacian_detail_raises_the_high_frequency_inside_the_mask(self):
        soft = blend(
            "laplacian", self.base, self.generated, self.mask, laplacian_detail=0.0
        )
        sharp = blend(
            "laplacian", self.base, self.generated, self.mask, laplacian_detail=2.0
        )
        inside = self.mask > 127
        self.assertGreater(
            float(np.std(sharp[inside].astype(np.float32))),
            float(np.std(soft[inside].astype(np.float32))),
        )

    def test_laplacian_lowfreq_protects_the_original_colour(self):
        base = np.full((32, 32, 3), 40, np.uint8)
        generated = np.full((32, 32, 3), 200, np.uint8)
        mask = np.zeros((32, 32), np.uint8)
        mask[8:24, 8:24] = 255
        inside = mask > 127
        generated_read = blend("laplacian", base, generated, mask, laplacian_lowfreq=1.0)
        protected = blend("laplacian", base, generated, mask, laplacian_lowfreq=0.0)
        self.assertGreater(
            float(generated_read[inside].astype(np.float32).mean()),
            float(protected[inside].astype(np.float32).mean()),
        )
        self.assertLess(
            abs(float(protected[inside].astype(np.float32).mean()) - 40.0), 40.0
        )


class DiscoveryTests(unittest.TestCase):
    def test_discovery_skips_output_and_specks(self):
        from PIL import Image

        with tempfile.TemporaryDirectory() as root:
            input_dir = os.path.join(root, "in")
            output_dir = os.path.join(input_dir, "out")
            os.makedirs(os.path.join(input_dir, "sub"))
            os.makedirs(output_dir)
            Image.new("RGB", (4, 4)).save(os.path.join(input_dir, "a.PNG"))
            Image.new("RGB", (4, 4)).save(os.path.join(input_dir, "sub", "b.jpg"))
            Image.new("RGB", (4, 4)).save(os.path.join(output_dir, "c.png"))
            open(os.path.join(input_dir, "empty.png"), "wb").close()
            open(os.path.join(input_dir, "note.txt"), "w").close()

            files = discover_images(input_dir, output_dir)
            names = [os.path.basename(path) for path in files]
            self.assertEqual(names, ["a.PNG", "b.jpg"])

    def test_discovery_flat_mode_skips_subdirectories(self):
        from PIL import Image

        with tempfile.TemporaryDirectory() as root:
            input_dir = os.path.join(root, "in")
            os.makedirs(os.path.join(input_dir, "sub"))
            Image.new("RGB", (4, 4)).save(os.path.join(input_dir, "a.png"))
            Image.new("RGB", (4, 4)).save(os.path.join(input_dir, "sub", "b.png"))
            recursive = discover_images(input_dir, "", True)
            flat = discover_images(input_dir, "", False)
            self.assertEqual([os.path.basename(path) for path in recursive], ["a.png", "b.png"])
            self.assertEqual([os.path.basename(path) for path in flat], ["a.png"])

    def test_find_ultralytics_prefers_large_model(self):
        with tempfile.TemporaryDirectory() as root:
            models = os.path.join(root, "models", "ultralytics", "segm")
            os.makedirs(models)
            small = os.path.join(models, "mosaic_seg_s.pt")
            large = os.path.join(models, "mosaic_seg_L.pt")
            with open(small, "wb") as handle:
                handle.write(b"x")
            with open(large, "wb") as handle:
                handle.write(b"xx")
            self.assertEqual(find_ultralytics_model(root, "mosaic"), large)


class MaskPlanTests(unittest.TestCase):
    class _Detector:
        def __init__(self, mask):
            self._mask = mask

        def load(self):
            pass

        def detect(self, rgb):
            return self._mask.copy(), []

    def test_editable_mask_keeps_all_regions(self):
        mask = np.zeros((100, 100), np.uint8)
        mask[0:40, 0:40] = 255
        mask[70:80, 70:80] = 255
        settings = Settings(grow=0, nsfw_mode="off")
        plan = build_mask_plan(
            np.zeros((100, 100, 3), np.uint8), self._Detector(mask), None, settings
        )
        self.assertEqual(len(plan.regions), 2)
        self.assertGreater(int((plan.mask > 0).sum()), 1600)
        self.assertEqual(int((plan.editable_mask > 0).sum()), 1700)

    def test_manual_plan_is_authoritative(self):
        mask = np.zeros((100, 100), np.uint8)
        mask[0:50, 0:50] = 255
        plan = build_manual_plan(mask)
        self.assertTrue(plan.manual)
        self.assertEqual(len(plan.regions), 1)
        self.assertEqual(int((plan.editable_mask > 0).sum()), 2500)

    def test_manual_mask_store_roundtrip(self):
        with tempfile.TemporaryDirectory() as root:
            store = ManualMaskStore(root)
            mask = np.zeros((30, 40), np.uint8)
            mask[5:15, 6:20] = 255
            path = store.save("sub/a.png", mask)
            self.assertTrue(os.path.isfile(path))
            self.assertTrue(store.has("sub/a.png"))
            loaded = store.load("sub/a.png")
            np.testing.assert_array_equal(loaded, mask)
            store.delete("sub/a.png")
            self.assertFalse(store.has("sub/a.png"))

    def test_mask_codec_roundtrip(self):
        mask = np.zeros((17, 23), np.uint8)
        mask[2:8, 3:9] = 255
        np.testing.assert_array_equal(decode_mask(encode_mask(mask)), mask)


class WorkflowTests(unittest.TestCase):
    def test_graph_matches_legacy_builder(self):
        legacy_root = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "AutoMosaicStudio")
        )
        if not os.path.isdir(os.path.join(legacy_root, "ams")):
            self.skipTest("legacy app not present")
        if legacy_root not in sys.path:
            sys.path.insert(0, legacy_root)
        from ams.config import DEFAULTS
        from ams.pipeline import build_auto_mosaic_workflow

        settings = Settings()
        old_graph = build_auto_mosaic_workflow(
            DEFAULTS, "in.png", "mask.png", 42, "ams_tmp/run/ams"
        )
        new_graph = build_workflow(settings, "in.png", "mask.png", 42, "ams_tmp/run/ams")
        self.assertEqual(old_graph, new_graph)

    def test_graph_is_self_consistent(self):
        graph = build_workflow(Settings(), "i.png", "m.png", 1, "p/ams")
        self.assertEqual(len(graph), 14)
        for node in graph.values():
            for value in node["inputs"].values():
                if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str):
                    self.assertIn(value[0], graph)

    def test_graph_uses_settings_denoise(self):
        graph = build_workflow(Settings(denoise=0.65), "i.png", "m.png", 1, "p/ams")
        self.assertEqual(graph["12"]["inputs"]["denoise"], 0.65)
        # Defaults must stay at a full redraw so the legacy graph is unchanged.
        self.assertEqual(
            build_workflow(Settings(), "i.png", "m.png", 1, "p/ams")["12"]["inputs"]["denoise"],
            1.0,
        )


if __name__ == "__main__":
    unittest.main()
