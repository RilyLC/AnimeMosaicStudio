"""Vector icon set rendered from inline SVG (no asset files, no Qt SVG plugin).

Every icon is a 24x24 line glyph.  ``icon()`` returns a cached ``QIcon`` tinted
for the current palette; ``pixmap()`` is handy for custom-painted widgets.
"""

from __future__ import annotations

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

_ICONS: dict[str, str] = {
    "home": '<path d="M4 10.8 12 4l8 6.8V20a1 1 0 0 1-1 1h-5v-6h-4v6H5a1 1 0 0 1-1-1z"/>',
    "sliders": (
        '<path d="M4 7h9"/><path d="M17 7h3"/><circle cx="15" cy="7" r="2"/>'
        '<path d="M4 17h3"/><path d="M11 17h9"/><circle cx="9" cy="17" r="2"/>'
    ),
    "prompt": (
        '<path d="M21 15a2 2 0 0 1-2 2H8l-5 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>'
        '<path d="M7 8h10"/><path d="M7 12h6"/>'
    ),
    "settings": (
        '<path d="M4 6h7M15 6h5"/><circle cx="13" cy="6" r="2"/>'
        '<path d="M4 12h3M11 12h9"/><circle cx="9" cy="12" r="2"/>'
        '<path d="M4 18h9M17 18h3"/><circle cx="15" cy="18" r="2"/>'
    ),
    "logs": (
        '<path d="M6 3h9l4 4v14H6z"/><path d="M15 3v4h4"/>'
        '<path d="M9 11h6"/><path d="M9 15h6"/>'
    ),
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v6"/><path d="M12 8h.01"/>',
    "folder": (
        '<path d="M3 7.5A2.5 2.5 0 0 1 5.5 5H9l2 2h7.5A2.5 2.5 0 0 1 21 9.5v7'
        'A2.5 2.5 0 0 1 18.5 19h-13A2.5 2.5 0 0 1 3 16.5z"/>'
    ),
    "play": '<path d="M8 5.3v13.4L19 12z" fill="currentColor" stroke="none"/>',
    "stop": '<rect x="6" y="6" width="12" height="12" rx="2.5" fill="currentColor" stroke="none"/>',
    "check": '<path d="M4.5 12.5l5 5L20 6.5"/>',
    "check_circle": '<circle cx="12" cy="12" r="9"/><path d="M8 12.5l2.7 2.7L16 9"/>',
    "alert": '<path d="M12 3 2.8 19h18.4z"/><path d="M12 9v4.5"/><path d="M12 16.8h.01"/>',
    "alert_circle": '<circle cx="12" cy="12" r="9"/><path d="M12 7v6"/><path d="M12 16.5h.01"/>',
    "image": (
        '<rect x="3" y="4" width="18" height="16" rx="3"/>'
        '<circle cx="8.5" cy="9.5" r="1.6"/><path d="M21 16l-4.5-4.5L7 20"/>'
    ),
    "sparkles": (
        '<path d="M12 3l1.7 4.8 4.8 1.7-4.8 1.7L12 16l-1.7-4.8L5.5 9.5l4.8-1.7z"/>'
        '<path d="M18.5 15.5l.8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8z"/>'
    ),
    "refresh": '<path d="M20 11a8 8 0 1 0-2.4 6.3"/><path d="M20 4v7h-7"/>',
    "external": (
        '<path d="M14 4h6v6"/><path d="M20 4l-9 9"/>'
        '<path d="M19 14v4a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h4"/>'
    ),
    "sun": (
        '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4'
        'M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>'
    ),
    "moon": '<path d="M20.5 14.5A8.5 8.5 0 1 1 9.5 3.5a7 7 0 0 0 11 11z"/>',
    "zap": '<path d="M13 2 4 14h6l-1 8 9-12h-6z"/>',
    "gem": '<path d="M6 3h12l3 6-9 12L3 9z"/><path d="M3 9h18"/><path d="M9 3l3 18 3-18"/>',
    "gauge": '<path d="M4.5 18a9 9 0 1 1 15 0"/><path d="M12 13l3.5-3.5"/>',
    "copy": (
        '<rect x="9" y="9" width="11" height="11" rx="2"/>'
        '<path d="M5 15H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v1"/>'
    ),
    "trash": (
        '<path d="M4 7h16"/><path d="M9 7V4h6v3"/><path d="M6 7l1 13h10l1-13"/>'
        '<path d="M10 11v6M14 11v6"/>'
    ),
    "save": '<path d="M5 3h11l3 3v15H5z"/><path d="M8 3v6h8V3"/><path d="M8 15h8v6"/>',
    "chevron_down": '<path d="M6 9l6 6 6-6"/>',
    "chevron_left": '<path d="M15 6l-6 6 6 6"/>',
    "chevron_right": '<path d="M9 6l6 6-6 6"/>',
    "close": '<path d="M6 6l12 12M18 6L6 18"/>',
    "search": '<circle cx="11" cy="11" r="6.5"/><path d="M16 16l4.5 4.5"/>',
    "cpu": (
        '<rect x="6" y="6" width="12" height="12" rx="2"/>'
        '<path d="M9 2v3M15 2v3M9 19v3M15 19v3M2 9h3M2 15h3M19 9h3M19 15h3"/>'
    ),
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "layers": '<path d="M12 3 3 8l9 5 9-5z"/><path d="M3 13l9 5 9-5"/>',
    "wand": (
        '<path d="M4 20 16 8"/><path d="M14 4l1 3 3 1-3 1-1 3-1-3-3-1 3-1z"/>'
        '<path d="M19 12l.7 2 2 .7-2 .7-.7 2-.7-2-2-.7 2-.7z"/>'
    ),
    "filter": '<path d="M3 5h18l-7 8v6l-4 2v-8z"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "minus": '<path d="M5 12h14"/>',
    "arrow_down": '<path d="M12 4v14"/><path d="M6 12l6 6 6-6"/>',
    "arrow_up": '<path d="M12 20V6"/><path d="M6 12l6-6 6 6"/>',
    "history": (
        '<path d="M3 12a9 9 0 1 0 3-6.7"/><path d="M3 4v5h5"/><path d="M12 7v5l3 2"/>'
    ),
    "undo": '<path d="M9 14 4 9l5-5"/><path d="M4 9h9a6 6 0 0 1 0 12h-3"/>',
    "redo": '<path d="M15 14l5-5-5-5"/><path d="M20 9h-9a6 6 0 0 0 0 12h3"/>',
    "brush": (
        '<path d="M14.5 4.5 20 10l-8 8H6v-6z"/><path d="M5 21c2 0 3-1 3-3"/>'
    ),
    "eraser": (
        '<path d="M8 20h12"/><path d="M14 5l5 5-7 7H7l-3-3z"/><path d="M10 9l5 5"/>'
    ),
    "shield": '<path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/>',
    "power": '<path d="M12 3v9"/><path d="M6.5 6.5a8 8 0 1 0 11 0"/>',
    "grid": (
        '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/>'
        '<rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>'
    ),
    "scan": (
        '<path d="M4 8V5a1 1 0 0 1 1-1h3M16 4h3a1 1 0 0 1 1 1v3'
        'M20 16v3a1 1 0 0 1-1 1h-3M8 20H5a1 1 0 0 1-1-1v-3"/>'
        '<path d="M4 12h16"/>'
    ),
}

_CACHE: dict[tuple[str, str, int], QIcon] = {}
_PIXMAP_CACHE: dict[tuple[str, str, int], QPixmap] = {}


def available() -> tuple[str, ...]:
    return tuple(_ICONS)


def pixmap(name: str, color: str, size: int = 20) -> QPixmap:
    key = (name, color, size)
    cached = _PIXMAP_CACHE.get(key)
    if cached is not None:
        return cached
    markup = _ICONS.get(name)
    if markup is None:
        markup = '<circle cx="12" cy="12" r="8"/>'
    markup = markup.replace("currentColor", color)
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
        f'viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="1.7" '
        f'stroke-linecap="round" stroke-linejoin="round">{markup}</svg>'
    )
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    scale = 2
    output = QPixmap(size * scale, size * scale)
    output.fill(Qt.transparent)
    output.setDevicePixelRatio(scale)
    painter = QPainter(output)
    painter.setRenderHint(QPainter.Antialiasing, True)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()
    _PIXMAP_CACHE[key] = output
    return output


def icon(name: str, color: str, size: int = 20) -> QIcon:
    key = (name, color, size)
    cached = _CACHE.get(key)
    if cached is not None:
        return cached
    result = QIcon(pixmap(name, color, size))
    _CACHE[key] = result
    return result


def icon_size(size: int = 20) -> QSize:
    return QSize(size, size)
