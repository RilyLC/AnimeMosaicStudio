"""PySide6 application bootstrap (the only place a QApplication is created)."""

from __future__ import annotations

import sys

from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtGui import QFont, QGuiApplication
from PySide6.QtWidgets import QApplication

from .. import __version__
from ..core.settings import load_settings
from ..logging_setup import setup_logging
from . import branding
from .main_window import MainWindow
from .state import SettingsStore
from .theme import ThemeManager, app_font_family


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv if argv is None else argv)
    smoke_test = "--smoke-test" in args
    args = [arg for arg in args if arg != "--smoke-test"]
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(args)
    app.setApplicationName("AnimeMosaicStudio")
    app.setApplicationDisplayName("AnimeMosaicStudio")
    app.setOrganizationName("AnimeMosaicStudio")
    app.setStyle("Fusion")
    app.setFont(QFont(app_font_family(), 10))

    logger = setup_logging()
    settings = load_settings()
    ui_settings = QSettings("AnimeMosaicStudio", "AnimeMosaicStudio")
    mode = str(ui_settings.value("theme", "light"))
    if mode not in ("dark", "light"):
        mode = "light"

    theme = ThemeManager(app, mode)
    palette = theme.apply()
    app.setWindowIcon(branding.app_icon(palette))

    store = SettingsStore(settings, parent=app)
    window = MainWindow(store, theme, persist=not smoke_test)
    window.show()
    logger.info("AnimeMosaicStudio %s 启动，配置 %s", __version__, settings.comfy_url)
    if smoke_test:
        QTimer.singleShot(700, app.quit)
    return app.exec()
