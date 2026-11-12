"""Regenerate ``assets/icon.png`` and ``assets/icon.ico`` from the app mark.

Run with the interpreter that runs the app (PySide6 must be importable):

    python tools/make_icon.py

The ICO is what the launcher exe embeds (``build_launcher.bat`` passes it to
PyInstaller); the PNG is used by the README and by anyone who wants the mark
for a store page.  Both are derived from ``anime_mosaic/ui/branding.py`` so the
files can never drift from the in-app icon.
"""

from __future__ import annotations

import io
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402
from PySide6.QtCore import QBuffer, QIODevice  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402

from anime_mosaic.ui.branding import ICON_SIZES, logo_pixmap  # noqa: E402
from anime_mosaic.ui.theme import LIGHT  # noqa: E402


def _pil_image(palette, size: int) -> Image.Image:
    pixmap = logo_pixmap(palette, size)
    buffer = QBuffer()
    buffer.open(QIODevice.WriteOnly)
    pixmap.save(buffer, "PNG")
    return Image.open(io.BytesIO(bytes(buffer.data()))).convert("RGBA")


def main() -> int:
    app = QGuiApplication.instance() or QGuiApplication([])  # noqa: F841
    palette = LIGHT
    out = ROOT / "assets"
    out.mkdir(exist_ok=True)

    largest = max(ICON_SIZES)
    frames = {size: _pil_image(palette, size) for size in ICON_SIZES}
    frames[largest].save(out / "icon.png")

    sizes = [(size, size) for size in ICON_SIZES]
    # Prefer pre-rendered frames (Pillow >= 9.1) so the tailored 16/24 px
    # variants survive, and BMP entries because PyInstaller reads those
    # reliably when it embeds the icon into the exe resources.
    attempts = (
        {"append_images": [frames[size] for size in ICON_SIZES[:-1]], "bitmap_format": "bmp"},
        {"append_images": [frames[size] for size in ICON_SIZES[:-1]]},
        {},
    )
    for extra in attempts:
        try:
            frames[largest].save(out / "icon.ico", format="ICO", sizes=sizes, **extra)
            break
        except (TypeError, ValueError):
            continue

    with Image.open(out / "icon.ico") as check:
        print(f"icon.png {frames[largest].size[0]}px")
        print(f"icon.ico {getattr(check, 'n_frames', 1)} frame(s): {sizes}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
