"""Architecture guard: the processing layers must never import Qt."""

from __future__ import annotations

import glob
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKAGE = os.path.join(ROOT, "anime_mosaic")


class LayeringTests(unittest.TestCase):
    def test_core_and_services_are_ui_free(self):
        files = glob.glob(os.path.join(PACKAGE, "core", "*.py"))
        files += glob.glob(os.path.join(PACKAGE, "services", "*.py"))
        files += [os.path.join(PACKAGE, "cli.py"), os.path.join(PACKAGE, "logging_setup.py")]
        self.assertTrue(files)
        for path in files:
            with open(path, "r", encoding="utf-8") as handle:
                source = handle.read()
            for forbidden in ("PySide6", "PyQt5", "PyQt6", "import tkinter"):
                self.assertNotIn(
                    forbidden,
                    source,
                    f"{os.path.basename(path)} must stay independent of the desktop UI",
                )

    def test_ui_only_imports_core_public_modules(self):
        for path in glob.glob(os.path.join(PACKAGE, "ui", "**", "*.py"), recursive=True):
            with open(path, "r", encoding="utf-8") as handle:
                source = handle.read()
            self.assertNotIn("import ams", source)


if __name__ == "__main__":
    unittest.main()
