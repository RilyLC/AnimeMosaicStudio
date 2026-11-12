"""AnimeMosaicStudio windowed entry point."""

from __future__ import annotations

import os
import sys
import traceback

APP_DIR = os.path.dirname(os.path.abspath(__file__))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)


def _fatal(message: str) -> None:
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(  # type: ignore[attr-defined]
            0, message, "AnimeMosaicStudio 启动失败", 0x10
        )
    except Exception:
        print(message, file=sys.stderr)


def main() -> int:
    try:
        from anime_mosaic.ui.app import main as run_gui

        return run_gui()
    except ModuleNotFoundError as exc:
        missing = getattr(exc, "name", "") or str(exc)
        hint = (
            f"缺少依赖：{missing}\n\n"
            "请先双击运行“install dependencies.bat”，或手动执行：\n"
            "  python -m pip install -r requirements.txt"
        )
        _write_log(traceback.format_exc())
        _fatal(hint)
        return 1
    except Exception:
        detail = traceback.format_exc()
        _write_log(detail)
        _fatal(
            "程序启动失败：\n\n"
            + detail[-1200:]
            + f"\n\n详细日志：{os.path.join(APP_DIR, 'AnimeMosaicStudio.log')}"
        )
        return 1


def _write_log(detail: str) -> None:
    try:
        with open(os.path.join(APP_DIR, "AnimeMosaicStudio.log"), "a", encoding="utf-8") as handle:
            handle.write(detail + "\n")
    except OSError:
        pass


if __name__ == "__main__":
    sys.exit(main())
