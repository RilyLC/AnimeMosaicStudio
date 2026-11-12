"""Portable path keys shared by output-side state files."""

from __future__ import annotations

import unittest

from anime_mosaic.services.output_state import state_key


class StateKeyTests(unittest.TestCase):
    def test_state_key_normalises_windows_separators(self):
        self.assertEqual(state_key(r"sub\a.png"), "sub/a.png")
        self.assertEqual(state_key("sub/a.png"), "sub/a.png")
        self.assertEqual(state_key(""), "")


if __name__ == "__main__":
    unittest.main()
