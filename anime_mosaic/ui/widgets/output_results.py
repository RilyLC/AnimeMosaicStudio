"""Directory-based output gallery for the workspace output-results tab."""

from __future__ import annotations

import datetime as _dt

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QIcon, QImageReader, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListView,
    QListWidget,
    QListWidgetItem,
    QStackedLayout,
    QVBoxLayout,
    QWidget,
)

from ...services.output_index import OutputEntry, human_size
from .. import icons
from ..theme import Palette
from .base import ElidedLabel
from .buttons import Button
from .segmented import SegmentedControl

THUMB_W = 384
THUMB_H = 240
FILTER_ALL = 0
FILTER_PROCESSED = 1
FILTER_REUSED = 2
FILTER_UNPROCESSED = 3


class OutputResultsPanel(QWidget):
    """A thumbnail gallery of input/output pairs used inside the workspace tabs."""

    compareRequested = Signal(object)
    refreshRequested = Signal()

    def __init__(self, palette: Palette, parent=None):
        super().__init__(parent)
        self._palette = palette
        self._entries: list[OutputEntry] = []
        self._items: dict[str, QListWidgetItem] = {}
        self._thumb_loaded: set[str] = set()
        self._thumb_queued: set[str] = set()
        self._thumb_queue: list[OutputEntry] = []
        self._thumb_token = 0
        self._total_input = 0
        self._loading = False
        self._filter_index = FILTER_ALL
        self._dir: str | None = None

        self._thumb_timer = QTimer(self)
        self._thumb_timer.setSingleShot(True)
        self._thumb_timer.timeout.connect(self._load_thumb_batch)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)
        self._summary = ElidedLabel("尚未扫描")
        self._summary.setObjectName("Caption")
        toolbar.addWidget(self._summary, 1)
        self._filter = SegmentedControl(["全部", "已处理", "复用", "未处理"], palette)
        self._filter.setToolTip(
            "未处理 = 原图复制；已处理 = 已生成马赛克；复用 = 差分复用生成"
        )
        self._filter.currentChanged.connect(self.set_filter)
        toolbar.addWidget(self._filter)
        self._dir_filter = QComboBox(self)
        self._dir_filter.setObjectName("DirFilter")
        self._dir_filter.setMinimumWidth(104)
        self._dir_filter.setMaximumWidth(220)
        self._dir_filter.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self._dir_filter.setToolTip("按输出子目录筛选查看")
        self._dir_filter.currentIndexChanged.connect(self._on_dir_changed)
        self._dir_filter.setVisible(False)
        toolbar.addWidget(self._dir_filter)
        self._refresh = Button("刷新", "ghost", "refresh", palette, size="sm")
        self._refresh.clicked.connect(self.refreshRequested.emit)
        toolbar.addWidget(self._refresh)
        self._compare = Button("对比选中", "primary", "image", palette, size="sm")
        self._compare.setEnabled(False)
        self._compare.clicked.connect(self._emit_compare)
        toolbar.addWidget(self._compare)
        root.addLayout(toolbar)

        self._stack = QStackedLayout()
        self._stack.setContentsMargins(0, 0, 0, 0)

        empty = QWidget()
        empty_layout = QVBoxLayout(empty)
        empty_layout.setAlignment(Qt.AlignCenter)
        empty_layout.setSpacing(6)
        self._empty_icon = QLabel()
        self._empty_icon.setPixmap(icons.pixmap("image", palette.dim, 30))
        self._empty_icon.setAlignment(Qt.AlignCenter)
        self._empty_text = QLabel("处理完成后，输出会按目录结构出现在这里")
        self._empty_text.setObjectName("Caption")
        self._empty_text.setAlignment(Qt.AlignCenter)
        empty_layout.addWidget(self._empty_icon)
        empty_layout.addWidget(self._empty_text)
        self._stack.addWidget(empty)

        self.view = QListWidget()
        self.view.setObjectName("OutputGallery")
        self.view.setViewMode(QListView.IconMode)
        self.view.setFlow(QListView.LeftToRight)
        self.view.setWrapping(True)
        self.view.setResizeMode(QListView.Adjust)
        self.view.setMovement(QListView.Static)
        self.view.setUniformItemSizes(True)
        self.view.setLayoutMode(QListView.Batched)
        self.view.setBatchSize(64)
        self.view.setGridSize(QSize(216, 190))
        self.view.setIconSize(QSize(192, 120))
        self.view.setSpacing(6)
        self.view.setWordWrap(True)
        self.view.setTextElideMode(Qt.ElideMiddle)
        self.view.setSelectionMode(QAbstractItemView.SingleSelection)
        self.view.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.view.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.view.itemDoubleClicked.connect(self._on_activated)
        self.view.currentItemChanged.connect(self._on_current)
        self._stack.addWidget(self.view)
        self._stack.setCurrentIndex(0)

        host = QWidget()
        host.setLayout(self._stack)
        root.addWidget(host, 1)

    # ------------------------------------------------------------------ api
    def set_palette(self, palette: Palette) -> None:
        self._palette = palette
        self._empty_icon.setPixmap(icons.pixmap("image", palette.dim, 30))
        for button in (self._refresh, self._compare):
            button.set_palette(palette)
        for entry in self._entries:
            if entry.rel not in self._thumb_loaded:
                item = self._items.get(entry.rel)
                if item is not None:
                    item.setIcon(self._placeholder_icon())

    def set_loading(self, loading: bool) -> None:
        self._loading = loading
        if loading:
            self._summary.setText("正在扫描输入与输出目录…")
        else:
            self._sync_view()

    def set_entries(self, entries: list[OutputEntry], total_input: int) -> None:
        self._total_input = max(0, total_input)
        self._entries = sorted(entries, key=lambda entry: entry.rel.lower())
        self._sync_dirs()
        self._rebuild()

    def upsert(self, entry: OutputEntry) -> None:
        for position, existing in enumerate(self._entries):
            if existing.rel == entry.rel:
                self._entries[position] = entry
                item = self._items.get(entry.rel)
                if item is not None:
                    self._configure_item(item, entry)
                    item.setHidden(not self._passes(entry))
                    self._thumb_loaded.discard(entry.rel)
                    self._thumb_queued.discard(entry.rel)
                    item.setIcon(self._placeholder_icon())
                    if self._passes(entry):
                        self._queue_thumbs([entry])
                self._sync_view(select_rel=entry.rel if self._passes(entry) else "")
                return

        position = 0
        key = entry.rel.lower()
        while position < len(self._entries) and self._entries[position].rel.lower() < key:
            position += 1
        self._entries.insert(position, entry)
        self._sync_dirs()
        item = self._make_item(entry)
        item.setHidden(not self._passes(entry))
        self._items[entry.rel] = item
        self.view.insertItem(position, item)
        if self._passes(entry):
            self._queue_thumbs([entry])
        self._sync_view(select_rel=entry.rel if self._passes(entry) else "")

    def entries(self) -> list[OutputEntry]:
        """All entries, including ones hidden by the current filter."""
        return list(self._entries)

    def visible_entries(self) -> list[OutputEntry]:
        return [entry for entry in self._entries if self._passes(entry)]

    def filter_index(self) -> int:
        return self._filter_index

    def set_filter(self, index: int) -> None:
        if index < FILTER_ALL or index > FILTER_UNPROCESSED:
            return
        self._filter_index = index
        if self._filter.current_index() != index:
            self._filter.blockSignals(True)
            self._filter.set_current(index)
            self._filter.blockSignals(False)
        self._apply_visibility()

    def _apply_visibility(self) -> None:
        for entry in self._entries:
            item = self._items.get(entry.rel)
            if item is not None:
                item.setHidden(not self._passes(entry))
        self._queue_thumbs(self.visible_entries())
        self._sync_view()

    def _sync_dirs(self) -> None:
        """Rebuild the sub-directory filter, keeping the current choice."""
        subdirs = sorted(
            {self._top_dir(entry.rel) for entry in self._entries} - {""}
        )
        self._dir_filter.setVisible(bool(subdirs))
        if not subdirs:
            self._dir = None
            self._dir_filter.blockSignals(True)
            self._dir_filter.clear()
            self._dir_filter.blockSignals(False)
            return

        current = self._dir
        self._dir_filter.blockSignals(True)
        self._dir_filter.clear()
        self._dir_filter.addItem("全部目录", None)
        if any(self._top_dir(entry.rel) == "" for entry in self._entries):
            self._dir_filter.addItem("根目录", "")
        for name in subdirs:
            self._dir_filter.addItem(name, name)
        index = 0
        if current is not None:
            for position in range(self._dir_filter.count()):
                if self._dir_filter.itemData(position) == current:
                    index = position
                    break
        self._dir_filter.setCurrentIndex(index)
        self._dir = self._dir_filter.itemData(index)
        self._dir_filter.blockSignals(False)

    def _on_dir_changed(self, index: int) -> None:
        self._dir = self._dir_filter.itemData(index)
        self._apply_visibility()

    @staticmethod
    def _top_dir(rel: str) -> str:
        normalised = rel.replace("\\", "/")
        return normalised.split("/", 1)[0] if "/" in normalised else ""

    def selected_entry(self) -> OutputEntry | None:
        item = self.view.currentItem()
        if item is None or item.isHidden():
            return None
        entry = item.data(Qt.UserRole)
        return entry if isinstance(entry, OutputEntry) else None

    def set_current_rel(self, rel: str) -> None:
        item = self._items.get(rel)
        if item is None:
            return
        entry = item.data(Qt.UserRole)
        if isinstance(entry, OutputEntry) and not self._passes(entry):
            self._dir = None
            self._dir_filter.blockSignals(True)
            self._dir_filter.setCurrentIndex(0)
            self._dir_filter.blockSignals(False)
            self.set_filter(FILTER_ALL)
        self.view.setCurrentItem(item)
        self.view.scrollToItem(item, QAbstractItemView.PositionAtCenter)

    # --------------------------------------------------------------- internal
    def _passes(self, entry: OutputEntry) -> bool:
        if self._dir is not None and self._top_dir(entry.rel) != self._dir:
            return False
        if self._filter_index == FILTER_PROCESSED:
            return entry.is_processed
        if self._filter_index == FILTER_UNPROCESSED:
            return not entry.is_processed
        if self._filter_index == FILTER_REUSED:
            return entry.reused
        return True

    def _placeholder_icon(self) -> QIcon:
        return QIcon(icons.pixmap("image", self._palette.dim, 48))

    def _make_item(self, entry: OutputEntry) -> QListWidgetItem:
        item = QListWidgetItem(self._placeholder_icon(), self._item_text(entry))
        item.setData(Qt.UserRole, entry)
        item.setTextAlignment(Qt.AlignHCenter | Qt.AlignTop)
        item.setSizeHint(QSize(210, 184))
        self._configure_item(item, entry)
        return item

    def _item_text(self, entry: OutputEntry) -> str:
        return f"{entry.rel}\n{entry.status_label}"

    def _configure_item(self, item: QListWidgetItem, entry: OutputEntry) -> None:
        item.setText(self._item_text(entry))
        item.setData(Qt.UserRole, entry)
        item.setToolTip(
            f"{entry.rel}\n{entry.status_label} · {human_size(entry.size)} · "
            f"{_dt.datetime.fromtimestamp(entry.mtime).strftime('%Y-%m-%d %H:%M')}\n"
            f"{entry.output_path}"
        )

    def _rebuild(self) -> None:
        self._thumb_token += 1
        self._thumb_timer.stop()
        self._thumb_queue.clear()
        self._thumb_queued.clear()
        self._thumb_loaded.clear()
        self._items.clear()
        self.view.setUpdatesEnabled(False)
        self.view.blockSignals(True)
        self.view.clear()
        for entry in self._entries:
            item = self._make_item(entry)
            item.setHidden(not self._passes(entry))
            self.view.addItem(item)
            self._items[entry.rel] = item
        self.view.blockSignals(False)
        self.view.setUpdatesEnabled(True)
        self._sync_view()
        self._queue_thumbs(self.visible_entries())

    def _queue_thumbs(self, entries: list[OutputEntry]) -> None:
        for entry in entries:
            if entry.rel in self._items and entry.rel not in self._thumb_loaded:
                if entry.rel in self._thumb_queued:
                    continue
                self._thumb_queued.add(entry.rel)
                self._thumb_queue.append(entry)
        if self._thumb_queue and not self._thumb_timer.isActive():
            self._thumb_timer.start(0)

    def _load_thumb_batch(self) -> None:
        token = self._thumb_token
        for _ in range(4):
            if not self._thumb_queue:
                return
            entry = self._thumb_queue.pop(0)
            self._thumb_queued.discard(entry.rel)
            if token != self._thumb_token:
                return
            item = self._items.get(entry.rel)
            if item is None or item.isHidden():
                continue
            image = _read_thumbnail(entry.output_path)
            if image is None or image.isNull():
                continue
            item.setIcon(QIcon(QPixmap.fromImage(image)))
            self._thumb_loaded.add(entry.rel)
        if self._thumb_queue and token == self._thumb_token:
            self._thumb_timer.start(0)

    def _sync_view(self, select_rel: str = "") -> None:
        count = len(self._entries)
        visible = self.visible_entries()
        if count:
            processed = sum(1 for entry in self._entries if entry.is_processed)
            reused = sum(1 for entry in self._entries if entry.reused)
            total = self._total_input or count
            self._summary.setText(
                f"输出 {count:,} / 输入 {total:,} · "
                f"已处理 {processed:,} · 未处理 {count - processed:,} · 复用 {reused:,}"
            )
            self._summary.setToolTip(
                "已处理 = 已生成马赛克；未处理 = 原图复制，仍可重新生成"
            )
            if select_rel and select_rel in self._items:
                self.set_current_rel(select_rel)
            elif self.selected_entry() is None and visible:
                self.view.setCurrentItem(self._items[visible[0].rel])
        else:
            self._summary.setText("正在扫描…" if self._loading else "还没有输出结果")
            self._summary.setToolTip("")
        if visible:
            self._stack.setCurrentIndex(1)
            self._empty_text.setText("")
        else:
            self._stack.setCurrentIndex(0)
            self._empty_text.setText(self._empty_message(count))
        self._on_current()

    def _empty_message(self, count: int) -> str:
        if self._loading:
            return "正在扫描输入与输出目录…"
        if not count:
            return "处理完成后，输出会按目录结构出现在这里"
        if self._dir is not None:
            return "该子目录下没有匹配的输出"
        if self._filter_index == FILTER_UNPROCESSED:
            return "没有未处理的图片（原图复制）"
        if self._filter_index == FILTER_PROCESSED:
            return "还没有已处理的输出"
        if self._filter_index == FILTER_REUSED:
            return "还没有通过差分复用生成的输出"
        return "没有匹配的输出"

    def _on_current(self, *_args) -> None:
        entry = self.selected_entry()
        self._compare.setEnabled(entry is not None)

    def _on_activated(self, item: QListWidgetItem) -> None:
        if item is None or item.isHidden():
            return
        entry = item.data(Qt.UserRole)
        if isinstance(entry, OutputEntry):
            self.compareRequested.emit(entry)

    def _emit_compare(self) -> None:
        entry = self.selected_entry()
        if entry is not None:
            self.compareRequested.emit(entry)


def _read_thumbnail(path: str):
    reader = QImageReader(path)
    reader.setAutoTransform(True)
    size = reader.size()
    if size.isValid() and size.width() > 0 and size.height() > 0:
        scale = min(THUMB_W / size.width(), THUMB_H / size.height(), 1.0)
        reader.setScaledSize(
            QSize(
                max(1, int(size.width() * scale)),
                max(1, int(size.height() * scale)),
            )
        )
    return reader.read()
