"""Directory pairing for the output-results list."""

from __future__ import annotations

import os
import tempfile
import unittest

from PIL import Image

from anime_mosaic.services.output_index import (
    entry_from_paths,
    human_size,
    scan_outputs,
)


class OutputIndexTests(unittest.TestCase):
    def _image(self, path: str, color=(30, 40, 50)) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        Image.new("RGB", (16, 12), color).save(path)

    def test_scan_pairs_existing_outputs_and_reports_input_total(self):
        with tempfile.TemporaryDirectory() as root:
            input_dir = os.path.join(root, "in")
            output_dir = os.path.join(root, "out")
            self._image(os.path.join(input_dir, "a.png"))
            self._image(os.path.join(input_dir, "sub", "b.png"))
            self._image(os.path.join(input_dir, "sub", "c.png"))
            self._image(os.path.join(output_dir, "a.png"))
            self._image(os.path.join(output_dir, "sub", "b.png"))
            open(os.path.join(output_dir, "sub", "c.png"), "wb").close()

            scan = scan_outputs(input_dir, output_dir, include_subdirs=True)
            self.assertEqual(scan.total_input, 3)
            self.assertEqual(
                [entry.rel for entry in scan.entries],
                ["a.png", os.path.join("sub", "b.png")],
            )
            self.assertGreater(scan.entries[0].size, 0)
            self.assertEqual(
                scan.entries[1].output_path,
                os.path.join(output_dir, "sub", "b.png"),
            )

    def test_scan_without_subdirs_only_lists_top_level(self):
        with tempfile.TemporaryDirectory() as root:
            input_dir = os.path.join(root, "in")
            output_dir = os.path.join(root, "out")
            self._image(os.path.join(input_dir, "a.png"))
            self._image(os.path.join(input_dir, "sub", "b.png"))
            self._image(os.path.join(output_dir, "a.png"))
            self._image(os.path.join(output_dir, "sub", "b.png"))

            scan = scan_outputs(input_dir, output_dir, include_subdirs=False)
            self.assertEqual(scan.total_input, 1)
            self.assertEqual([entry.rel for entry in scan.entries], ["a.png"])

    def test_entry_from_paths_rejects_missing_or_empty_output(self):
        with tempfile.TemporaryDirectory() as root:
            input_dir = os.path.join(root, "in")
            os.makedirs(input_dir)
            missing = os.path.join(root, "out", "a.png")
            self.assertIsNone(entry_from_paths("a.png", input_dir, missing))
            os.makedirs(os.path.dirname(missing))
            open(missing, "wb").close()
            self.assertIsNone(entry_from_paths("a.png", input_dir, missing))

    def test_scan_reads_manifest_status(self):
        with tempfile.TemporaryDirectory() as root:
            input_dir = os.path.join(root, "in")
            output_dir = os.path.join(root, "out")
            self._image(os.path.join(input_dir, "a.png"))
            self._image(os.path.join(input_dir, "b.png"), (10, 20, 30))
            self._image(os.path.join(output_dir, "a.png"))
            self._image(os.path.join(output_dir, "b.png"), (200, 20, 30))
            with open(
                os.path.join(output_dir, "_AnimeMosaicStudio_manifest.csv"),
                "w",
                encoding="utf-8",
                newline="",
            ) as handle:
                handle.write("file,status\nb.png,processed\n")

            scan = scan_outputs(input_dir, output_dir)
            entries = {entry.rel: entry for entry in scan.entries}
            self.assertEqual(entries["a.png"].status, "copied")
            self.assertFalse(entries["a.png"].is_processed)
            self.assertEqual(entries["a.png"].status_label, "未处理（原图复制）")
            self.assertEqual(entries["b.png"].status, "processed")
            self.assertTrue(entries["b.png"].is_processed)

    def test_scan_reads_reused_marker(self):
        with tempfile.TemporaryDirectory() as root:
            input_dir = os.path.join(root, "in")
            output_dir = os.path.join(root, "out")
            self._image(os.path.join(input_dir, "a.png"))
            self._image(os.path.join(output_dir, "a.png"), (200, 20, 30))
            with open(
                os.path.join(output_dir, "_AnimeMosaicStudio_manifest.csv"),
                "w",
                encoding="utf-8",
                newline="",
            ) as handle:
                handle.write("file,status,reused\na.png,processed,1\n")

            entry = scan_outputs(input_dir, output_dir).entries[0]
            self.assertTrue(entry.reused)
            self.assertEqual(entry.status_label, "已处理（复用）")

    def test_scan_detects_an_unmanifested_byte_copy(self):
        with tempfile.TemporaryDirectory() as root:
            input_dir = os.path.join(root, "in")
            output_dir = os.path.join(root, "out")
            self._image(os.path.join(input_dir, "a.png"))
            self._image(os.path.join(output_dir, "a.png"))

            entry = scan_outputs(input_dir, output_dir).entries[0]
            self.assertEqual(entry.status, "copied")
            self.assertFalse(entry.is_processed)
            self.assertEqual(entry.status_label, "未处理（原图复制）")

    def test_human_size(self):
        self.assertEqual(human_size(12), "12 B")
        self.assertEqual(human_size(1536), "1.5 KB")


if __name__ == "__main__":
    unittest.main()
