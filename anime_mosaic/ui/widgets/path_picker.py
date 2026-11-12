"""Large folder pickers for the workspace, with drag & drop support."""

from __future__ import annotations

from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from ..theme import Palette
from .base import Badge, ElidedLabel, IconTile, repolish
from .buttons import Button


class _ElidedPathEdit(QLineEdit):
    """QLineEdit that middle-elides long paths while it is not focused."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._full_text = ""

    def full_text(self) -> str:
        return self._full_text

    def note_user_text(self, text: str) -> None:
        self._full_text = text or ""
        self.setToolTip(self._full_text)

    def set_full_text(self, text: str) -> None:
        text = text or ""
        self._full_text = text
        self.setToolTip(text)
        if self.hasFocus():
            with QSignalBlocker(self):
                super().setText(text)
            return
        self._render_elided()

    def _render_elided(self) -> None:
        if self.hasFocus():
            return
        available = max(
            28,
            self.width()
            - self.textMargins().left()
            - self.textMargins().right()
            - 10,
        )
        shown = self.fontMetrics().elidedText(
            self._full_text, Qt.ElideMiddle, available
        )
        with QSignalBlocker(self):
            super().setText(shown)

    def focusInEvent(self, event):  # noqa: N802 - Qt naming
        with QSignalBlocker(self):
            super().setText(self._full_text)
        super().focusInEvent(event)
        self.setCursorPosition(len(self._full_text))

    def focusOutEvent(self, event):  # noqa: N802 - Qt naming
        self._full_text = self.text()
        super().focusOutEvent(event)
        self._render_elided()

    def resizeEvent(self, event):  # noqa: N802 - Qt naming
        super().resizeEvent(event)
        self._render_elided()


class PathPicker(QFrame):
    pathChanged = Signal(str)

    def __init__(
        self,
        title: str,
        hint: str,
        placeholder: str,
        palette: Palette,
        icon: str = "folder",
        header_extra: QWidget | None = None,
        compact: bool = False,
        tone: str = "neutral",
        parent=None,
    ):
        super().__init__(parent)
        self.setObjectName("DropZone")
        self.setProperty("tone", tone)
        self.setAcceptDrops(True)
        self._palette = palette
        self._active = False
        self._compact = compact

        root = QVBoxLayout(self)
        if compact:
            root.setContentsMargins(14, 10, 14, 10)
            root.setSpacing(8)
        else:
            root.setContentsMargins(18, 16, 18, 16)
            root.setSpacing(12)

        header = QHBoxLayout()
        header.setSpacing(8 if compact else 11)
        self._icon = IconTile(
            icon, palette, 28 if compact else 36, tone=tone
        )
        header.addWidget(self._icon, 0, Qt.AlignTop)
        labels = QVBoxLayout()
        labels.setSpacing(1)
        title_label = QLabel(title)
        title_label.setObjectName("CardTitle")
        hint_label = ElidedLabel(hint)
        hint_label.setObjectName("CardHint")
        labels.addWidget(title_label)
        labels.addWidget(hint_label)
        header.addLayout(labels, 1)
        if header_extra is not None:
            header.addWidget(header_extra, 0, Qt.AlignTop)
        self._status = Badge("未选择", "neutral")
        header.addWidget(self._status, 0, Qt.AlignTop)
        root.addLayout(header)

        row = QHBoxLayout()
        row.setSpacing(8)
        self._edit = _ElidedPathEdit()
        self._edit.setPlaceholderText(placeholder)
        self._edit.setMinimumHeight(34 if compact else 38)
        self._edit.editingFinished.connect(self._on_edited)
        row.addWidget(self._edit, 1)
        browse = Button("浏览", "secondary", "folder", palette, size="sm")
        browse.setMinimumHeight(34 if compact else 38)
        browse.clicked.connect(self._browse)
        row.addWidget(browse, 0)
        root.addLayout(row)

        self._edit.textEdited.connect(self._edit.note_user_text)
        self._edit.textChanged.connect(self._on_text)

    # ------------------------------------------------------------------ api
    def path(self) -> str:
        return self._edit.full_text().strip()

    def set_path(self, path: str) -> None:
        if self._edit.full_text() != (path or ""):
            self._edit.set_full_text(path or "")

    def set_status(self, text: str, tone: str = "neutral") -> None:
        self._status.setText(text)
        self._status.set_tone(tone)

    def set_palette(self, palette: Palette) -> None:
        self._palette = palette
        self._icon.set_palette(palette)

    # -------------------------------------------------------------- events
    def _on_text(self, _text: str) -> None:
        self.pathChanged.emit(self.path())

    def _on_edited(self) -> None:
        self.pathChanged.emit(self.path())

    def _browse(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "选择文件夹", self.path())
        if selected:
            self.set_path(selected)
            self.pathChanged.emit(selected)

    def dragEnterEvent(self, event):  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self._set_active(True)

    def dragLeaveEvent(self, event):  # noqa: N802
        self._set_active(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event):  # noqa: N802
        self._set_active(False)
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path:
                self.set_path(path)
                self.pathChanged.emit(path)
                event.acceptProposedAction()
                return
        super().dropEvent(event)

    def _set_active(self, active: bool) -> None:
        if self._active == active:
            return
        self._active = active
        self.setProperty("active", "true" if active else "false")
        repolish(self)
