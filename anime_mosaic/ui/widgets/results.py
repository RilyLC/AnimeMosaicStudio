"""Results table for the current run."""

from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QImageReader, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QStackedLayout,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ...core.events import ProcessRecord
from ..theme import Palette
from .base import ElidedLabel

HEADERS = ("文件", "状态", "区域", "耗时", "种子", "备注")


class ResultsModel(QAbstractTableModel):
    def __init__(self, palette: Palette | None = None, parent=None):
        super().__init__(parent)
        self._rows: list[ProcessRecord] = []
        self._palette = palette

    # ------------------------------------------------------------ Qt contract
    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(HEADERS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):  # noqa: N802
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return HEADERS[section]
        if role == Qt.TextAlignmentRole and orientation == Qt.Horizontal:
            alignment = Qt.AlignRight if section in (2, 3) else Qt.AlignLeft
            return int(alignment | Qt.AlignVCenter)
        return None

    def data(self, index: QModelIndex, role=Qt.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._rows)):
            return None
        record = self._rows[index.row()]
        column = index.column()

        if role == Qt.DisplayRole:
            if column == 0:
                return record.file
            if column == 1:
                return record.status_label
            if column == 2:
                return str(record.regions) if record.regions else "—"
            if column == 3:
                return f"{record.seconds:.1f}s" if record.seconds else "—"
            if column == 4:
                return record.seed or "—"
            return record.message or ""
        if role == Qt.ToolTipRole:
            return f"{record.file}\n{record.message}" if record.message else record.file
        if role == Qt.ForegroundRole:
            if column == 1:
                return QColor(self._status_color(record.status))
            if column == 0:
                return QColor(self._palette.text if self._palette else "#e2e8f0")
            return QColor(self._palette.muted if self._palette else "#94a3b8")
        if role == Qt.TextAlignmentRole and column in (2, 3):
            return int(Qt.AlignRight | Qt.AlignVCenter)
        if role == Qt.FontRole and column == 1:
            font = QFont()
            font.setBold(True)
            return font
        return None

    # ------------------------------------------------------------------ api
    def append(self, record: ProcessRecord) -> None:
        row = len(self._rows)
        self.beginInsertRows(QModelIndex(), row, row)
        self._rows.append(record)
        self.endInsertRows()

    def clear(self) -> None:
        self.beginResetModel()
        self._rows.clear()
        self.endResetModel()

    def set_palette(self, palette: Palette) -> None:
        self._palette = palette
        if self._rows:
            self.dataChanged.emit(
                self.index(0, 0),
                self.index(len(self._rows) - 1, len(HEADERS) - 1),
                [Qt.ForegroundRole],
            )

    def records(self) -> list[ProcessRecord]:
        return list(self._rows)

    def record_at(self, row: int) -> ProcessRecord | None:
        if 0 <= row < len(self._rows):
            return self._rows[row]
        return None

    def update_record(self, rel: str, record: ProcessRecord) -> None:
        for row, existing in enumerate(self._rows):
            if existing.file == rel:
                self._rows[row] = record
                self.dataChanged.emit(
                    self.index(row, 0),
                    self.index(row, len(HEADERS) - 1),
                )
                return

    def _status_color(self, status: str) -> str:
        palette = self._palette
        if palette is None:
            return "#94a3b8"
        return {
            "processed": palette.success,
            "copied": palette.info,
            "skipped": palette.muted,
            "error": palette.danger,
        }.get(status, palette.muted)


class ResultsPanel(QWidget):
    activated = Signal(object)

    def __init__(self, palette: Palette | None = None, parent=None):
        super().__init__(parent)
        self._palette = palette
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self._live = self._build_live()
        layout.addWidget(self._live)

        self._stack = QStackedLayout()
        layout.addLayout(self._stack)

        self._empty = self._build_empty()
        self._stack.addWidget(self._empty)

        self.model = ResultsModel(palette)
        self.view = QTableView()
        self.view.setModel(self.model)
        self.view.setAlternatingRowColors(True)
        self.view.setShowGrid(False)
        self.view.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.view.setSelectionMode(QAbstractItemView.SingleSelection)
        self.view.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.view.setWordWrap(False)
        self.view.verticalHeader().setVisible(False)
        self.view.verticalHeader().setDefaultSectionSize(34)
        self.view.horizontalHeader().setHighlightSections(False)
        self.view.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.view.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.view.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
        self.view.setFrameShape(QTableView.NoFrame)
        self._stack.addWidget(self.view)

        self.model.rowsInserted.connect(lambda *_: self._stack.setCurrentIndex(1))
        self.view.doubleClicked.connect(self._activate)

    def _build_live(self) -> QFrame:
        live = QFrame()
        live.setObjectName("Inset")
        live.setVisible(False)
        row = QHBoxLayout(live)
        row.setContentsMargins(10, 8, 10, 8)
        row.setSpacing(10)
        self._live_thumb = QLabel()
        self._live_thumb.setFixedSize(112, 63)
        self._live_thumb.setStyleSheet("background: transparent;")
        row.addWidget(self._live_thumb)
        texts = QVBoxLayout()
        texts.setSpacing(1)
        self._live_title = QLabel("正在处理")
        self._live_title.setObjectName("FormLabel")
        self._live_file = ElidedLabel("")
        self._live_file.setObjectName("Caption")
        self._live_stage = QLabel("")
        self._live_stage.setObjectName("Caption")
        texts.addWidget(self._live_title)
        texts.addWidget(self._live_file)
        texts.addWidget(self._live_stage)
        row.addLayout(texts, 1)
        self._live_hint = QLabel("实时显示当前输入图")
        self._live_hint.setObjectName("Caption")
        row.addWidget(self._live_hint, 0, Qt.AlignBottom)
        return live

    def _activate(self, index) -> None:
        record = self.model.record_at(index.row())
        if record is not None:
            self.activated.emit(record)

    def _build_empty(self) -> QWidget:
        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(6)
        label = QLabel("还没有处理记录")
        label.setObjectName("CardTitle")
        label.setAlignment(Qt.AlignCenter)
        hint = QLabel("开始处理后，每张图片的状态、耗时与种子会显示在这里。")
        hint.setObjectName("Caption")
        hint.setAlignment(Qt.AlignCenter)
        hint.setWordWrap(True)
        layout.addWidget(label)
        layout.addWidget(hint)
        return wrapper

    def append(self, record: ProcessRecord) -> None:
        self.model.append(record)

    def set_processing(self, rel: str, stage: str = "", image_path: str = "") -> None:
        """Show a compact live bar for the image currently being processed."""
        self._live_file.setText(rel)
        self._live_stage.setText(stage or "正在处理…")
        self._live.setVisible(True)
        if image_path:
            reader = QImageReader(image_path)
            reader.setAutoTransform(True)
            size = reader.size()
            if size.isValid() and size.width() > 0 and size.height() > 0:
                reader.setScaledSize(
                    QSize(
                        max(1, int(size.width() * min(240 / size.width(), 136 / size.height(), 1.0))),
                        max(1, int(size.height() * min(240 / size.width(), 136 / size.height(), 1.0))),
                    )
                )
            image = reader.read()
            if not image.isNull():
                self._live_thumb.setPixmap(QPixmap.fromImage(image))

    def clear_processing(self) -> None:
        self._live.setVisible(False)
        self._live_thumb.clear()
        self._live_file.setText("")
        self._live_stage.setText("")

    def clear(self) -> None:
        self.model.clear()
        self.clear_processing()
        self._stack.setCurrentIndex(0)

    def update_record(self, rel: str, record: ProcessRecord) -> None:
        self.model.update_record(rel, record)

    def set_palette(self, palette: Palette) -> None:
        self._palette = palette
        self.model.set_palette(palette)
