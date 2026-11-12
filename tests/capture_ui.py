"""Developer tool: render every page to PNG for visual review.

Run from the project root::

    python tests/capture_ui.py [output_dir]
"""

from __future__ import annotations

import os
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from anime_mosaic.core.events import ProcessRecord  # noqa: E402
from anime_mosaic.core.settings import load_settings  # noqa: E402
from anime_mosaic.ui.main_window import MainWindow  # noqa: E402
from anime_mosaic.ui.state import SettingsStore  # noqa: E402
from anime_mosaic.ui.theme import ThemeManager, app_font_family  # noqa: E402


def _sample_image(path: str) -> None:
    import numpy as np
    from PIL import Image, ImageDraw

    width, height = 900, 640
    x = np.linspace(0, 1, width)
    y = np.linspace(0, 1, height)
    grid = np.outer(y, np.ones(width)) * 0.5 + np.outer(np.ones(height), x) * 0.5
    rgb = np.stack(
        [120 + 90 * grid, 70 + 120 * (1 - grid), 150 + 60 * grid], axis=-1
    ).astype("uint8")
    image = Image.fromarray(rgb)
    draw = ImageDraw.Draw(image)
    draw.ellipse((260, 150, 640, 520), fill=(250, 214, 190))
    draw.ellipse((330, 250, 380, 290), fill=(40, 30, 30))
    draw.ellipse((520, 250, 570, 290), fill=(40, 30, 30))
    draw.arc((400, 320, 500, 400), 20, 160, fill=(120, 60, 60), width=8)
    image.save(path)


def main() -> int:
    out_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "_ui_shots")
    os.makedirs(out_dir, exist_ok=True)
    sample = os.path.join(out_dir, "sample.png")
    _sample_image(sample)

    app = QApplication([])
    app.setStyle("Fusion")
    app.setFont(QFont(app_font_family(), 10))
    theme = ThemeManager(app, "dark")
    theme.apply()
    store = SettingsStore(load_settings(), autosave=False)
    # Demo values for the marketing screenshots; nothing is persisted.
    store.replace(
        store.settings.merged(
            size=1024,
            steps=25,
            cfg=3.0,
            seed=-1,
            grow=8,
            crop_min_pct=25,
            crop_background_ratio=2.0,
            conf=0.25,
            lora_strength=0.33,
            nsfw_mode="off",
        )
    )
    window = MainWindow(store, theme, auto_probe=False, persist=False)
    window.resize(1360, 880)
    window.show()
    window.logs.add("success", "ComfyUI 已连接（版本 0.44.0）")
    app.processEvents()

    names = ("workspace", "tuning", "prompts", "settings", "logs", "about")
    for index, name in enumerate(names):
        window.go_to(index, save=False)
        app.processEvents()
        app.processEvents()
        window.grab().save(os.path.join(out_dir, f"dark_{index}_{name}.png"))

    # Populated workspace
    window.go_to(0, save=False)
    workspace = window.workspace
    workspace._stage_badge.set_state("运行中", "accent")
    workspace._current.setText("ComfyUI 重绘 · 2/3 · sample.png")
    for record, seconds in (
        (ProcessRecord("a.png", "processed", regions=2, seconds=12.4, seed="1234,1235"), 12.4),
        (ProcessRecord("sub/b.png", "copied", seconds=0.1, message="未检测到马赛克"), 0.1),
        (ProcessRecord("sub/c.png", "skipped", message="输出已存在"), 0.0),
        (ProcessRecord("sub/d.png", "error", seconds=4.2, message="显存不足，已跳过"), 4.2),
    ):
        workspace.handle_result(record, sample)
    workspace._stage_badge.set_state("已完成", "ok")
    workspace._current.setText("完成 4 张 · 用时 18s")
    window.logs.add("success", "完成：a.png（12.4s）")
    window.logs.add("info", "    区域 1/2 168x120 @(412,286) · 1024x1024 · 6.1s")
    window.logs.add("warn", "sub/d.png：显存不足，已跳过")
    window.logs.add("info", "发现 4 张图片，输出目录：D:/Pictures/anime_out")
    window._stage_label.setText("已完成")
    window._file_label.setText("完成 4 张 · 用时 18s")
    window._progress.setRange(0, 4)
    window._progress.setValue(4)
    window._count_label.setText("4 / 4")
    window._eta_label.setText("总用时 18s")
    workspace.input_picker.set_status("4 张", "ok")
    workspace.input_picker.set_status("4 张", "ok")
    app.processEvents()
    window.grab().save(os.path.join(out_dir, "dark_workspace_populated.png"))

    window.go_to(4, save=False)
    app.processEvents()
    app.processEvents()
    window.grab().save(os.path.join(out_dir, "dark_logs_populated.png"))

    # Light theme samples
    window.toggle_theme()
    for index, name in ((0, "workspace"), (1, "tuning"), (3, "settings")):
        window.go_to(index, save=False)
        app.processEvents()
        app.processEvents()
        window.grab().save(os.path.join(out_dir, f"light_{index}_{name}.png"))
    window.close()
    print(f"captured to {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
