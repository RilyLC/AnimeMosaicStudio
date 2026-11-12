"""Headless Qt smoke tests for the desktop shell."""

from __future__ import annotations

import os
import tempfile
import time
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if os.name == "nt" and not os.environ.get("QT_QPA_FONTDIR"):
    font_dir = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
    if os.path.isdir(font_dir):
        os.environ["QT_QPA_FONTDIR"] = font_dir

from PySide6.QtCore import QPointF, Qt  # noqa: E402
from PySide6.QtGui import QFont, QPixmap  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from anime_mosaic.core.events import ProcessRecord, RunSummary  # noqa: E402
from anime_mosaic.core.settings import (  # noqa: E402
    GROUP_BLEND_LAPLACIAN,
    GROUP_BLEND_SEAMLESS,
    Settings,
)
from anime_mosaic.services.environment import ConnectionReport  # noqa: E402
from anime_mosaic.services.output_index import OutputEntry  # noqa: E402
from anime_mosaic.services.preflight import PreflightEntry  # noqa: E402
from anime_mosaic.ui.main_window import MainWindow  # noqa: E402
from anime_mosaic.services.reuse_groups import ReuseGroup  # noqa: E402
from anime_mosaic.ui.preflight.dialog import PreflightDialog, PreflightModel  # noqa: E402
from anime_mosaic.ui.preflight.editor import MaskEditorDialog  # noqa: E402
from anime_mosaic.ui.preflight.preview import PreviewCanvas  # noqa: E402
from anime_mosaic.ui.preflight.reuse_dialog import ReuseGroupsDialog  # noqa: E402
from anime_mosaic.ui.results.compare import ResultCompareDialog  # noqa: E402
from anime_mosaic.ui.results.controller import ResultItem  # noqa: E402
from anime_mosaic.ui.results.postprocess import PostProcessDialog  # noqa: E402
from anime_mosaic.ui.state import SettingsStore  # noqa: E402
from anime_mosaic.ui.setup_dialog import SetupDialog  # noqa: E402
from anime_mosaic.ui.widgets.output_results import (  # noqa: E402
    FILTER_ALL,
    FILTER_REUSED,
    FILTER_UNPROCESSED,
    OutputResultsPanel,
)
from anime_mosaic.ui.widgets.results import ResultsPanel  # noqa: E402
from anime_mosaic.ui.theme import ThemeManager, app_font_family  # noqa: E402


class UiTestBase(unittest.TestCase):
    app: QApplication

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyle("Fusion")
        cls.app.setFont(QFont(app_font_family(), 10))

    def make_window(self, settings: Settings | None = None, config: str = ""):
        theme = ThemeManager(self.app, "dark")
        theme.apply()
        path = config or os.path.join(self._tmp.name, "config.json")
        store = SettingsStore(settings or Settings(), path=path)
        window = MainWindow(store, theme, auto_probe=False, persist=False)
        window.resize(1280, 820)
        window.show()
        QApplication.processEvents()
        self.addCleanup(window.deleteLater)
        return window

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)


class WindowTests(UiTestBase):
    def test_window_builds_all_pages(self):
        window = self.make_window()
        self.assertEqual(window.stack.count(), 6)
        self.assertEqual(window.sidebar.WIDTH, 228)
        self.assertEqual(window.stack.currentIndex(), 0)
        for index in range(6):
            window.go_to(index, save=False)
            QApplication.processEvents()
            self.assertEqual(window.stack.currentIndex(), index)

    def test_theme_toggle_updates_palette(self):
        window = self.make_window()
        window.toggle_theme()
        self.assertEqual(window.theme.mode, "light")
        self.assertEqual(window._palette.name, "light")
        window.toggle_theme()
        self.assertEqual(window.theme.mode, "dark")

    def test_validation_routes_to_workspace(self):
        window = self.make_window()
        window.start_run()
        self.assertFalse(window.controller.running)
        self.assertEqual(window.stack.currentIndex(), 0)

    def test_action_bar_has_preflight_and_single_run_button(self):
        window = self.make_window()
        self.assertFalse(hasattr(window, "_start_button"))
        self.assertFalse(hasattr(window, "_stop_button"))
        self.assertEqual(window._run_button.text(), "开始处理")
        self.assertEqual(window._preflight_button.text(), "预处理")
        self.assertFalse(window._preflight_button.isEnabled())

    def test_tuning_shows_only_active_blend_advanced_section(self):
        window = self.make_window()
        tuning = window.tuning
        self.assertFalse(tuning._blend_sections[GROUP_BLEND_SEAMLESS].isHidden())
        self.assertTrue(tuning._blend_sections[GROUP_BLEND_LAPLACIAN].isHidden())
        window.store.set("blend", "laplacian")
        QApplication.processEvents()
        self.assertTrue(tuning._blend_sections[GROUP_BLEND_SEAMLESS].isHidden())
        self.assertFalse(tuning._blend_sections[GROUP_BLEND_LAPLACIAN].isHidden())

    def test_comfy_status_updates_from_probe_report(self):
        window = self.make_window()
        self.assertFalse(hasattr(window.sidebar, "_status"))
        window._on_probe(ConnectionReport(True, "0.44.0", "", 0.2))
        QApplication.processEvents()
        self.assertTrue(any("已连接" in entry.message for entry in window.logs.entries))
        window._on_probe(ConnectionReport(False, "", "offline", 0.1))
        QApplication.processEvents()
        self.assertTrue(any("未连接" in entry.message for entry in window.logs.entries))
        self.assertEqual(window._probe_timer.interval(), 8000)

    def test_subdirs_switch_updates_settings(self):
        with tempfile.TemporaryDirectory() as root:
            input_dir = os.path.join(root, "in")
            os.makedirs(input_dir)
            settings = Settings(
                input_dir=input_dir, output_dir=os.path.join(root, "out"), include_subdirs=True
            )
            window = self.make_window(settings)
            self.assertTrue(window.workspace.subdir_switch.isChecked())
            window.workspace.subdir_switch.setChecked(False)
            QApplication.processEvents()
            self.assertFalse(window.store.get("include_subdirs"))
            self.assertFalse(window.workspace.subdir_switch.isChecked())

    def test_preflight_requires_input(self):
        window = self.make_window()
        window.workspace.open_preflight()
        self.assertIsNone(window.workspace._preflight_dialog)

    def test_preflight_ready_requires_every_image(self):
        window = self.make_window()
        preflight = window.workspace.preflight
        preflight.has_results = lambda: True
        preflight.is_stale = lambda settings: False
        preflight.summary = lambda: {"total": 2, "scanned": 1}
        self.assertFalse(window.workspace.preflight_ready())
        preflight.summary = lambda: {"total": 2, "scanned": 2}
        self.assertTrue(window.workspace.preflight_ready())

    def test_preflight_dialog_builds_without_autostart(self):
        with tempfile.TemporaryDirectory() as root:
            input_dir = os.path.join(root, "in")
            os.makedirs(input_dir)
            settings = Settings(
                input_dir=input_dir, output_dir=os.path.join(root, "out"), mosaic_model="x.pt"
            )
            window = self.make_window(settings)
            dialog = PreflightDialog(
                window.workspace.preflight,
                window.store,
                window.theme.palette,
                window,
                autostart=False,
            )
            dialog.show()
            QApplication.processEvents()
            self.assertEqual(dialog._model.rowCount(), 0)
            finished = []
            dialog.finished.connect(finished.append)
            dialog.close()
            QApplication.processEvents()
            self.assertEqual(finished, [0])

    def test_preflight_model_upserts_without_resetting(self):
        theme = ThemeManager(self.app, "dark")
        model = PreflightModel(theme.palette)
        first = PreflightEntry(path="a.png", rel="a.png", regions=1, coverage=3.0)
        second = PreflightEntry(path="b.png", rel="b.png", regions=0, coverage=0.0)
        model.set_all_entries([first, second])
        resets: list[bool] = []
        model.modelReset.connect(lambda: resets.append(True))
        model.upsert(PreflightEntry(path="a.png", rel="a.png", regions=4, coverage=9.5))
        self.assertEqual(model.rowCount(), 2)
        self.assertEqual(resets, [])
        self.assertEqual(model.data(model.index(0, 1)), "4")
        model.upsert(PreflightEntry(path="c.png", rel="c.png", regions=2))
        self.assertEqual(model.rowCount(), 3)
        self.assertEqual(resets, [])
        # A row that stops matching the active filter is removed in place too.
        model.set_filter("mask")
        moved = PreflightEntry(path="a.png", rel="a.png", regions=0, coverage=0.0)
        model.upsert(moved)
        self.assertEqual(model.rowCount(), 1)
        self.assertEqual(resets, [True])

    def test_preflight_stale_settings_restart_everything(self):
        with tempfile.TemporaryDirectory() as root:
            input_dir = os.path.join(root, "in")
            os.makedirs(input_dir)
            settings = Settings(
                input_dir=input_dir, output_dir=os.path.join(root, "out"), mosaic_model="x.pt"
            )
            window = self.make_window(settings)
            dialog = PreflightDialog(
                window.workspace.preflight,
                window.store,
                window.theme.palette,
                window,
                autostart=False,
            )
            modes: list[str] = []
            dialog.controller._entries["a.png"] = PreflightEntry(
                path=os.path.join(input_dir, "a.png"), rel="a.png", regions=1
            )
            dialog.controller.is_stale = lambda settings: True
            dialog.controller.start = (
                lambda settings, mode="all", only_rel=None, only_rels=None: modes.append(mode)
                or True
            )
            self.assertEqual(dialog._idle_text(), "重新预处理")
            dialog._toggle_scan()
            self.assertEqual(modes, ["all"])
            dialog.close()
            QApplication.processEvents()

    def test_preflight_dialog_can_be_resized_and_maximized(self):
        with tempfile.TemporaryDirectory() as root:
            input_dir = os.path.join(root, "in")
            os.makedirs(input_dir)
            settings = Settings(
                input_dir=input_dir, output_dir=os.path.join(root, "out"), mosaic_model="x.pt"
            )
            window = self.make_window(settings)
            dialog = PreflightDialog(
                window.workspace.preflight,
                window.store,
                window.theme.palette,
                window,
                autostart=False,
            )
            self.assertTrue(bool(dialog.windowFlags() & Qt.WindowMaximizeButtonHint))
            self.assertTrue(dialog.isSizeGripEnabled())
            self.assertLessEqual(dialog.minimumWidth(), 1000)
            dialog.close()
            QApplication.processEvents()

    def test_mask_preview_fits_any_aspect_and_zooms(self):
        canvas = PreviewCanvas()
        canvas.resize(600, 300)
        portrait = QPixmap(400, 1600)
        portrait.fill(Qt.black)
        canvas.set_pixmap(portrait)
        fitted = canvas.zoom_percent()
        self.assertLess(fitted, 100.0)
        canvas.zoom_in()
        self.assertGreater(canvas.zoom_percent(), fitted)
        canvas.fit_to_view()
        self.assertAlmostEqual(canvas.zoom_percent(), fitted, places=1)
        landscape = QPixmap(3200, 400)
        landscape.fill(Qt.black)
        canvas.set_pixmap(landscape)
        self.assertLess(canvas.zoom_percent(), 30.0)

    def test_mask_editor_draws_and_undoes(self):
        from PIL import Image

        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "a.png")
            Image.new("RGB", (320, 200), (80, 60, 100)).save(path)
            theme = ThemeManager(self.app, "dark")
            theme.apply()
            dialog = MaskEditorDialog(path, None, None, theme.palette)
            dialog.show()
            QApplication.processEvents()
            dialog._snapshot()
            dialog._canvas._apply_stroke(QPointF(20, 20), QPointF(120, 90), 255)
            dialog._refresh_info()
            self.assertGreater(int((dialog._canvas.mask() > 0).sum()), 0)
            dialog._save()
            self.assertIsNotNone(dialog.result_mask())
            dialog.undo()
            self.assertEqual(int((dialog._canvas.mask() > 0).sum()), 0)
            dialog.close()

    def test_result_compare_and_postprocess_ui(self):
        from PIL import Image

        with tempfile.TemporaryDirectory() as root:
            input_dir = os.path.join(root, "in")
            output_dir = os.path.join(root, "out")
            os.makedirs(input_dir)
            os.makedirs(output_dir)
            original = os.path.join(input_dir, "a.png")
            result = os.path.join(output_dir, "a.png")
            Image.new("RGB", (160, 120), (40, 60, 90)).save(original)
            Image.new("RGB", (160, 120), (90, 60, 40)).save(result)
            settings = Settings(
                input_dir=input_dir,
                output_dir=output_dir,
                mosaic_model="x.pt",
            )
            store = SettingsStore(settings, path=os.path.join(root, "config.json"), autosave=False)
            record = ProcessRecord("a.png", "processed", 1, 2.0, "42")
            item = ResultItem("a.png", original, result, record)
            theme = ThemeManager(self.app, "dark")
            theme.apply()
            dialog = ResultCompareDialog([item], 0, store, theme.palette, None)
            dialog.show()
            QApplication.processEvents()
            self.assertEqual(dialog._position.text(), "1 / 1")
            self.assertEqual(dialog._canvas.mode(), "side")
            dialog._modes.set_current(1)
            self.assertEqual(dialog._canvas.mode(), "split")
            finished = []
            dialog.finished.connect(lambda _result: finished.append(True))
            dialog.close()
            QApplication.processEvents()
            self.assertEqual(finished, [True])

            post = PostProcessDialog(theme.palette, "a.png")
            post.show()
            QApplication.processEvents()
            self.assertIn("开发中", post.windowTitle())
            self.assertEqual(post._file_label.text(), "a.png")
            post.close()

    def test_closing_compare_releases_workspace_lock(self):
        from PIL import Image

        with tempfile.TemporaryDirectory() as root:
            input_dir = os.path.join(root, "in")
            output_dir = os.path.join(root, "out")
            os.makedirs(input_dir)
            os.makedirs(output_dir)
            original = os.path.join(input_dir, "a.png")
            result = os.path.join(output_dir, "a.png")
            Image.new("RGB", (80, 60), (20, 30, 40)).save(original)
            Image.new("RGB", (80, 60), (40, 50, 60)).save(result)
            settings = Settings(
                input_dir=input_dir,
                output_dir=output_dir,
                mosaic_model="x.pt",
            )
            window = self.make_window(settings)
            entry = OutputEntry(
                "a.png",
                original,
                result,
                os.path.getsize(result),
                os.path.getmtime(result),
                status="processed",
            )
            window.workspace._outputs_panel.set_entries([entry], 1)
            window.workspace.open_compare("a.png")
            QApplication.processEvents()
            self.assertIsNotNone(window.workspace._compare_dialog)
            window.workspace._compare_dialog.close()
            QApplication.processEvents()
            self.assertIsNone(window.workspace._compare_dialog)

    def test_output_gallery_filters(self):
        from PIL import Image

        with tempfile.TemporaryDirectory() as root:
            copied = os.path.join(root, "a.png")
            processed = os.path.join(root, "b.png")
            Image.new("RGB", (80, 60), (20, 30, 40)).save(copied)
            Image.new("RGB", (80, 60), (40, 50, 60)).save(processed)
            theme = ThemeManager(self.app, "dark")
            theme.apply()
            panel = OutputResultsPanel(theme.palette)
            panel.resize(900, 500)
            panel.show()
            entries = [
                OutputEntry(
                    "a.png", copied, copied, os.path.getsize(copied),
                    os.path.getmtime(copied), status="copied",
                ),
                OutputEntry(
                    "b.png", processed, processed, os.path.getsize(processed),
                    os.path.getmtime(processed), status="processed",
                ),
            ]
            panel.set_entries(entries, 2)
            QApplication.processEvents()
            self.assertEqual(len(panel.visible_entries()), 2)

            panel.set_filter(FILTER_UNPROCESSED)
            self.assertEqual([entry.rel for entry in panel.visible_entries()], ["a.png"])
            panel.set_filter(FILTER_ALL)
            self.assertEqual(len(panel.visible_entries()), 2)
            self.assertIn("已处理", panel._items["b.png"].text())
            panel.close()

    def test_output_gallery_filters_by_subdirectory(self):
        from PIL import Image

        with tempfile.TemporaryDirectory() as root:
            top = os.path.join(root, "a.png")
            nested = os.path.join(root, "sub", "b.png")
            for path in (top, nested):
                os.makedirs(os.path.dirname(path), exist_ok=True)
                Image.new("RGB", (80, 60), (20, 30, 40)).save(path)
            theme = ThemeManager(self.app, "dark")
            theme.apply()
            panel = OutputResultsPanel(theme.palette)
            panel.set_entries(
                [
                    OutputEntry(
                        "a.png", top, top, os.path.getsize(top),
                        os.path.getmtime(top), status="processed",
                    ),
                    OutputEntry(
                        os.path.join("sub", "b.png"), nested, nested,
                        os.path.getsize(nested), os.path.getmtime(nested),
                        status="processed",
                    ),
                ],
                2,
            )
            self.assertEqual(len(panel.visible_entries()), 2)
            self.assertFalse(panel._dir_filter.isHidden())

            panel._dir_filter.setCurrentIndex(panel._dir_filter.findData("sub"))
            self.assertEqual(
                [entry.rel for entry in panel.visible_entries()],
                [os.path.join("sub", "b.png")],
            )
            panel.close()

    def test_output_gallery_filter_reused(self):
        from PIL import Image

        with tempfile.TemporaryDirectory() as root:
            processed = os.path.join(root, "a.png")
            reused = os.path.join(root, "b.png")
            Image.new("RGB", (80, 60), (20, 30, 40)).save(processed)
            Image.new("RGB", (80, 60), (40, 50, 60)).save(reused)
            theme = ThemeManager(self.app, "dark")
            theme.apply()
            panel = OutputResultsPanel(theme.palette)
            panel.set_entries(
                [
                    OutputEntry(
                        "a.png", processed, processed, os.path.getsize(processed),
                        os.path.getmtime(processed), status="processed",
                    ),
                    OutputEntry(
                        "b.png", reused, reused, os.path.getsize(reused),
                        os.path.getmtime(reused), status="processed", reused=True,
                    ),
                ],
                2,
            )
            panel.set_filter(FILTER_REUSED)
            self.assertEqual([entry.rel for entry in panel.visible_entries()], ["b.png"])
            self.assertIn("复用", panel._items["b.png"].text())
            panel.close()

    def test_reuse_groups_dialog_builds(self):
        import numpy as np

        theme = ThemeManager(self.app, "dark")
        theme.apply()
        mask = np.zeros((80, 80), np.uint8)
        mask[20:40, 20:40] = 255
        group = ReuseGroup(
            "g1", ("a.png", "b.png"), 1, 6.0, 0.9, "a.png", 80, 80, mask
        )
        with tempfile.TemporaryDirectory() as root:
            dialog = ReuseGroupsDialog(
                [group], {}, set(), root, theme.palette
            )
            dialog.show()
            QApplication.processEvents()
            self.assertEqual(dialog._tree.topLevelItemCount(), 1)
            group_item = dialog._tree.topLevelItem(0)
            self.assertEqual(group_item.checkState(0), Qt.Checked)
            self.assertEqual(group_item.childCount(), 2)
            group_item.child(0).setCheckState(0, Qt.Unchecked)
            self.assertEqual(group_item.checkState(0), Qt.PartiallyChecked)
            group_item.child(0).setCheckState(0, Qt.Checked)
            self.assertEqual(group_item.checkState(0), Qt.Checked)
            group_item.setCheckState(0, Qt.Unchecked)
            self.assertEqual(group_item.child(0).checkState(0), Qt.Unchecked)
            self.assertEqual(group_item.child(1).checkState(0), Qt.Unchecked)
            dialog.close()

            entry = PreflightEntry(path="a.png", rel="a.png", regions=1, coverage=6.0)
            model = PreflightModel(theme.palette)
            model.set_all_entries([entry])
            model.set_groups([group])
            model.set_disabled({"a.png"})
            self.assertEqual(model.data(model.index(0, 4)), "已移出")
            self.assertTrue(model.is_disabled("a.png"))
            model.set_disabled(set())
            self.assertFalse(model.is_disabled("a.png"))
            self.assertTrue(model.has_group("a.png"))

    def test_results_panel_live_bar(self):
        from PIL import Image

        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "a.png")
            Image.new("RGB", (200, 120), (20, 30, 40)).save(path)
            theme = ThemeManager(self.app, "dark")
            theme.apply()
            panel = ResultsPanel(theme.palette)
            panel.set_processing("sub/a.png", "ComfyUI 重绘", path)
            self.assertFalse(panel._live.isHidden())
            self.assertIn("sub/a.png", panel._live_file.text())
            panel.clear_processing()
            self.assertTrue(panel._live.isHidden())

    def test_settings_store_autosave(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "config.json")
            store = SettingsStore(Settings(), path=path, autosave=False)
            store.set("steps", 18)
            self.assertEqual(store.get("steps"), 18)
            store.save_now()
            self.assertTrue(os.path.isfile(path))
            store.update({"steps": 20, "cfg": 2.5})
            self.assertEqual(store.get("steps"), 20)
            self.assertEqual(store.get("cfg"), 2.5)


class PipelineWiringTests(UiTestBase):
    def test_start_and_finish_update_ui(self):
        with tempfile.TemporaryDirectory() as root:
            input_dir = os.path.join(root, "in")
            os.makedirs(input_dir)
            model_path = os.path.join(root, "mosaic.pt")
            with open(model_path, "wb") as handle:
                handle.write(b"fake")
            output_dir = os.path.join(root, "out")
            os.makedirs(output_dir)
            settings = Settings(
                input_dir=input_dir,
                output_dir=output_dir,
                comfy_dir=root,
                mosaic_model=model_path,
                size=512,
                steps=4,
            )
            window = self.make_window(settings)

            def fake_run_batch(settings, reporter, stop_event=None, **kwargs):
                time.sleep(0.08)
                reporter.log("info", "fake batch started")
                reporter.stage("a.png", "detect")
                reporter.progress(1, 1, "a.png", 1.0, 0.0)
                record = ProcessRecord("a.png", "processed", regions=1, seconds=1.2, seed="42")
                reporter.result(record, os.path.join(output_dir, "a.png"))
                summary = RunSummary(
                    total=1, processed=1, regions=1, elapsed=1.2, stopped=False
                )
                reporter.done(summary)
                return summary

            window.workspace.preflight_ready = lambda: True
            with mock.patch("anime_mosaic.ui.controller.run_batch", fake_run_batch):
                window.start_run()
                self.assertTrue(window.controller.running)
                deadline = time.time() + 4
                while window.controller.running and time.time() < deadline:
                    QTest.qWait(25)
                QTest.qWait(250)

            self.assertFalse(window.controller.running)
            self.assertTrue(window._run_button.isEnabled())
            self.assertEqual(window._run_button.text(), "开始处理")
            self.assertEqual(len(window.workspace._results.model.records()), 1)
            self.assertEqual(window.workspace.stat_tiles["processed"].value_label.text(), "1")
            self.assertTrue(any("fake batch started" in e.message for e in window.logs.entries))
            self.assertIn("处理记录 (1)", window.workspace._segment._buttons[1].text())

    def test_stop_while_idle_is_safe(self):
        window = self.make_window()
        window.stop_run()
        self.assertFalse(window.controller.running)


class SetupDialogTests(UiTestBase):
    """The first-run wizard must build without a window and commit each step."""

    def make_dialog(self, first_run: bool = True):
        store = SettingsStore(Settings(), path=os.path.join(self._tmp.name, "setup.json"))
        theme = ThemeManager(self.app, "dark")
        dialog = SetupDialog(store, theme.palette, None, first_run=first_run)
        self.addCleanup(dialog.deleteLater)
        return store, dialog

    def test_wizard_has_three_steps_and_commits_each_one(self):
        store, dialog = self.make_dialog()
        self.assertEqual(dialog._stack.count(), 3)
        self.assertEqual(dialog._step, 0)

        dialog._python.set_path(r"D:\Python\python.exe")
        dialog._on_next()
        self.assertEqual(store.get("python_exe"), r"D:\Python\python.exe")
        self.assertEqual(dialog._step, 1)

        dialog._comfy_dir.set_path(r"D:\ComfyUI")
        dialog._on_next()
        self.assertEqual(store.get("comfy_dir"), r"D:\ComfyUI")
        self.assertEqual(dialog._step, 2)

        dialog._mosaic.set_path(r"D:\ComfyUI\models\mosaic_l.pt")
        dialog._nsfw.set_path(r"D:\ComfyUI\models\nsfw.pt")
        dialog._on_finish()
        self.assertEqual(store.get("mosaic_model"), r"D:\ComfyUI\models\mosaic_l.pt")
        self.assertEqual(store.get("nsfw_model"), r"D:\ComfyUI\models\nsfw.pt")
        self.assertEqual(dialog.result(), int(SetupDialog.Accepted))

    def test_finish_points_at_the_first_missing_path(self):
        store, dialog = self.make_dialog()
        dialog._on_finish()
        self.assertEqual(dialog._step, 0)
        self.assertTrue(dialog._status.isVisibleTo(dialog))

    def test_later_button_rejects_without_writing(self):
        store, dialog = self.make_dialog()
        dialog._python.set_path(r"D:\Python\python.exe")
        dialog.reject()
        self.assertEqual(dialog.result(), int(SetupDialog.Rejected))
        self.assertEqual(store.get("python_exe"), "")


if __name__ == "__main__":
    unittest.main()
