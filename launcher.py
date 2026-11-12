"""Standalone launcher for AnimeMosaicStudio.

``AnimeMosaicStudioLauncher.exe`` is a tiny wrapper compiled from this file
(see ``build_launcher.bat``).  It only uses the standard library, so it starts
instantly and does not need Qt, torch or ultralytics itself.  At run time it:

1. reads ``config.json`` next to the executable (``python_exe`` wins);
2. falls back to the ``AMS_PYTHON`` environment variable;
3. then to the ``python.exe`` on PATH and to the interpreters registered with
   the ``py`` launcher - each candidate is verified by running it first;
4. if nothing runs at all, asks the user to pick a ``python.exe`` /
   ``pythonw.exe`` in a file dialog and writes the choice back to
   ``config.json``;
5. probes the resolved interpreter for the runtime dependencies;
6. starts ``AnimeMosaicStudio.pyw`` with that interpreter.

No directory is ever scanned for a Python installation: the interpreter is
either configured, present on PATH, or chosen by the user.

Command line::

    AnimeMosaicStudioLauncher.exe                 start the GUI
    AnimeMosaicStudioLauncher.exe --check         show the resolved interpreter
    AnimeMosaicStudioLauncher.exe --print-python  print the pythonw path (scripts)
    AnimeMosaicStudioLauncher.exe --cli -i D:\\in  run the CLI in a console

The module is import-safe without Windows: the helpers used by the tests do not
touch the registry, dialogs or Win32 APIs.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile

APP_SCRIPT = "AnimeMosaicStudio.pyw"
CONFIG_NAME = "config.json"

#: Imported by the GUI or by a normal processing run.
REQUIRED_MODULES = ("PySide6", "numpy", "cv2", "PIL", "requests")
#: Only needed for detection.
OPTIONAL_MODULES = ("torch", "ultralytics")

_PROBE_SOURCE = (
    "import importlib.util, sys\n"
    "names = sys.argv[1].split(',')\n"
    "missing = [n for n in names if importlib.util.find_spec(n) is None]\n"
    "print('PY ' + sys.version.split()[0])\n"
    "print('MISSING ' + ','.join(missing))\n"
)


# --------------------------------------------------------------------- paths
def project_dir() -> str:
    """Directory holding ``AnimeMosaicStudio.pyw`` and ``config.json``."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def read_config(directory: str) -> dict:
    """Best-effort read of ``config.json``; never raises."""
    path = os.path.join(directory, CONFIG_NAME)
    try:
        # utf-8-sig: a BOM from a hand-edited config.json must not break startup.
        with open(path, "r", encoding="utf-8-sig") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def configured_python(config: dict) -> str:
    value = config.get("python_exe")
    return value.strip() if isinstance(value, str) else ""


def as_python(path: str) -> str:
    """Normalise ``pythonw.exe`` to ``python.exe`` (for probing and the CLI)."""
    name = os.path.basename(path).lower()
    if name == "pythonw.exe":
        sibling = os.path.join(os.path.dirname(path), "python.exe")
        if os.path.isfile(sibling):
            return sibling
    return path


def as_pythonw(path: str) -> str:
    """Prefer the windowless interpreter when starting the GUI."""
    name = os.path.basename(path).lower()
    if name == "python.exe":
        sibling = os.path.join(os.path.dirname(path), "pythonw.exe")
        if os.path.isfile(sibling):
            return sibling
    return path


def write_config(directory: str, updates: dict) -> bool:
    """Merge ``updates`` into ``config.json`` atomically.  Never raises."""
    path = os.path.join(directory, CONFIG_NAME)
    data = read_config(directory)
    data.update(updates)
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        return True
    except OSError:
        return False


def _path_pythons() -> list[str]:
    """``python.exe`` / ``pythonw.exe`` on PATH (the user's default install)."""
    found: list[str] = []
    if os.name != "nt":
        return found
    for name in ("python.exe", "pythonw.exe"):
        try:
            completed = subprocess.run(
                ["where", name],
                capture_output=True,
                text=True,
                errors="replace",
                timeout=15.0,
                creationflags=_no_window_flag(),
            )
        except (OSError, subprocess.SubprocessError):
            continue
        for line in (completed.stdout or "").splitlines():
            path = line.strip()
            if path.lower().endswith(".exe") and os.path.isfile(path):
                found.append(path)
    return found


def _py_launcher_pythons() -> list[str]:
    """Interpreters registered with the Windows ``py`` launcher."""
    found: list[str] = []
    if os.name != "nt":
        return found
    try:
        completed = subprocess.run(
            ["py", "-0p"],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=15.0,
            creationflags=_no_window_flag(),
        )
    except (OSError, subprocess.SubprocessError):
        return found
    for line in (completed.stdout or "").splitlines():
        match = re.search(r"[A-Za-z]:\\", line)
        if not match:
            continue
        path = line[match.start() :].strip().strip('"')
        if path.lower().endswith(".exe") and os.path.isfile(path):
            found.append(path)
    return found


def candidate_pythons(directory: str, config: dict | None = None) -> list[str]:
    """Interpreters to try, in priority order, duplicates removed.

    Explicit choices come first (``config.json``, then ``AMS_PYTHON``); after
    that the environment the user already has: PATH, then the ``py`` launcher.
    Nothing is scanned on disk, and every candidate is verified by actually
    running it before it is used.
    """
    config = read_config(directory) if config is None else config
    ordered: list[str] = []
    configured = configured_python(config)
    if configured:
        ordered.append(configured)
    env = (os.environ.get("AMS_PYTHON") or "").strip()
    if env:
        ordered.append(env)
    ordered.extend(_path_pythons())
    ordered.extend(_py_launcher_pythons())

    result: list[str] = []
    seen: set[str] = set()
    for path in ordered:
        path = as_python(os.path.expandvars(path))
        key = os.path.normcase(os.path.abspath(path)) if path else ""
        if not key or key in seen:
            continue
        seen.add(key)
        if os.path.isfile(path):
            result.append(path)
    return result


def resolve_python(directory: str, config: dict | None = None) -> str | None:
    """First candidate on disk (not necessarily verified)."""
    found = candidate_pythons(directory, config)
    return found[0] if found else None


def search_python(directory: str, config: dict | None = None) -> tuple[str, list[str]]:
    """First candidate that actually starts, plus its missing modules.

    ``("", [])`` means nothing on this machine could be started at all.  When
    every runnable candidate lacks modules, the first one is returned together
    with its missing list so the caller can show the pip hint.
    """
    fallback: tuple[str, list[str]] = ("", [])
    for path in candidate_pythons(directory, config):
        ok, _detail, missing = probe_python(path)
        if not ok:
            continue
        if not missing:
            return path, []
        if not fallback[0]:
            fallback = (path, missing)
    return fallback


def _pick_with_comdlg(initial: str) -> tuple[str, bool]:
    """Explorer-style file dialog.  Returns ``(path, failed)``.

    ``failed`` is False when the user simply cancelled: only a real creation
    failure (non-zero ``CommDlgExtendedError``) sets it to True.
    """
    try:
        import ctypes
        from ctypes import wintypes
    except Exception:
        return "", True

    class _OpenFileName(ctypes.Structure):
        _fields_ = [
            ("lStructSize", wintypes.DWORD),
            ("hwndOwner", wintypes.HWND),
            ("lpstrFilter", wintypes.LPCWSTR),
            ("lpstrCustomFilter", wintypes.LPWSTR),
            ("nMaxCustFilter", wintypes.DWORD),
            ("nFilterIndex", wintypes.DWORD),
            ("lpstrFile", wintypes.LPWSTR),
            ("nMaxFile", wintypes.DWORD),
            ("lpstrFileTitle", wintypes.LPWSTR),
            ("nMaxFileTitle", wintypes.DWORD),
            ("lpstrInitialDir", wintypes.LPCWSTR),
            ("lpstrTitle", wintypes.LPCWSTR),
            ("Flags", wintypes.DWORD),
            ("nFileOffset", wintypes.WORD),
            ("nFileExtension", wintypes.WORD),
            ("lpstrDefExt", wintypes.LPCWSTR),
            ("lCustData", wintypes.LPARAM),
            ("lpfnHook", wintypes.LPVOID),
            ("lpTemplateName", wintypes.LPCWSTR),
            ("pvReserved", wintypes.LPVOID),
            ("dwReserved", wintypes.DWORD),
            ("FlagsEx", wintypes.DWORD),
        ]

    buffer = ctypes.create_unicode_buffer(1024)
    filters = (
        "Python 解释器 (python.exe;pythonw.exe)\0python.exe;pythonw.exe\0"
        "可执行文件 (*.exe)\0*.exe\0所有文件 (*.*)\0*.*\0\0"
    )
    dialog = _OpenFileName()
    dialog.lStructSize = ctypes.sizeof(_OpenFileName)
    dialog.lpstrFilter = filters
    # An array cannot be assigned to an LPWSTR field directly: cast it first.
    dialog.lpstrFile = ctypes.cast(buffer, wintypes.LPWSTR)
    dialog.nMaxFile = len(buffer)
    if initial and os.path.isdir(initial):
        dialog.lpstrInitialDir = initial
    dialog.lpstrTitle = "首次使用：请选择 Python 解释器"
    # FILEMUSTEXIST | PATHMUSTEXIST | EXPLORER | NOCHANGEDIR
    dialog.Flags = 0x00001000 | 0x00000800 | 0x00080000 | 0x00000008

    initialized = False
    try:
        # The Explorer-style dialog is COM based.  Without an STA on the calling
        # thread GetOpenFileNameW fails with CDERR_INITIALIZATION (0x0001).
        if ctypes.windll.ole32.CoInitializeEx(None, 0x2) == 0:  # S_OK
            initialized = True
    except Exception:
        pass
    try:
        if not ctypes.windll.comdlg32.GetOpenFileNameW(ctypes.byref(dialog)):
            return "", bool(ctypes.windll.comdlg32.CommDlgExtendedError())
        return buffer.value.strip(), False
    except Exception:
        return "", True
    finally:
        if initialized:
            try:
                ctypes.windll.ole32.CoUninitialize()
            except Exception:
                pass


def _pick_with_powershell(initial: str = "") -> tuple[str, bool]:
    """Fallback dialog: WinForms inside a separate Windows PowerShell process.

    Returns ``(path, failed)`` like :func:`_pick_with_comdlg`; the script always
    writes the result file so a cancel (empty file) is not mistaken for a crash.
    """
    target = os.path.join(tempfile.gettempdir(), f"ams_pick_{os.getpid()}.txt")
    start = os.path.dirname(initial) if os.path.isfile(initial) else initial
    start = (start or "").replace("'", "''")
    script = (
        "Add-Type -AssemblyName System.Windows.Forms;"
        "$d = New-Object System.Windows.Forms.OpenFileDialog;"
        "$d.Title = '首次使用：请选择 Python 解释器';"
        "$d.Filter = 'Python 解释器 (*.exe)|*.exe|所有文件 (*.*)|*.*';"
        "$d.CheckFileExists = $true;"
        f"$d.InitialDirectory = '{start}';"
        "$chosen = '';"
        "if ($d.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {"
        " $chosen = $d.FileName };"
        f"[IO.File]::WriteAllText('{target}', $chosen, [Text.Encoding]::UTF8)"
    )
    command = [
        "powershell",
        "-NoProfile",
        "-STA",
        "-WindowStyle",
        "Hidden",
        "-Command",
        script,
    ]
    try:
        subprocess.run(
            command,
            capture_output=True,
            timeout=600,
            creationflags=_no_window_flag(),
        )
    except (OSError, subprocess.SubprocessError):
        return "", True
    try:
        with open(target, "r", encoding="utf-8-sig") as handle:
            return handle.read().strip(), False
    except OSError:
        # The script never got far enough to write its result.
        return "", True
    finally:
        try:
            os.remove(target)
        except OSError:
            pass


def pick_python(initial: str = "") -> str:
    """Ask for an interpreter with a Windows file dialog, never guessing."""
    if os.name != "nt":
        return ""
    chosen, failed = _pick_with_comdlg(initial)
    if chosen or not failed:
        # A path, or a deliberate cancel: nothing else to try.
        return chosen
    chosen, failed = _pick_with_powershell(initial)
    if chosen or not failed:
        return chosen
    _alert(
        "无法打开文件选择框。\n"
        "请在 config.json 里手动填写 python_exe，或设置环境变量 AMS_PYTHON。"
    )
    return ""


def choose_python(directory: str) -> str:
    """Interactive first-run fallback: pick, verify and remember an interpreter."""
    configured = configured_python(read_config(directory))
    initial = os.path.dirname(configured) if configured else os.path.expanduser("~")
    chosen = pick_python(initial)
    if not chosen:
        return ""
    chosen = as_python(chosen)
    ok, detail, _missing = probe_python(chosen)
    if not ok:
        _alert(f"这个解释器无法运行：\n{chosen}\n\n{detail}")
        return ""
    if not write_config(directory, {"python_exe": chosen}):
        _alert(f"无法写入 config.json，但会继续使用：\n{chosen}")
    return chosen


# ------------------------------------------------------------------- probing
def probe_python(python: str, timeout: float = 30.0) -> tuple[bool, str, list[str]]:
    """Return ``(ok, version, missing_required)`` for one interpreter."""
    modules = ",".join(REQUIRED_MODULES)
    try:
        completed = subprocess.run(
            [python, "-c", _PROBE_SOURCE, modules],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=_no_window_flag(),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc), list(REQUIRED_MODULES)
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        return False, detail.splitlines()[-1] if detail else "无法运行该解释器", list(REQUIRED_MODULES)
    version = ""
    missing: list[str] = []
    for line in completed.stdout.splitlines():
        if line.startswith("PY "):
            version = line[3:].strip()
        elif line.startswith("MISSING "):
            missing = [item for item in line[8:].split(",") if item]
    return True, version, missing


# ------------------------------------------------------------------ launching
def launch_gui(python: str, directory: str) -> subprocess.Popen:
    script = os.path.join(directory, APP_SCRIPT)
    flags = 0
    if os.name == "nt":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    return subprocess.Popen(
        [as_pythonw(python), script],
        cwd=directory,
        creationflags=flags,
        close_fds=True,
    )


def run_cli(python: str, directory: str, args: list[str]) -> int:
    command = [as_python(python), "-m", "anime_mosaic.cli", *args]
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    try:
        return subprocess.call(command, cwd=directory, env=env)
    except OSError as exc:
        _alert(f"无法启动命令行：{exc}")
        return 1


# --------------------------------------------------------------------- win32
def _no_window_flag() -> int:
    return subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def _hide_own_console() -> None:
    """Hide the console window when the launcher owns it (double-click)."""
    if os.name != "nt":
        return
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        hwnd = kernel32.GetConsoleWindow()
        if not hwnd:
            return
        buffer = (ctypes.c_uint * 4)()
        count = kernel32.GetConsoleProcessList(buffer, 4)
        if count == 1:
            ctypes.windll.user32.ShowWindow(hwnd, 0)
    except Exception:
        return


def _alert(message: str, title: str = "AnimeMosaicStudio") -> None:
    if os.name == "nt":
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(None, message, title, 0x10)
            return
        except Exception:
            pass
    print(message, file=sys.stderr)


def _pip_hint(python: str) -> str:
    return f'"{as_python(python)}" -m pip install -r requirements.txt'


def _missing_message(python: str, missing: list[str]) -> str:
    return (
        "当前 Python 环境缺少运行依赖：\n"
        f"  {', '.join(missing)}\n\n"
        f"解释器：{python}\n\n"
        "请安装后再启动：\n"
        f"  {_pip_hint(python)}\n\n"
        "如果这个解释器不对，可在 设置 → 运行环境 里修改 Python 路径，"
        "或设置环境变量 AMS_PYTHON，或删除 config.json 里的 python_exe 让启动器重新询问。"
    )


# ---------------------------------------------------------------------- main
def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    directory = project_dir()

    if "--print-python" in args:
        python, _missing = search_python(directory)
        if not python:
            return 1
        print(as_pythonw(python))
        return 0

    if "--check" in args:
        return _check(directory)

    if "--cli" in args:
        rest = args[args.index("--cli") + 1 :]
        python, missing = search_python(directory)
        if not python:
            python = choose_python(directory)
        if not python:
            _alert(
                "找不到可用的 Python 解释器。\n"
                "请安装 Python，或在 config.json 里填写 python_exe，或设置环境变量 AMS_PYTHON。"
            )
            return 1
        if missing:
            _alert(_missing_message(python, missing))
            return 1
        return run_cli(python, directory, rest)

    _hide_own_console()
    script = os.path.join(directory, APP_SCRIPT)
    if not os.path.isfile(script):
        _alert(f"在程序目录里找不到 {APP_SCRIPT}：\n{directory}")
        return 1

    python, missing = search_python(directory)
    if not python:
        # Nothing configured and nothing usable on PATH: ask instead of guessing.
        python = choose_python(directory)
        if not python:
            return 1
        ok, detail, missing = probe_python(python)
        if not ok:
            _alert(f"无法使用该 Python：\n{python}\n\n{detail}")
            return 1
    if missing:
        _alert(_missing_message(python, missing))
        return 1

    try:
        launch_gui(python, directory)
    except OSError as exc:
        _alert(f"启动失败：{exc}\n\n解释器：{python}")
        return 1
    return 0


def _check(directory: str) -> int:
    """Print the resolved interpreter and dependency state."""
    python, missing = search_python(directory)
    if not python:
        print("没有找到可用的 Python 解释器。")
        print("请安装 Python，或在 config.json 里填写 python_exe，或设置环境变量 AMS_PYTHON。")
        return 1
    ok, version, _ = probe_python(python)
    print(f"程序目录：{directory}")
    print(f"解释器：{python}")
    print(f"版本：{version or '未知'}")
    if not ok:
        print("状态：无法运行该解释器")
        return 1
    print(f"必需依赖：{'齐全' if not missing else '缺少 ' + ', '.join(missing)}")
    installed = _installed(python)
    optional = [name for name in OPTIONAL_MODULES if name not in installed]
    print(f"检测依赖：{'齐全' if not optional else '缺少 ' + ', '.join(optional)}")
    return 0 if not missing else 1


def _installed(python: str) -> set[str]:
    """Modules of :data:`OPTIONAL_MODULES` that the interpreter can import."""
    modules = ",".join(OPTIONAL_MODULES)
    try:
        completed = subprocess.run(
            [python, "-c", _PROBE_SOURCE, modules],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30.0,
            creationflags=_no_window_flag(),
        )
    except (OSError, subprocess.SubprocessError):
        return set()
    missing: set[str] = set()
    for line in completed.stdout.splitlines():
        if line.startswith("MISSING "):
            missing = {item for item in line[8:].split(",") if item}
    return {name for name in OPTIONAL_MODULES if name not in missing}


if __name__ == "__main__":
    raise SystemExit(main())
