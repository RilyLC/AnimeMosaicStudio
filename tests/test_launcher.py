"""Launcher: config handling, interpreter resolution and dependency probing."""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

import launcher


def _touch(path: str) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(b"")
    return path


class ConfigTests(unittest.TestCase):
    def test_missing_and_invalid_config_are_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(launcher.read_config(tmp), {})
            with open(os.path.join(tmp, launcher.CONFIG_NAME), "w", encoding="utf-8") as handle:
                handle.write("{not json")
            self.assertEqual(launcher.read_config(tmp), {})

    def test_configured_python_is_trimmed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, launcher.CONFIG_NAME)
            with open(path, "w", encoding="utf-8") as handle:
                json.dump({"python_exe": "  D:\\Python\\python.exe  "}, handle)
            self.assertEqual(
                launcher.configured_python(launcher.read_config(tmp)),
                r"D:\Python\python.exe",
            )

    def test_write_config_merges_updates_and_leaves_no_temp_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, launcher.CONFIG_NAME)
            with open(path, "w", encoding="utf-8") as handle:
                json.dump({"comfy_dir": "D:\\ComfyUI"}, handle)

            self.assertTrue(launcher.write_config(tmp, {"python_exe": "D:\\Py\\python.exe"}))

            with open(path, encoding="utf-8") as handle:
                data = json.load(handle)
            self.assertEqual(data["python_exe"], "D:\\Py\\python.exe")
            self.assertEqual(data["comfy_dir"], "D:\\ComfyUI")
            self.assertFalse(os.path.exists(path + ".tmp"))

    def test_write_config_creates_a_missing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertTrue(launcher.write_config(tmp, {"python_exe": "x"}))
            self.assertEqual(launcher.read_config(tmp), {"python_exe": "x"})

    def test_write_config_reports_failure_instead_of_raising(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = os.path.join(tmp, "absent")
            self.assertFalse(launcher.write_config(missing, {"python_exe": "x"}))


class InterpreterTests(unittest.TestCase):
    def test_as_python_and_as_pythonw_switch_siblings(self):
        with tempfile.TemporaryDirectory() as tmp:
            console = _touch(os.path.join(tmp, "python.exe"))
            windowed = _touch(os.path.join(tmp, "pythonw.exe"))
            self.assertEqual(launcher.as_python(windowed), console)
            self.assertEqual(launcher.as_pythonw(console), windowed)
            # A lone interpreter is returned unchanged.
            other = _touch(os.path.join(tmp, "other", "python.exe"))
            self.assertEqual(launcher.as_pythonw(other), other)

    def test_candidate_order_prefers_config_then_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            configured = _touch(os.path.join(tmp, "a", "python.exe"))
            from_env = _touch(os.path.join(tmp, "b", "python.exe"))
            with mock.patch.dict(os.environ, {"AMS_PYTHON": from_env}, clear=False):
                with mock.patch.object(launcher, "_path_pythons", return_value=[]):
                    with mock.patch.object(launcher, "_py_launcher_pythons", return_value=[]):
                        found = launcher.candidate_pythons(
                            tmp, {"python_exe": configured, "comfy_dir": ""}
                        )
            self.assertEqual(found, [configured, from_env])

    def test_candidate_list_skips_missing_and_duplicates(self):
        with tempfile.TemporaryDirectory() as tmp:
            real = _touch(os.path.join(tmp, "python.exe"))
            with mock.patch.dict(os.environ, {"AMS_PYTHON": real}, clear=False):
                with mock.patch.object(launcher, "_path_pythons", return_value=[]):
                    with mock.patch.object(launcher, "_py_launcher_pythons", return_value=[]):
                        found = launcher.candidate_pythons(tmp, {"python_exe": real, "comfy_dir": ""})
            self.assertEqual(found, [real])

    def test_nothing_is_guessed_when_nothing_is_configured(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"AMS_PYTHON": ""}, clear=False):
                with mock.patch.object(launcher, "_path_pythons", return_value=[]):
                    with mock.patch.object(launcher, "_py_launcher_pythons", return_value=[]):
                        self.assertEqual(launcher.candidate_pythons(tmp, {"comfy_dir": ""}), [])
                        self.assertIsNone(launcher.resolve_python(tmp, {}))

    def test_path_and_py_launcher_come_after_the_explicit_choices(self):
        with tempfile.TemporaryDirectory() as tmp:
            configured = _touch(os.path.join(tmp, "cfg", "python.exe"))
            on_path = _touch(os.path.join(tmp, "path", "python.exe"))
            from_py = _touch(os.path.join(tmp, "pylauncher", "python.exe"))
            with mock.patch.dict(os.environ, {"AMS_PYTHON": ""}, clear=False):
                with mock.patch.object(launcher, "_path_pythons", return_value=[on_path]):
                    with mock.patch.object(launcher, "_py_launcher_pythons", return_value=[from_py]):
                        found = launcher.candidate_pythons(tmp, {"python_exe": configured})
            self.assertEqual(found, [configured, on_path, from_py])

    def test_choose_python_remembers_the_picked_interpreter(self):
        with tempfile.TemporaryDirectory() as tmp:
            picked = _touch(os.path.join(tmp, "pick", "python.exe"))
            with mock.patch.object(launcher, "pick_python", return_value=picked):
                with mock.patch.object(launcher, "probe_python", return_value=(True, "3.12", [])):
                    chosen = launcher.choose_python(tmp)
            self.assertEqual(chosen, picked)
            self.assertEqual(launcher.read_config(tmp)["python_exe"], picked)

    def test_choose_python_returns_empty_when_the_user_cancels(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(launcher, "pick_python", return_value=""):
                self.assertEqual(launcher.choose_python(tmp), "")
            self.assertEqual(launcher.read_config(tmp), {})

    def test_choose_python_rejects_an_interpreter_that_cannot_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            picked = _touch(os.path.join(tmp, "pick", "python.exe"))
            with mock.patch.object(launcher, "pick_python", return_value=picked):
                with mock.patch.object(launcher, "probe_python", return_value=(False, "boom", [])):
                    with mock.patch.object(launcher, "_alert"):
                        self.assertEqual(launcher.choose_python(tmp), "")
            self.assertEqual(launcher.read_config(tmp), {})

    def test_probe_reports_version_for_the_current_interpreter(self):
        ok, version, missing = launcher.probe_python(sys.executable)
        self.assertTrue(ok)
        self.assertTrue(version)
        self.assertTrue(set(missing) <= set(launcher.REQUIRED_MODULES))


class PickerTests(unittest.TestCase):
    """The dialog chain: native first, PowerShell fallback, then advice."""

    def test_native_dialog_result_is_used_directly(self):
        with mock.patch.object(
            launcher, "_pick_with_comdlg", return_value=(r"D:\Py\python.exe", False)
        ):
            with mock.patch.object(launcher, "_pick_with_powershell") as fallback:
                self.assertEqual(launcher.pick_python(), r"D:\Py\python.exe")
        fallback.assert_not_called()

    def test_cancel_does_not_open_the_fallback_dialog(self):
        with mock.patch.object(launcher, "_pick_with_comdlg", return_value=("", False)):
            with mock.patch.object(launcher, "_pick_with_powershell") as fallback:
                with mock.patch.object(launcher, "_alert") as alert:
                    self.assertEqual(launcher.pick_python(), "")
        fallback.assert_not_called()
        alert.assert_not_called()

    def test_failed_native_dialog_falls_back_to_powershell(self):
        with mock.patch.object(launcher, "_pick_with_comdlg", return_value=("", True)):
            with mock.patch.object(
                launcher, "_pick_with_powershell", return_value=(r"D:\Py\python.exe", False)
            ) as fallback:
                with mock.patch.object(launcher, "_alert") as alert:
                    self.assertEqual(launcher.pick_python(), r"D:\Py\python.exe")
        fallback.assert_called_once()
        alert.assert_not_called()

    def test_cancel_in_the_fallback_dialog_is_not_a_failure(self):
        with mock.patch.object(launcher, "_pick_with_comdlg", return_value=("", True)):
            with mock.patch.object(launcher, "_pick_with_powershell", return_value=("", False)):
                with mock.patch.object(launcher, "_alert") as alert:
                    self.assertEqual(launcher.pick_python(), "")
        alert.assert_not_called()

    def test_both_dialogs_failing_explains_the_manual_option(self):
        with mock.patch.object(launcher, "_pick_with_comdlg", return_value=("", True)):
            with mock.patch.object(launcher, "_pick_with_powershell", return_value=("", True)):
                with mock.patch.object(launcher, "_alert") as alert:
                    self.assertEqual(launcher.pick_python(), "")
        self.assertIn("config.json", alert.call_args[0][0])


class PrintPythonTests(unittest.TestCase):
    def test_print_python_emits_the_configured_interpreter(self):
        with tempfile.TemporaryDirectory() as tmp:
            console = _touch(os.path.join(tmp, "python.exe"))
            with open(os.path.join(tmp, launcher.CONFIG_NAME), "w", encoding="utf-8") as handle:
                json.dump({"python_exe": console}, handle)
            buffer = io.StringIO()
            with mock.patch.object(launcher, "project_dir", return_value=tmp):
                with mock.patch.dict(os.environ, {"AMS_PYTHON": ""}, clear=False):
                    with mock.patch.object(launcher, "_path_pythons", return_value=[]):
                        with mock.patch.object(launcher, "_py_launcher_pythons", return_value=[]):
                            with mock.patch.object(
                                launcher, "probe_python", return_value=(True, "3.12", [])
                            ):
                                with redirect_stdout(buffer):
                                    code = launcher.main(["--print-python"])
            self.assertEqual(code, 0)
            self.assertEqual(buffer.getvalue().strip(), console)

    def test_print_python_fails_when_nothing_is_configured(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(launcher, "project_dir", return_value=tmp):
                with mock.patch.dict(os.environ, {"AMS_PYTHON": ""}, clear=False):
                    with mock.patch.object(launcher, "_path_pythons", return_value=[]):
                        with mock.patch.object(launcher, "_py_launcher_pythons", return_value=[]):
                            self.assertEqual(launcher.main(["--print-python"]), 1)

    def test_search_skips_an_interpreter_that_cannot_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            broken = _touch(os.path.join(tmp, "a", "python.exe"))
            working = _touch(os.path.join(tmp, "b", "python.exe"))
            answers = {broken: (False, "boom", []), working: (True, "3.12", [])}
            with mock.patch.object(launcher, "_path_pythons", return_value=[broken, working]):
                with mock.patch.object(launcher, "_py_launcher_pythons", return_value=[]):
                    with mock.patch.object(
                        launcher, "probe_python", side_effect=lambda p: answers[p]
                    ):
                        self.assertEqual(launcher.search_python(tmp), (working, []))

    def test_search_reports_missing_modules_when_no_candidate_is_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            only = _touch(os.path.join(tmp, "python.exe"))
            with mock.patch.object(launcher, "_path_pythons", return_value=[only]):
                with mock.patch.object(launcher, "_py_launcher_pythons", return_value=[]):
                    with mock.patch.object(
                        launcher, "probe_python", return_value=(True, "3.12", ["PySide6"])
                    ):
                        self.assertEqual(launcher.search_python(tmp), (only, ["PySide6"]))


if __name__ == "__main__":
    unittest.main()
