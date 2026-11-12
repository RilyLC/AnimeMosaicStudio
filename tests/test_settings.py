"""Settings schema, validation and preset tests."""

from __future__ import annotations

import os
import tempfile
import unittest

from anime_mosaic.core.settings import (
    DEFAULT_NEGATIVE,
    DEFAULT_POSITIVE,
    DEFAULTS,
    FIELD_SPECS,
    GROUP_RUNTIME,
    PATH_KEYS,
    PRESET_VALUE_KEYS,
    Settings,
    load_settings,
    save_settings,
    spec_for,
)
from anime_mosaic.services.presets import (
    CUSTOM_PRESET_ID,
    PRESETS,
    active_preset_id,
    preset_by_id,
    remember_preset_values,
    resolve_preset_id,
    restore_preset_defaults,
)


class SettingsTests(unittest.TestCase):
    def test_example_config_matches_defaults(self):
        import json

        path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "config.json.example")
        )
        with open(path, "r", encoding="utf-8-sig") as handle:
            data = json.load(handle)
        self.assertEqual(set(data), set(DEFAULTS))
        for key in PATH_KEYS:
            self.assertEqual(data[key], "", key)
        self.assertEqual(Settings.from_mapping(data).to_mapping(), DEFAULTS)

    def test_defaults_match_legacy_app(self):
        legacy_root = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "AutoMosaicStudio")
        )
        if not os.path.isdir(os.path.join(legacy_root, "ams")):
            self.skipTest("legacy app not present")
        import sys

        if legacy_root not in sys.path:
            sys.path.insert(0, legacy_root)
        from ams.config import DEFAULTS as LEGACY_DEFAULTS

        # The crop settings were replaced by ``crop_min_pct`` /
        # ``crop_background_ratio``, so only compare the keys both apps share.
        obsolete = {"context", "min_context_ratio", "min_crop_px", "max_crop_px"}
        self.assertEqual(set(LEGACY_DEFAULTS) - set(DEFAULTS) - obsolete, set())
        for key, value in LEGACY_DEFAULTS.items():
            if key in obsolete:
                continue
            self.assertEqual(DEFAULTS[key], value, f"default changed: {key}")
        self.assertTrue(DEFAULTS["include_subdirs"])

    def test_prompt_defaults(self):
        self.assertEqual(Settings().positive, DEFAULT_POSITIVE)
        self.assertEqual(Settings().negative, DEFAULT_NEGATIVE)

    def test_field_specs_reference_real_fields(self):
        keys = set(DEFAULTS)
        for spec in FIELD_SPECS:
            self.assertIn(spec.key, keys)
            self.assertTrue(spec.label)

    def test_coercion_from_json_strings(self):
        settings = Settings.from_mapping(
            {"steps": "18", "cfg": "2.5", "skip_existing": "false", "size": 768.0, "unknown": 1}
        )
        self.assertEqual(settings.steps, 18)
        self.assertEqual(settings.cfg, 2.5)
        self.assertFalse(settings.skip_existing)
        self.assertEqual(settings.size, 768)

    def test_merged_rejects_unknown_keys(self):
        with self.assertRaises(KeyError):
            Settings().merged(nope=1)

    def test_validation_reports_missing_directories(self):
        problems = Settings().validate()
        fields = {problem.field for problem in problems}
        self.assertIn("input_dir", fields)
        self.assertIn("output_dir", fields)

    def test_validation_accepts_valid_setup(self):
        with tempfile.TemporaryDirectory() as root:
            input_dir = os.path.join(root, "in")
            os.makedirs(input_dir)
            settings = Settings(input_dir=input_dir, output_dir=os.path.join(root, "out"))
            self.assertEqual(settings.validate(), [])

    def test_denoise_defaults_to_full_redraw(self):
        self.assertEqual(Settings().denoise, 1.0)

    def test_validation_rejects_out_of_range_denoise(self):
        with tempfile.TemporaryDirectory() as root:
            input_dir = os.path.join(root, "in")
            os.makedirs(input_dir)
            base = dict(input_dir=input_dir, output_dir=os.path.join(root, "out"))
            for denoise in (0.1, 1.1):
                fields = {p.field for p in Settings(denoise=denoise, **base).validate()}
                self.assertIn("denoise", fields)
            fields = {p.field for p in Settings(denoise=0.2, **base).validate()}
            self.assertNotIn("denoise", fields)

    def test_output_cannot_equal_input(self):
        with tempfile.TemporaryDirectory() as root:
            settings = Settings(input_dir=root, output_dir=root)
            self.assertTrue(settings.output_conflicts)
            self.assertTrue(any(p.field == "output_dir" for p in settings.validate()))

    def test_save_and_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "config.json")
            original = Settings(input_dir="D:/images", output_dir="D:/images_out", seed=7)
            save_settings(original, path)
            loaded = load_settings(path)
            self.assertEqual(original.to_mapping(), loaded.to_mapping())

    def test_load_ignores_unknown_keys(self):
        import json

        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "config.json")
            payload = Settings().to_mapping()
            payload.update(seed=99, comfy_dir="C:/fake/comfy", retired_option=1)
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle)
            loaded = load_settings(path)
            self.assertEqual(loaded.seed, 99)
            self.assertEqual(loaded.comfy_dir, "C:/fake/comfy")

    def test_load_never_guesses_comfyui_or_models(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "config.json")
            loaded = load_settings(path)
            self.assertEqual(loaded.comfy_dir, "")
            self.assertEqual(loaded.mosaic_model, "")
            self.assertEqual(loaded.nsfw_model, "")
            self.assertFalse(os.path.exists(path))


class PresetTests(unittest.TestCase):
    def test_balanced_equals_defaults(self):
        preset = preset_by_id("balanced")
        applied = preset.apply(Settings(seed=5, input_dir="x"))
        self.assertEqual(applied.size, Settings().size)
        self.assertEqual(applied.steps, Settings().steps)
        self.assertEqual(applied.cfg, Settings().cfg)
        self.assertEqual(applied.grow, Settings().grow)
        # Presets own the whole tuning page, so the seed is reset with it too.
        self.assertEqual(applied.seed, Settings().seed)
        self.assertEqual(applied.input_dir, "x")

    def test_presets_save_the_whole_page(self):
        base = preset_by_id("fast").apply(Settings())
        edited = remember_preset_values(
            base.merged(crop_min_pct=40, crop_background_ratio=0.5, conf=0.4)
        )
        self.assertEqual(edited.preset_values["fast"]["crop_min_pct"], 40)
        self.assertEqual(edited.preset_values["fast"]["crop_background_ratio"], 0.5)
        self.assertEqual(edited.preset_values["fast"]["conf"], 0.4)

        switched = preset_by_id("balanced").apply(edited)
        self.assertEqual(switched.crop_min_pct, Settings().crop_min_pct)
        self.assertEqual(switched.conf, Settings().conf)

        back = preset_by_id("fast").apply(switched)
        self.assertEqual(back.crop_min_pct, 40)
        self.assertEqual(back.crop_background_ratio, 0.5)
        self.assertEqual(back.conf, 0.4)

    def test_active_preset_detection(self):
        self.assertEqual(active_preset_id(Settings()), "balanced")
        self.assertEqual(active_preset_id(preset_by_id("fast").apply(Settings())), "fast")
        self.assertEqual(active_preset_id(Settings(size=900)), "custom")

    def test_all_presets_apply_cleanly(self):
        for preset in PRESETS:
            settings = preset.apply(Settings())
            self.assertEqual(settings.validate().__class__, list)
            self.assertTrue(settings.positive)
            self.assertEqual(settings.preset, preset.id)

    def test_presets_define_denoise(self):
        expected = {"fast": 0.85, "balanced": 1.0, "quality": 1.0}
        for preset in PRESETS:
            self.assertEqual(preset.apply(Settings()).denoise, expected[preset.id])

    def test_explicit_custom_wins_over_matching_values(self):
        settings = Settings(preset=CUSTOM_PRESET_ID)
        self.assertEqual(resolve_preset_id(settings), CUSTOM_PRESET_ID)
        custom = preset_by_id(CUSTOM_PRESET_ID)
        applied = custom.apply(Settings())
        self.assertEqual(applied.preset, CUSTOM_PRESET_ID)
        self.assertEqual(applied.size, Settings().size)

    def test_manual_change_keeps_selected_preset(self):
        settings = remember_preset_values(Settings(preset="fast", size=1536, steps=40))
        self.assertEqual(resolve_preset_id(settings), "fast")
        self.assertEqual(settings.preset_values["fast"]["size"], 1536)
        self.assertEqual(settings.preset_values["fast"]["steps"], 40)

    def test_remembered_values_are_applied_back(self):
        base = preset_by_id("fast").apply(Settings())
        settings = remember_preset_values(base.merged(size=1536, steps=40))
        applied = preset_by_id("fast").apply(settings)
        self.assertEqual(applied.size, 1536)
        self.assertEqual(applied.steps, 40)
        self.assertEqual(applied.cfg, 2.5)

    def test_restore_preset_defaults_clears_overrides(self):
        settings = remember_preset_values(Settings(preset="fast", size=1536))
        restored = restore_preset_defaults(settings, "fast")
        self.assertEqual(restored.preset_values, {})
        self.assertEqual(restored.size, 768)
        self.assertEqual(restored.preset, "fast")

    def test_restore_inactive_preset_keeps_current_values(self):
        settings = remember_preset_values(Settings(preset="balanced", size=900))
        restored = restore_preset_defaults(settings, "fast")
        self.assertEqual(restored.preset, "balanced")
        self.assertEqual(restored.size, 900)
        self.assertEqual(restored.preset_values, settings.preset_values)

    def test_invalid_preset_is_reported(self):
        problems = Settings(preset="nope").validate()
        self.assertTrue(any(problem.field == "preset" for problem in problems))

    def test_crop_min_pct_is_validated(self):
        self.assertFalse(
            any(
                problem.field == "crop_min_pct"
                for problem in Settings(crop_min_pct=5).validate()
            )
        )
        self.assertTrue(
            any(
                problem.field == "crop_min_pct"
                for problem in Settings(crop_min_pct=4).validate()
            )
        )
        self.assertTrue(
            any(
                problem.field == "crop_min_pct"
                for problem in Settings(crop_min_pct=101).validate()
            )
        )

    def test_crop_background_ratio_is_validated(self):
        problems = Settings(crop_background_ratio=4.5).validate()
        self.assertTrue(any(p.field == "crop_background_ratio" for p in problems))
        problems = Settings(crop_background_ratio=-0.1).validate()
        self.assertTrue(any(p.field == "crop_background_ratio" for p in problems))

    def test_blend_advanced_values_are_validated(self):
        problems = Settings(
            seamless_mode="bad", laplacian_levels=0, laplacian_feather=65
        ).validate()
        self.assertTrue(any(problem.field == "seamless_mode" for problem in problems))
        self.assertTrue(any(problem.field == "laplacian_levels" for problem in problems))
        self.assertTrue(any(problem.field == "laplacian_feather" for problem in problems))

    def test_blend_extra_options_are_validated(self):
        problems = Settings(
            seamless_strength=101,
            seamless_feather=-1,
            laplacian_detail=2.5,
            laplacian_gamma=0.1,
            laplacian_lowfreq=1.5,
        ).validate()
        for field in (
            "seamless_strength",
            "seamless_feather",
            "laplacian_detail",
            "laplacian_gamma",
            "laplacian_lowfreq",
        ):
            self.assertTrue(
                any(problem.field == field for problem in problems), field
            )

    def test_reuse_values_are_validated(self):
        problems = Settings(reuse_max_diff=101, reuse_context_px=300).validate()
        self.assertTrue(any(problem.field == "reuse_max_diff" for problem in problems))
        self.assertTrue(any(problem.field == "reuse_context_px" for problem in problems))

    def test_reuse_similarity_rules_are_validated(self):
        problems = Settings(
            reuse_min_group_iou=0.2,
            reuse_min_mask_iou=0.5,
            reuse_p99_factor=0.5,
        ).validate()
        self.assertTrue(any(problem.field == "reuse_min_group_iou" for problem in problems))
        self.assertTrue(any(problem.field == "reuse_min_mask_iou" for problem in problems))
        self.assertTrue(any(problem.field == "reuse_p99_factor" for problem in problems))


class RuntimeSettingsTests(unittest.TestCase):
    def test_python_exe_defaults_to_empty_and_is_a_known_field(self):
        self.assertEqual(Settings().python_exe, "")
        spec = spec_for("python_exe")
        self.assertEqual(spec.kind, "path")
        self.assertEqual(spec.group, GROUP_RUNTIME)

    def test_python_exe_is_a_path_key_but_not_a_preset_key(self):
        self.assertIn("python_exe", PATH_KEYS)
        self.assertNotIn("python_exe", PRESET_VALUE_KEYS)

    def test_python_exe_round_trips_through_mapping(self):
        settings = Settings(python_exe=r"D:\Python\python.exe")
        self.assertEqual(
            Settings.from_mapping(settings.to_mapping()).python_exe,
            r"D:\Python\python.exe",
        )

    def test_python_exe_does_not_block_processing(self):
        problems = Settings(python_exe="").validate()
        self.assertFalse(any(problem.field == "python_exe" for problem in problems))


if __name__ == "__main__":
    unittest.main()
