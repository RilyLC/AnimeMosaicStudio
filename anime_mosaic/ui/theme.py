"""Design tokens and the generated Qt stylesheet.

Two palettes (dark / light) share one QSS template.  Widgets only use object
names and dynamic properties, never hard-coded colours, so a theme switch is a
single ``setStyleSheet`` call.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import asdict, dataclass
from string import Template

from PySide6.QtCore import QByteArray, QObject, QRectF, Qt, Signal
from PySide6.QtGui import QImage, QPainter
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication


@dataclass(frozen=True)
class Palette:
    name: str
    bg: str
    bg_alt: str
    surface: str
    surface_2: str
    surface_3: str
    border: str
    border_strong: str
    text: str
    muted: str
    dim: str
    accent: str
    accent_hover: str
    accent_pressed: str
    accent_soft: str
    accent_2: str
    on_accent: str
    success: str
    success_soft: str
    warning: str
    warning_soft: str
    danger: str
    danger_soft: str
    info: str
    info_soft: str
    log_debug: str
    log_warn: str
    log_error: str
    log_success: str


DARK = Palette(
    name="dark",
    bg="#0B0F14",
    bg_alt="#0E141B",
    surface="#121A24",
    surface_2="#17212D",
    surface_3="#1F2B3A",
    border="#22303F",
    border_strong="#2F4155",
    text="#E7EEF7",
    muted="#91A1B5",
    dim="#5F7085",
    accent="#6D8DFF",
    accent_hover="#87A2FF",
    accent_pressed="#5A78E6",
    accent_soft="rgba(109, 141, 255, 0.16)",
    accent_2="#39D2C0",
    on_accent="#FFFFFF",
    success="#3DDC97",
    success_soft="rgba(61, 220, 151, 0.14)",
    warning="#F4B860",
    warning_soft="rgba(244, 184, 96, 0.14)",
    danger="#FF7A8A",
    danger_soft="rgba(255, 122, 138, 0.14)",
    info="#6CC5FF",
    info_soft="rgba(108, 197, 255, 0.14)",
    log_debug="#6B7C93",
    log_warn="#F4B860",
    log_error="#FF7A8A",
    log_success="#3DDC97",
)

LIGHT = Palette(
    name="light",
    bg="#F3F5F9",
    bg_alt="#FFFFFF",
    surface="#FFFFFF",
    surface_2="#F6F8FB",
    surface_3="#E9EEF5",
    border="#E1E7F0",
    border_strong="#C9D4E2",
    text="#17202E",
    muted="#5F6E83",
    dim="#93A1B4",
    accent="#4F6DF5",
    accent_hover="#6A84FF",
    accent_pressed="#3E57D8",
    accent_soft="rgba(79, 109, 245, 0.10)",
    accent_2="#14B8A6",
    on_accent="#FFFFFF",
    success="#0E9F6E",
    success_soft="rgba(14, 159, 110, 0.10)",
    warning="#B7791F",
    warning_soft="rgba(183, 121, 31, 0.10)",
    danger="#D6455D",
    danger_soft="rgba(214, 69, 93, 0.10)",
    info="#1D7ED6",
    info_soft="rgba(29, 126, 214, 0.10)",
    log_debug="#8492A6",
    log_warn="#B7791F",
    log_error="#D6455D",
    log_success="#0E9F6E",
)

PALETTES = {"dark": DARK, "light": LIGHT}

QSS_TEMPLATE = Template(
    """
* { outline: none; }
QWidget {
    color: $text;
    font-size: 13px;
}
QMainWindow, QWidget#Root { background: $bg; }
QDialog { background: $bg; }
QToolTip {
    background: $surface_2; color: $text;
    border: 1px solid $border_strong; border-radius: 8px;
    padding: 7px 9px; font-size: 12px;
}
QFrame#Sidebar { background: $bg_alt; border-right: 1px solid $border; }
QFrame#Header { background: transparent; }
QFrame#ActionBar { background: $bg_alt; border-top: 1px solid $border; }
QFrame#Card {
    background: $surface;
    border: 1px solid $border;
    border-radius: 16px;
}
QFrame#Inset {
    background: $bg;
    border: 1px solid $border;
    border-radius: 12px;
}
QFrame#Inset[tone="accent"] { background: $accent_soft; border-color: $accent; }
QFrame#Inset[tone="success"] { background: $success_soft; border-color: $success; }
QFrame#Inset[tone="warning"] { background: $warning_soft; border-color: $warning; }
QFrame#Inset[tone="info"] { background: $info_soft; border-color: $info; }
QFrame#Inset[tone="plain"] { background: $surface; border-color: $border; }
QFrame#Toast {
    background: $surface_2;
    border: 1px solid $border_strong;
    border-radius: 12px;
}
QFrame#DropZone {
    background: $bg;
    border: 1px dashed $border_strong;
    border-radius: 12px;
}
QFrame#DropZone[tone="accent"] { background: $accent_soft; border: 1px dashed $accent; }
QFrame#DropZone[tone="success"] { background: $success_soft; border: 1px dashed $success; }
QFrame#DropZone[tone="warning"] { background: $warning_soft; border: 1px dashed $warning; }
QFrame#DropZone[tone="info"] { background: $info_soft; border: 1px dashed $info; }
QFrame#DropZone[tone="plain"] { background: $surface; border: 1px dashed $border_strong; }
QFrame#DropZone[active="true"] {
    background: $accent_soft;
    border: 1px dashed $accent;
}
QFrame#Divider { background: $border; max-height: 1px; min-height: 1px; border: none; }
QFrame#Segment {
    background: $bg;
    border: 1px solid $border;
    border-radius: 12px;
}
QFrame#PresetCard {
    background: $bg;
    border: 1px solid $border;
    border-radius: 12px;
}
QFrame#PresetCard:hover { border-color: $border_strong; }
QFrame#PresetCard[selected="true"] {
    background: $accent_soft;
    border: 1px solid $accent;
}

QScrollArea { background: transparent; border: none; }
QScrollArea > QWidget > QWidget { background: transparent; }
QWidget#ScrollBody { background: transparent; }

QLabel { background: transparent; }
QLabel#PageTitle { font-size: 24px; font-weight: 700; }
QLabel#PageSubtitle { color: $muted; font-size: 13px; }
QLabel#CardTitle { font-size: 15px; font-weight: 600; }
QLabel#CardHint { color: $muted; font-size: 12px; }
QLabel#Caption { color: $muted; font-size: 12px; }
QLabel#Dim { color: $dim; font-size: 12px; }
QLabel#StatValue { font-size: 26px; font-weight: 700; }
QLabel#StatValueSmall { font-size: 20px; font-weight: 700; }
QLabel#StatCaption { color: $muted; font-size: 12px; }
QLabel#Mono { font-family: "Cascadia Code", "Consolas", monospace; font-size: 12px; color: $muted; }
QLabel#FormLabel { color: $text; font-size: 13px; }
QLabel#FormHelp { color: $muted; font-size: 11.5px; }
QLabel#StepNumber {
    background: $accent_soft; color: $accent;
    border-radius: 12px; font-weight: 700; font-size: 13px;
}
QLabel#BrandName { font-size: 16px; font-weight: 700; letter-spacing: 0.3px; }
QLabel#BrandSub { color: $dim; font-size: 9px; font-weight: 700; letter-spacing: 2.2px; }
QLabel#NavSection { color: $dim; font-size: 10px; font-weight: 700; letter-spacing: 1.4px; }
QLabel#Badge {
    background: $surface_3; color: $muted;
    border-radius: 9px; padding: 3px 9px;
    font-size: 11px; font-weight: 600;
}
QLabel#Badge[tone="accent"] { background: $accent_soft; color: $accent; }
QLabel#Badge[tone="ok"] { background: $success_soft; color: $success; }
QLabel#Badge[tone="warn"] { background: $warning_soft; color: $warning; }
QLabel#Badge[tone="danger"] { background: $danger_soft; color: $danger; }
QLabel#Badge[tone="info"] { background: rgba(108, 197, 255, 0.14); color: $info; }
QLabel#StatusChip {
    background: $surface_2; border: 1px solid $border;
    border-radius: 14px; padding: 5px 12px;
    color: $muted; font-size: 12px; font-weight: 600;
}
QLabel#StatusChip[state="checking"] { color: $warning; border-color: $warning_soft; background: $warning_soft; }
QLabel#StatusChip[state="ok"] { color: $success; border-color: $success_soft; background: $success_soft; }
QLabel#StatusChip[state="error"] { color: $danger; border-color: $danger_soft; background: $danger_soft; }

QPushButton {
    background: transparent;
    border: 1px solid transparent;
    border-radius: 10px;
    padding: 8px 14px;
    color: $text;
    font-size: 13px;
}
QPushButton:hover { background: $surface_2; }
QPushButton:pressed { background: $surface_3; }
QPushButton:disabled { color: $dim; background: transparent; }
QPushButton[variant="primary"] {
    background: $accent; color: $on_accent; font-weight: 600;
}
QPushButton[variant="primary"]:hover { background: $accent_hover; }
QPushButton[variant="primary"]:pressed { background: $accent_pressed; }
QPushButton[variant="primary"]:disabled { background: $surface_3; color: $dim; }
QPushButton[variant="secondary"] {
    background: $surface_2; border-color: $border; color: $text;
}
QPushButton[variant="secondary"]:hover { background: $surface_3; border-color: $border_strong; }
QPushButton[variant="ghost"] { color: $muted; }
QPushButton[variant="ghost"]:hover { color: $text; background: $surface_2; }
QPushButton[variant="danger"] {
    color: $danger; border-color: $danger_soft; background: transparent;
}
QPushButton[variant="danger"]:hover { background: $danger_soft; }
QPushButton[variant="danger"]:disabled { color: $dim; border-color: $border; }
QPushButton[variant="link"] { color: $accent; padding: 2px 4px; background: transparent; }
QPushButton[variant="link"]:hover { color: $accent_hover; background: transparent; }
QPushButton[size="lg"] { padding: 12px 22px; font-size: 14px; border-radius: 12px; }
QPushButton[size="sm"] { padding: 5px 10px; font-size: 12px; border-radius: 8px; }
QPushButton#NavButton {
    text-align: left; padding: 10px 12px;
    border-radius: 10px; color: $muted; font-size: 13px;
}
QPushButton#NavButton:hover { background: $surface_2; color: $text; }
QPushButton#NavButton:checked { background: $accent_soft; color: $accent; font-weight: 600; }
QPushButton#IconButton { padding: 6px; border-radius: 9px; color: $muted; }
QPushButton#IconButton:hover { background: $surface_2; color: $text; }
QPushButton#SegmentButton {
    border-radius: 9px; padding: 6px 16px;
    color: $muted; background: transparent; font-size: 12.5px;
}
QPushButton#SegmentButton:hover { color: $text; }
QPushButton#SegmentButton:checked {
    background: $surface; color: $text; font-weight: 600;
    border: 1px solid $border;
}

QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background: $bg;
    border: 1px solid $border;
    border-radius: 10px;
    padding: 8px 10px;
    color: $text;
    selection-background-color: $accent;
    selection-color: $on_accent;
}
QLineEdit:hover, QPlainTextEdit:hover, QTextEdit:hover, QSpinBox:hover,
QDoubleSpinBox:hover, QComboBox:hover { border-color: $border_strong; }
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QSpinBox:focus,
QDoubleSpinBox:focus, QComboBox:focus { border-color: $accent; }
QLineEdit:disabled, QPlainTextEdit:disabled, QSpinBox:disabled, QComboBox:disabled { color: $dim; }
QSpinBox QLineEdit, QDoubleSpinBox QLineEdit {
    background: transparent;
    border: none;
    border-radius: 0;
    padding: 0px;
    color: $text;
}
QComboBox QLineEdit {
    background: transparent;
    border: none;
    border-radius: 0;
    padding: 0px;
    color: $text;
}
QComboBox::drop-down { border: none; width: 24px; }
QComboBox::down-arrow { image: url("$chevron"); width: 10px; height: 10px; }
QComboBox QAbstractItemView {
    background: $surface_2;
    border: 1px solid $border_strong;
    border-radius: 10px;
    padding: 4px;
    selection-background-color: $accent_soft;
    selection-color: $text;
}
QPlainTextEdit#PromptEditor {
    font-family: "Cascadia Code", "Consolas", monospace;
    font-size: 12.5px;
    padding: 12px;
}
QPlainTextEdit#LogView {
    font-family: "Cascadia Code", "Consolas", monospace;
    font-size: 12.5px;
    background: transparent;
    border: none;
    padding: 4px 2px;
}
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button { width: 0; height: 0; border: none; }

QCheckBox { spacing: 8px; color: $text; font-size: 12.5px; }
QCheckBox::indicator {
    width: 18px; height: 18px; border-radius: 5px;
    border: 1px solid $border_strong; background: $bg;
}
QCheckBox::indicator:hover { border-color: $accent; }
QCheckBox::indicator:checked {
    background: $accent; border-color: $accent; image: url("$check");
}

QSlider::groove:horizontal { height: 6px; background: $surface_3; border-radius: 3px; }
QSlider::sub-page:horizontal { background: $accent; border-radius: 3px; }
QSlider::handle:horizontal {
    width: 14px; height: 14px; margin: -5px 0;
    border-radius: 7px; background: $surface; border: 3px solid $accent;
}
QSlider::handle:horizontal:hover { border-color: $accent_hover; }
QSlider::handle:horizontal:pressed { background: $accent; }

QProgressBar {
    background: $surface_3; border: none; border-radius: 4px;
    min-height: 8px; max-height: 8px; text-align: center; color: transparent;
}
QProgressBar::chunk {
    border-radius: 4px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 $accent, stop:1 $accent_2);
}

QTabWidget::pane { border: none; background: transparent; }
QTabBar::tab {
    background: transparent; color: $muted;
    padding: 7px 12px; margin-right: 4px; border-radius: 8px; font-size: 12.5px;
}
QTabBar::tab:hover { color: $text; background: $surface_2; }
QTabBar::tab:selected { color: $text; background: $surface_2; font-weight: 600; }

QTableView {
    background: transparent; border: none; gridline-color: transparent;
    selection-background-color: $accent_soft; selection-color: $text;
    alternate-background-color: $bg;
    font-size: 12px;
}
QHeaderView { background: transparent; border: none; }
QHeaderView::section {
    background: transparent; color: $muted; border: none;
    border-bottom: 1px solid $border; padding: 8px 10px;
    font-size: 11.5px; font-weight: 600;
}
QTableCornerButton::section { background: transparent; border: none; }
QTableView::item { padding: 6px 10px; border-bottom: 1px solid $border; }
QTableView::item:selected { background: $accent_soft; }

QListWidget#OutputGallery {
    background: transparent; border: none; outline: none; padding: 2px;
}
QListWidget#OutputGallery::item {
    background: $surface_2; border: 1px solid $border; border-radius: 10px;
    padding: 8px; margin: 4px; color: $text;
}
QListWidget#OutputGallery::item:hover {
    background: $surface_3; border-color: $border_strong;
}
QListWidget#OutputGallery::item:selected {
    background: $accent_soft; border-color: $accent; color: $text;
}

QTreeWidget#ReuseTree {
    background: transparent; border: 1px solid $border; border-radius: 10px;
    padding: 4px; outline: none; alternate-background-color: $surface_2;
    font-size: 12px;
}
QTreeWidget#ReuseTree::item {
    padding: 6px 6px; border-radius: 5px;
}
QTreeWidget#ReuseTree::item:hover { background: $surface_3; }
QTreeWidget#ReuseTree::item:selected {
    background: $accent_soft; color: $text;
}
QTreeWidget#ReuseTree::branch { background: transparent; }
QTreeWidget#ReuseTree::indicator {
    width: 16px; height: 16px; border-radius: 4px;
    border: 1px solid $border_strong; background: $bg;
}
QTreeWidget#ReuseTree::indicator:hover { border-color: $accent; }
QTreeWidget#ReuseTree::indicator:checked {
    background: $accent; border-color: $accent; image: url("$check");
}
QTreeWidget#ReuseTree::indicator:indeterminate {
    background: $accent; border-color: $accent; image: url("$dash");
}

QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: $surface_3; border-radius: 4px; min-height: 32px; }
QScrollBar::handle:vertical:hover { background: $border_strong; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle:horizontal { background: $surface_3; border-radius: 4px; min-width: 32px; }
QScrollBar::handle:horizontal:hover { background: $border_strong; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

QSplitter::handle { background: transparent; }
QSplitter::handle:horizontal { width: 12px; }
QSplitter::handle:vertical { height: 12px; }

QMenu { background: $surface_2; border: 1px solid $border_strong; border-radius: 10px; padding: 6px; }
QMenu::item { padding: 7px 18px; border-radius: 6px; }
QMenu::item:selected { background: $accent_soft; color: $text; }

QMessageBox { background: $surface; }
QFileDialog { background: $bg; }
"""
)


class ThemeManager(QObject):
    """Applies a palette to the QApplication and caches small QSS assets."""

    changed = Signal(str)

    def __init__(self, app: QApplication, mode: str = "dark"):
        super().__init__(app)
        self._app = app
        self._mode = mode if mode in PALETTES else "dark"

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def palette(self) -> Palette:
        return PALETTES[self._mode]

    def apply(self, mode: str | None = None) -> Palette:
        if mode:
            self._mode = mode if mode in PALETTES else "dark"
        palette = self.palette
        assets = ensure_assets(palette)
        qss = QSS_TEMPLATE.substitute(**asdict(palette), **assets)
        self._app.setStyleSheet(qss)
        self.changed.emit(self._mode)
        return palette

    def toggle(self) -> str:
        return "light" if self._mode == "dark" else "dark"


def _asset_cache_dir() -> str:
    """Cache folder next to this module; QSS needs real files on disk."""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cache")


def ensure_assets(palette: Palette) -> dict[str, str]:
    """Render the small images QSS needs (chevron, check, dash), keyed by colour."""
    cache_dir = _asset_cache_dir()
    try:
        os.makedirs(cache_dir, exist_ok=True)
    except OSError:
        cache_dir = tempfile.mkdtemp(prefix="ams_ui_")
    assets = {
        "chevron": (palette.muted, '<path d="M6 9.5l6 6 6-6" stroke="{c}" stroke-width="2" fill="none"/>'),
        "check": (palette.on_accent, '<path d="M5 12.5l4.5 4.5L19 7" stroke="{c}" stroke-width="2.6" fill="none"/>'),
        "dash": (palette.on_accent, '<path d="M6 12h12" stroke="{c}" stroke-width="2.6" fill="none"/>'),
    }
    paths: dict[str, str] = {}
    for name, (color, markup) in assets.items():
        path = os.path.join(cache_dir, f"{name}_{color.lstrip('#')}_v2.png")
        if not os.path.isfile(path):
            _render_png(markup.format(c=color), path)
        paths[name] = path.replace("\\", "/")
    return paths


def _render_png(markup: str, path: str) -> None:
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" '
        'viewBox="0 0 24 24">' + markup + "</svg>"
    )
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    image = QImage(40, 40, QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing, True)
    renderer.render(painter, QRectF(0, 0, 40, 40))
    painter.end()
    image.save(path)


def app_font_family() -> str:
    from PySide6.QtGui import QFontDatabase

    families = set(QFontDatabase.families())
    for candidate in ("Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC", "Segoe UI"):
        if candidate in families:
            return candidate
    return "Segoe UI"


def mono_font_family() -> str:
    from PySide6.QtGui import QFontDatabase

    families = set(QFontDatabase.families())
    for candidate in ("Cascadia Code", "JetBrains Mono", "Consolas"):
        if candidate in families:
            return candidate
    return "Consolas"
