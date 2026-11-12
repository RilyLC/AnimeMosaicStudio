"""Pre-recognition dialog: list every image, preview masks, open the editor."""

from __future__ import annotations

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QRect,
    QSignalBlocker,
    Qt,
    QTimer,
)
from PySide6.QtGui import QDoubleValidator, QIntValidator
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QSplitter,
    QStackedLayout,
    QStyledItemDelegate,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from .. import icons

from ...core.manual_mask import ManualMaskStore, encode_mask
from ...core.settings import Settings
from ...services.preflight import (
    PreflightEntry,
    entry_core_png,
    entry_mask_png,
)
from ...services.reuse_groups import (
    build_groups,
    load_disabled,
    load_mask_for_entry,
    save_disabled,
    state_key,
)
from ..state import SettingsStore
from ..theme import Palette
from ..widgets.base import Badge, Card, ElidedLabel
from ..widgets.buttons import Button
from ..widgets.switch import Switch
from .controller import PreflightController
from .editor import MaskEditorDialog, load_mask_like, mask_stats
from .preview import MaskPreview, compose_preview
from .reuse_dialog import ReuseGroupsDialog

HEADERS = ("文件", "区域", "覆盖", "状态", "复用组", "手动")

FILTERS = (
    ("全部", "all"),
    ("有遮罩", "mask"),
    ("无遮罩", "empty"),
    ("已手动编辑", "edited"),
    ("失败", "error"),
    ("动图", "animated"),
)


class PreflightModel(QAbstractTableModel):
    def __init__(self, palette: Palette, parent=None):
        super().__init__(parent)
        self._palette = palette
        self._all: list[PreflightEntry] = []
        self._entries: list[PreflightEntry] = []
        self._row_of: dict[str, int] = {}
        self._filter = "all"
        self._group_map: dict[str, str] = {}
        self._group_meta: dict[str, str] = {}
        self._disabled: set[str] = set()

    # ------------------------------------------------------------ Qt contract
    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._entries)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(HEADERS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):  # noqa: N802
        if orientation != Qt.Horizontal:
            return None
        if role == Qt.DisplayRole:
            return HEADERS[section]
        if role == Qt.TextAlignmentRole:
            return int(
                (Qt.AlignRight if section in (1, 2) else Qt.AlignLeft) | Qt.AlignVCenter
            )
        return None

    def data(self, index: QModelIndex, role=Qt.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._entries)):
            return None
        entry = self._entries[index.row()]
        column = index.column()
        if role == Qt.DisplayRole:
            if column == 0:
                return entry.rel
            if column == 1:
                return str(entry.regions) if entry.regions else "—"
            if column == 2:
                return f"{entry.coverage:.1f}%" if entry.coverage else "—"
            if column == 3:
                return entry.status_label
            if column == 4:
                if self.is_disabled(entry.rel):
                    return "已移出"
                return self._group_map.get(entry.rel, "—")
            if column == 5:
                return "手动" if entry.manual else "—"
        if role == Qt.ToolTipRole:
            details = [entry.path]
            if entry.error:
                details.append(entry.error)
            if entry.detections:
                details.append(entry.detections)
            group_key = self._group_map.get(entry.rel)
            if group_key:
                details.append(f"差分复用候选：{group_key}（{self._group_meta[group_key]}）")
            return "\n".join(details)
        if role == Qt.UserRole:
            return entry.rel
        if role == Qt.ForegroundRole:
            palette = self._palette
            if self.is_disabled(entry.rel):
                return palette.muted
            if column == 3:
                if entry.error:
                    return palette.danger
                if entry.status_key in ("mask", "manual"):
                    return palette.success
                return palette.muted
            if column == 4 and entry.manual:
                return palette.accent
            if column == 0:
                return palette.text
            return palette.muted
        if role == Qt.TextAlignmentRole and column in (1, 2):
            return int(Qt.AlignRight | Qt.AlignVCenter)
        return None

    def is_disabled(self, rel: str) -> bool:
        return rel in self._disabled

    def has_group(self, rel: str) -> bool:
        return rel in self._group_map

    def set_disabled(self, disabled: set[str]) -> None:
        self._disabled = set(disabled)
        self._rebuild()

    def set_groups(self, groups) -> None:
        self._group_map = {}
        self._group_meta = {}
        for group in groups:
            for rel in group.rels:
                self._group_map[rel] = group.key
            self._group_meta[group.key] = group.summary
        self._rebuild()

    # ------------------------------------------------------------------- api
    def set_all_entries(self, entries: list[PreflightEntry]) -> None:
        self._all = list(entries)
        self._rebuild()

    def add_entry(self, entry: PreflightEntry) -> None:
        self.upsert(entry)

    def upsert(self, entry: PreflightEntry) -> None:
        """Insert or refresh one row in place.

        Scanning emits one entry per image; resetting the model for every
        single one made the table lose its selection and scroll back to the
        top on each item (and made the progress bar look frozen).  Keep the
        change local instead: a ``dataChanged`` for existing rows, a single
        row insert for new ones.
        """
        replaced = False
        for index, existing in enumerate(self._all):
            if existing.rel == entry.rel:
                self._all[index] = entry
                replaced = True
                break
        if not replaced:
            self._all.append(entry)
        wanted = self.matches(entry)
        row = self._row_of.get(entry.rel)
        if row is not None and wanted:
            self._entries[row] = entry
            self.dataChanged.emit(
                self.index(row, 0), self.index(row, len(HEADERS) - 1)
            )
            return
        if row is not None:
            self.beginRemoveRows(QModelIndex(), row, row)
            self._entries.pop(row)
            self.endRemoveRows()
            self._reindex()
            return
        if not wanted:
            return
        row = len(self._entries)
        self.beginInsertRows(QModelIndex(), row, row)
        self._entries.append(entry)
        self._row_of[entry.rel] = row
        self.endInsertRows()

    def update_entry(self, entry: PreflightEntry) -> None:
        self.upsert(entry)

    def set_filter(self, key: str) -> None:
        self._filter = key
        self._rebuild()

    def _reindex(self) -> None:
        self._row_of = {entry.rel: row for row, entry in enumerate(self._entries)}

    def _rebuild(self) -> None:
        self.beginResetModel()
        self._entries = [entry for entry in self._all if self.matches(entry)]
        self._reindex()
        self.endResetModel()

    def entry_at(self, row: int) -> PreflightEntry | None:
        if 0 <= row < len(self._entries):
            return self._entries[row]
        return None

    def rels(self) -> list[str]:
        return [entry.rel for entry in self._entries]

    def matches(self, entry: PreflightEntry) -> bool:
        if self._filter == "all":
            return True
        if self._filter == "mask":
            return entry.has_mask or entry.manual
        if self._filter == "empty":
            return not entry.has_mask and not entry.manual
        if self._filter == "edited":
            return entry.manual
        if self._filter == "error":
            return bool(entry.error)
        if self._filter == "animated":
            return entry.animated
        return True

    def set_palette(self, palette: Palette) -> None:
        self._palette = palette
        if self._entries:
            self.dataChanged.emit(
                self.index(0, 0),
                self.index(len(self._entries) - 1, len(HEADERS) - 1),
                [Qt.ForegroundRole],
            )


class ReuseGroupDelegate(QStyledItemDelegate):
    """Draw the inline remove/restore icon in the 复用组 column."""

    def __init__(self, palette: Palette, model: PreflightModel, parent=None):
        super().__init__(parent)
        self._palette = palette
        self._model = model

    def paint(self, painter, option, index) -> None:
        super().paint(painter, option, index)
        rel = index.data(Qt.UserRole)
        if not rel or index.column() != 4:
            return
        if not (self._model.has_group(str(rel)) or self._model.is_disabled(str(rel))):
            return
        disabled = self._model.is_disabled(str(rel))
        color = self._palette.accent if disabled else self._palette.muted
        icon = icons.icon("refresh" if disabled else "trash", color, 14)
        text = str(index.data(Qt.DisplayRole) or "")
        text_width = option.fontMetrics.horizontalAdvance(text)
        x = option.rect.left() + 6 + text_width + 8
        x = min(x, option.rect.right() - 8)
        rect = QRect(x, option.rect.center().y() - 7, 14, 14)
        icon.paint(painter, rect, Qt.AlignCenter)


class PreflightDialog(QDialog):
    def __init__(
        self,
        controller: PreflightController,
        store: SettingsStore,
        palette: Palette,
        parent=None,
        autostart: bool = False,
    ):
        super().__init__(parent)
        self.controller = controller
        self.store = store
        self._palette = palette
        self._current_rel: str | None = None
        self._show_mask = True
        self._preview_pixmap = None
        self._preview_key: tuple | None = None
        self._preview_grow_value = int(self.store.settings.grow)
        self._failed = False
        self._scanned_this_run = 0
        self._groups = []
        self._disabled: set[str] = set()
        self._grow_timer = QTimer(self)
        self._grow_timer.setSingleShot(True)
        self._grow_timer.setInterval(90)
        self._grow_timer.timeout.connect(self._refresh_grow_preview)

        self.setObjectName("PreflightDialog")
        self.setWindowTitle("预处理 · 遮罩检查")
        self.setModal(False)
        # A non-modal tool window the user keeps around while tuning settings:
        # let it be resized down to a laptop screen and maximised.
        self.setWindowFlag(Qt.WindowMaximizeButtonHint, True)
        self.setSizeGripEnabled(True)
        self.setMinimumSize(920, 600)
        self.resize(1320, 860)
        self._build()
        self._connect()
        output_dir = self.store.settings.output_dir
        self._disabled = load_disabled(output_dir) if output_dir else set()
        self._model.set_disabled(self._disabled)
        self._refresh_scope()
        self._refresh_manual()
        self._reload_model()
        self._on_state(False)
        self._sync_controls()
        if autostart or not self.controller.entries:
            self._load_or_start()
        if self.controller.entries:
            # Group ids live in the mask files, so the column can be filled
            # from the cache alone; defer it so the window paints first.
            QTimer.singleShot(0, lambda: self._refresh_groups(silent=True))

    # ------------------------------------------------------------------ build
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(12)

        header = QHBoxLayout()
        header.setSpacing(12)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        title = QLabel("预处理")
        title.setObjectName("PageTitle")
        subtitle = QLabel("完成预处理确认遮罩后再回到工作台开始处理。")
        subtitle.setObjectName("PageSubtitle")
        titles.addWidget(title)
        titles.addWidget(subtitle)
        header.addLayout(titles, 1)
        self._scope_badge = Badge("", "neutral")
        header.addWidget(self._scope_badge, 0, Qt.AlignTop)
        self._status = Badge("准备中", "neutral")
        header.addWidget(self._status, 0, Qt.AlignTop)
        self._start_button = Button("开始预处理", "primary", "scan", self._palette)
        self._start_button.clicked.connect(self._toggle_scan)
        header.addWidget(self._start_button, 0, Qt.AlignTop)
        root.addLayout(header)

        params = QHBoxLayout()
        params.setSpacing(8)
        caption = QLabel("检测参数")
        caption.setObjectName("FormLabel")
        params.addWidget(caption)

        self._conf_edit = QLineEdit()
        self._conf_edit.setFixedWidth(64)
        self._conf_edit.setValidator(QDoubleValidator(0.01, 1.0, 2))
        self._conf_edit.setToolTip("马赛克检测置信度，改完按回车生效")
        self._conf_edit.editingFinished.connect(self._apply_conf)
        params.addWidget(QLabel("置信度"))
        params.addWidget(self._conf_edit)

        self._grow_edit = QLineEdit()
        self._grow_edit.setFixedWidth(64)
        self._grow_edit.setValidator(QIntValidator(0, 256))
        self._grow_edit.setToolTip("遮罩外扩像素：输入时实时预览，按回车或离开输入框保存")
        self._grow_edit.textEdited.connect(self._on_grow_text)
        self._grow_edit.editingFinished.connect(self._apply_grow)
        params.addWidget(QLabel("外扩"))
        params.addWidget(self._grow_edit)
        params.addWidget(QLabel("px"))

        self._nsfw_combo = QComboBox()
        for label, value in (
            ("关闭", "off"),
            ("仅记录", "record"),
            ("并入遮罩", "augment"),
        ):
            self._nsfw_combo.addItem(label, value)
        self._nsfw_combo.setMinimumWidth(96)
        self._nsfw_combo.currentIndexChanged.connect(self._apply_nsfw_mode)
        params.addWidget(QLabel("NSFW"))
        params.addWidget(self._nsfw_combo)
        params.addStretch(1)
        root.addLayout(params)

        reuse_params = QHBoxLayout()
        reuse_params.setSpacing(8)
        reuse_caption = QLabel("差分复用")
        reuse_caption.setObjectName("FormLabel")
        reuse_params.addWidget(reuse_caption)
        self._reuse_switch = Switch(bool(self.store.settings.reuse_enabled), self._palette)
        self._reuse_switch.setToolTip("开启后，相似裁切块可复用上一张的生成结果")
        self._reuse_switch.toggled.connect(self._apply_reuse_enabled)
        reuse_params.addWidget(self._reuse_switch)
        self._reuse_button = Button(
            "差分管理", "secondary", "layers", self._palette, size="sm"
        )
        self._reuse_button.setStyleSheet("font-size: 11px;")
        self._reuse_button.setToolTip("查看差分复用组、调整判定规则并管理组内图片")
        self._reuse_button.clicked.connect(self._open_reuse_groups)
        reuse_params.addWidget(self._reuse_button)
        reuse_hint = QLabel("差分判定规则在“差分管理”中调整")
        reuse_hint.setObjectName("FormHelp")
        reuse_params.addWidget(reuse_hint)
        reuse_params.addStretch(1)
        root.addLayout(reuse_params)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        self._filter = QComboBox()
        for label, value in FILTERS:
            self._filter.addItem(label, value)
        self._filter.setMinimumWidth(130)
        self._filter.currentIndexChanged.connect(self._on_filter)
        toolbar.addWidget(self._filter)
        self._stats = QLabel("0 张")
        self._stats.setObjectName("Caption")
        toolbar.addWidget(self._stats)
        self._progress = QProgressBar()
        self._progress.setRange(0, 1)
        self._progress.setValue(0)
        toolbar.addWidget(self._progress, 1)
        self._progress_label = QLabel("0 / 0")
        self._progress_label.setObjectName("Caption")
        toolbar.addWidget(self._progress_label)
        self._last_log = QLabel("")
        self._last_log.setObjectName("Caption")
        self._last_log.setMaximumWidth(320)
        toolbar.addWidget(self._last_log)
        root.addLayout(toolbar)

        body = QSplitter(Qt.Horizontal)
        body.setChildrenCollapsible(False)
        body.setHandleWidth(10)
        left = Card("图片列表", "按输入目录顺序列出；双击可编辑遮罩", "image", self._palette)
        left.setMinimumWidth(420)
        self._model = PreflightModel(self._palette)
        self._table = QTableView()
        self._table.setModel(self._model)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.setShowGrid(False)
        self._table.verticalHeader().setVisible(False)
        self._table.verticalHeader().setDefaultSectionSize(34)
        self._table.horizontalHeader().setHighlightSections(False)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self._table.setFrameShape(QTableView.NoFrame)
        self._table.setItemDelegateForColumn(
            4, ReuseGroupDelegate(self._palette, self._model, self._table)
        )
        self._table.doubleClicked.connect(self._edit_current)
        self._table.clicked.connect(self._on_table_clicked)

        self._stack = QStackedLayout()
        empty = QWidget()
        empty_layout = QVBoxLayout(empty)
        empty_layout.setAlignment(Qt.AlignCenter)
        empty_text = QLabel("还没有预处理结果")
        empty_text.setObjectName("CardTitle")
        empty_text.setAlignment(Qt.AlignCenter)
        empty_hint = QLabel("调好检测参数后，点击右上角“开始预处理”。")
        empty_hint.setObjectName("Caption")
        empty_hint.setAlignment(Qt.AlignCenter)
        empty_layout.addWidget(empty_text)
        empty_layout.addWidget(empty_hint)
        self._stack.addWidget(empty)
        self._stack.addWidget(self._table)
        table_host = QWidget()
        table_host.setLayout(self._stack)
        left.add(table_host, 1)
        body.addWidget(left)

        right = Card(
            "遮罩预览",
            "仅预览显示：红色为遮罩，蓝色为外扩范围；外扩值按回车保存",
            "grid",
            self._palette,
        )
        right.setMinimumWidth(300)
        self._show_mask_switch = Switch(True, self._palette)
        right.add_action(QLabel("遮罩"))
        right.add_action(self._show_mask_switch)
        self._show_grow_switch = Switch(bool(self.store.settings.show_grow_band), self._palette)
        self._show_grow_switch.setToolTip("仅预览显示蓝色外扩范围，不改变遮罩")
        right.add_action(QLabel("外扩"))
        right.add_action(self._show_grow_switch)
        self._show_nsfw_switch = Switch(bool(self.store.settings.show_nsfw_marks), self._palette)
        self._show_nsfw_switch.setToolTip("显示 NSFW 检测框")
        right.add_action(QLabel("NSFW"))
        right.add_action(self._show_nsfw_switch)
        self._preview = MaskPreview(self._palette)
        self._preview.setMinimumHeight(220)
        right.add(self._preview, 1)

        zoom_bar = QHBoxLayout()
        zoom_bar.setSpacing(6)
        fit_button = Button("适应窗口", "ghost", None, self._palette, size="sm")
        fit_button.setToolTip("缩放回适应窗口（双击预览也可复位）")
        fit_button.clicked.connect(self._preview.fit_to_view)
        zoom_bar.addWidget(fit_button)
        zoom_out = Button("−", "ghost", None, self._palette, size="sm")
        zoom_out.setToolTip("缩小")
        zoom_out.clicked.connect(self._preview.zoom_out)
        zoom_bar.addWidget(zoom_out)
        zoom_in = Button("＋", "ghost", None, self._palette, size="sm")
        zoom_in.setToolTip("放大")
        zoom_in.clicked.connect(self._preview.zoom_in)
        zoom_bar.addWidget(zoom_in)
        self._zoom_label = QLabel("适应")
        self._zoom_label.setObjectName("Caption")
        self._zoom_label.setMinimumWidth(42)
        zoom_bar.addWidget(self._zoom_label)
        zoom_bar.addStretch(1)
        zoom_hint = QLabel("滚轮缩放 · 拖动平移")
        zoom_hint.setObjectName("Caption")
        zoom_bar.addWidget(zoom_hint)
        right.add_layout(zoom_bar)
        self._preview.zoomChanged.connect(self._on_zoom_changed)
        self._preview_name = ElidedLabel("未选择图片")
        self._preview_name.setObjectName("FormLabel")
        right.add(self._preview_name)
        self._preview_meta = QLabel("")
        self._preview_meta.setObjectName("Caption")
        self._preview_meta.setWordWrap(True)
        right.add(self._preview_meta)
        preview_hint = QLabel("遮罩 / 外扩 / NSFW 开关仅影响此预览，不会修改保存的黑白遮罩。")
        preview_hint.setObjectName("Caption")
        preview_hint.setWordWrap(True)
        right.add(preview_hint)
        actions = QHBoxLayout()
        actions.setSpacing(8)
        self._manual_badge = Badge("未编辑", "neutral")
        actions.addWidget(self._manual_badge)
        actions.addStretch(1)
        self._delete_button = Button("删除手动遮罩", "danger", "trash", self._palette, size="sm")
        self._delete_button.clicked.connect(self._delete_manual)
        actions.addWidget(self._delete_button)
        self._edit_button = Button("编辑遮罩", "primary", "brush", self._palette)
        self._edit_button.clicked.connect(self._edit_current)
        actions.addWidget(self._edit_button)
        right.add_layout(actions)
        body.addWidget(right)
        body.setStretchFactor(0, 3)
        body.setStretchFactor(1, 2)
        body.setSizes([780, 540])
        root.addWidget(body, 1)

        footer = QHBoxLayout()
        footer.setSpacing(8)
        hint = QLabel("手动遮罩保存在输出目录的 _AnimeMosaicStudio_masks 文件夹中。")
        hint.setObjectName("Caption")
        footer.addWidget(hint, 1)
        clear = Button("清除全部手动遮罩", "ghost", "trash", self._palette, size="sm")
        clear.clicked.connect(self._clear_manual)
        footer.addWidget(clear)
        self._redo_one = Button("重新处理选中图", "secondary", "refresh", self._palette, size="sm")
        self._redo_one.clicked.connect(self._redo_current)
        footer.addWidget(self._redo_one)
        self._redo_all_button = Button(
            "重新处理全部", "secondary", "refresh", self._palette, size="sm"
        )
        self._redo_all_button.clicked.connect(self._redo_all)
        footer.addWidget(self._redo_all_button)
        close = Button("关闭", "secondary", None, self._palette)
        close.clicked.connect(self.close)
        footer.addWidget(close)
        root.addLayout(footer)

    # ---------------------------------------------------------------- wiring
    def _connect(self) -> None:
        self.controller.started.connect(self._on_started)
        self.controller.itemReady.connect(self._on_item)
        self.controller.progress.connect(self._on_progress)
        self.controller.finished.connect(self._on_finished)
        self.controller.failed.connect(self._on_failed)
        self.controller.stateChanged.connect(self._on_state)
        self.controller.itemsChanged.connect(self._reload_model)
        self.controller.log.connect(self._on_log)
        self._table.selectionModel().currentRowChanged.connect(self._on_select)
        self._show_mask_switch.toggled.connect(self._on_show_mask)
        self._show_grow_switch.toggled.connect(self._on_show_grow)
        self._show_nsfw_switch.toggled.connect(self._on_show_nsfw)
        self.store.changed.connect(self._on_setting_changed)
        self.store.replaced.connect(self._on_settings_replaced)

    # ------------------------------------------------------------------ flow
    def _idle_text(self) -> str:
        if not self.controller.has_results():
            return "开始预处理"
        settings = self.store.settings
        if self.controller.is_stale(settings) or self.controller.dirty:
            return "重新预处理"
        return "继续预处理"

    def _load_or_start(self) -> None:
        settings = self.store.settings
        if not settings.input_dir:
            self._set_status("请先选择输入目录", "warn")
            return
        if not self.controller.has_results():
            self.controller.load_cached(settings)
        self.controller.refresh_manual(settings)
        count = len(self.controller.entries)
        if not count:
            self._set_status("尚未预处理 · 请点击“开始预处理”", "neutral")
            self._on_state(False)
            return
        if self.controller.is_stale(settings):
            self._set_status(
                f"已加载 {count} 张缓存 · 检测设置已变化，点“重新预处理”将重新识别全部图片",
                "warn",
            )
        elif self.controller.dirty:
            self._set_status(
                f"已加载 {count} 张缓存 · 有图片已变化，点“重新预处理”只处理变化的图片",
                "warn",
            )
        else:
            self._set_status(
                f"已加载 {count} 张缓存 · 点“继续预处理”只处理新增或变化的图片", "ok"
            )
        self._progress.setRange(0, max(1, count))
        self._progress.setValue(count)
        self._progress_label.setText(f"{count} / {count}")
        self._refresh_stats()
        self._reload_model()
        self._start_button.setText(self._idle_text())

    def _start(self, mode: str = "continue", only_rels: list[str] | None = None) -> None:
        settings = self.store.settings
        if not settings.input_dir:
            self._set_status("请先选择输入目录", "warn")
            return
        if not settings.output_dir:
            self._set_status("请先选择输出目录（手动遮罩保存在输出目录）", "warn")
            return
        self._failed = False
        self._scanned_this_run = 0
        stale = self.controller.is_stale(settings) or self.controller.dirty
        if mode == "all" and only_rels is None:
            # A full re-detection refreshes the existing rows in place instead
            # of emptying the table: the scroll position and the current
            # selection survive, and the rows visibly fill up as results land.
            self._preview_name.setText("重新识别中…")
        elif only_rels:
            label = only_rels[0] if len(only_rels) == 1 else f"{len(only_rels)} 张图片"
            self._preview_name.setText(f"重新处理 · {label}")
        self._progress.setRange(0, 1)
        self._progress.setValue(0)
        self._progress_label.setText("0 / 0")
        if mode == "all" and only_rels is None and stale:
            self._set_status("检测设置已变化 · 正在重新识别全部图片…", "accent")
        else:
            self._set_status("正在预处理…", "accent")
        self._start_button.setEnabled(False)
        self.controller.start(settings, mode=mode, only_rels=only_rels)

    def _refresh_groups(self, silent: bool = False, min_iou: float | None = None) -> list:
        entries = self.controller.entries
        settings = self.store.settings
        if settings.output_dir:
            self._disabled = load_disabled(settings.output_dir)
            self._model.set_disabled(self._disabled)
        if not entries:
            self._groups = []
            self._model.set_groups([])
            self._reuse_button.setText("差分管理（待检测）")
            return []
        if not settings.output_dir:
            # Masks live under the output directory; without one there is
            # nothing to group yet.
            self._groups = []
            self._model.set_groups([])
            self._reuse_button.setText("差分管理（待检测）")
            return []
        self._reuse_button.setText("差分管理")
        mask_store = ManualMaskStore(settings.output_dir)
        groups = build_groups(
            entries,
            lambda entry: load_mask_for_entry(entry, mask_store),
            min_iou=settings.reuse_min_group_iou if min_iou is None else min_iou,
        )
        self._groups = groups
        self._model.set_groups(groups)
        if self._current_rel:
            for index in range(self._model.rowCount()):
                entry = self._model.entry_at(index)
                if entry and entry.rel == self._current_rel:
                    self._table.selectRow(index)
                    break
        if not silent:
            if groups:
                self._set_status(f"发现 {len(groups)} 个差分复用候选组", "ok")
            else:
                self._set_status(
                    "没有发现可成组的遮罩；处理时仍会按像素差分逐张判断", "neutral"
                )
        return groups

    def _open_reuse_groups(self) -> None:
        entries = self.controller.entries
        if not entries:
            self._set_status("请先完成预处理，再查看差分复用组", "warn")
            return
        settings = self.store.settings
        groups = self._refresh_groups(silent=True)
        if not groups:
            self._set_status(
                "当前没有候选组；可在差分管理中放宽分组 IoU 后重新检测", "neutral"
            )
        dialog = ReuseGroupsDialog(
            groups,
            {entry.rel: entry for entry in entries},
            self._disabled,
            settings.output_dir,
            self._palette,
            self,
            store=self.store,
            rebuild=lambda iou: self._refresh_groups(silent=True, min_iou=iou),
        )
        if dialog.exec() == QDialog.Accepted:
            self._disabled = load_disabled(settings.output_dir)
            self._model.set_disabled(self._disabled)
            self._refresh_groups(silent=True)
            self._set_status("差分管理设置已保存，下次处理生效", "ok")

    def _redo_current(self) -> None:
        entry = self._model.entry_at(self._table.currentIndex().row())
        if entry is None or not self.store.get("output_dir"):
            return
        self._start(mode="all", only_rels=[entry.rel])

    def _redo_all(self) -> None:
        if not self.controller.running:
            self._start(mode="all")

    def _toggle_scan(self) -> None:
        if self.controller.running:
            self.controller.stop()
            self._start_button.setEnabled(False)
            self._set_status("正在停止…", "warn")
            return
        settings = self.store.settings
        if self.controller.is_stale(settings) or self.controller.dirty:
            # Detection settings changed: a "continue" pass would silently
            # re-detect everything anyway, so be explicit and refresh all rows.
            self._start(mode="all")
        else:
            self._start(mode="continue")

    # ---------------------------------------------------------------- signals
    def _on_started(self, total: int) -> None:
        if not self._model.rowCount():
            # Only a full re-scan empties the table; its cached group ids are
            # meaningless until the run finishes.  A "continue" pass keeps the
            # existing rows (and their groups) on screen.
            self._groups = []
            self._model.set_groups([])
            self._reuse_button.setText("差分管理（待检测）")
        self._progress.setRange(0, max(1, total))
        self._progress.setValue(0)
        self._progress_label.setText(f"0 / {total}")
        self._set_status(f"正在预处理 0 / {total}", "accent")
        self._start_button.setEnabled(True)
        self._start_button.setText("停止")

    def _on_item(self, entry: PreflightEntry) -> None:
        self._scanned_this_run += 1
        was_empty = self._model.rowCount() == 0
        self._model.upsert(entry)
        if self._model.rowCount() > 0:
            # Only pull the view to the first result once; re-selecting on
            # every item would fight the user's scrolling and re-decode the
            # preview mask on the UI thread for each image.
            if was_empty and self._scanned_this_run == 1:
                self._table.selectRow(0)
            self._stack.setCurrentIndex(1)
        if self._scanned_this_run % 8 == 1:
            # ``summary()`` walks every entry; keep it off the per-item path.
            self._refresh_stats()

    def _on_progress(self, done: int, total: int) -> None:
        self._progress.setRange(0, max(1, total))
        self._progress.setValue(done)
        self._progress_label.setText(f"{done} / {total}")
        self._set_status(f"正在预处理 {done} / {total}", "accent")

    def _on_finished(self, summary: dict) -> None:
        self._start_button.setEnabled(True)
        self._start_button.setText(self._idle_text())
        self._progress.setRange(0, max(1, summary.get("total", 0)))
        self._progress.setValue(summary.get("scanned", 0))
        self._progress_label.setText(
            f"{summary.get('scanned', 0)} / {summary.get('total', 0)}"
        )
        self._refresh_stats()
        self._reload_model()
        if self._scanned_this_run:
            # Only a run that produced results can change group membership.
            self._refresh_groups(silent=True)
        if self._failed:
            self._failed = False
            return
        if summary.get("scanned"):
            stopped = summary.get("scanned", 0) < summary.get("total", 0)
            self._set_status(
                ("已停止" if stopped else "完成")
                + f" · {summary.get('masks', 0)} 张有遮罩 · {summary.get('edited', 0)} 张手动",
                "warn" if stopped else "ok",
            )
        else:
            if summary.get("total"):
                self._set_status("没有新增或变化的图片，列表已是最新", "ok")
            else:
                self._set_status("没有可识别的图片", "warn")

    def _on_failed(self, message: str) -> None:
        self._failed = True
        self._start_button.setEnabled(True)
        self._start_button.setText(self._idle_text())
        self._set_status(f"预处理失败：{message}", "danger")
        self._last_log.setText(message[:80])

    def _on_state(self, running: bool) -> None:
        if running:
            self._start_button.setText("停止")
            self._start_button.setEnabled(True)
        else:
            self._start_button.setText(self._idle_text())
            self._start_button.setEnabled(True)
            self._redo_one.setEnabled(
                self._model.entry_at(self._table.currentIndex().row()) is not None
            )

    def _on_log(self, level: str, message: str) -> None:
        self._last_log.setText(message[:80])
        if level == "error":
            self._set_status(message, "danger")

    # ------------------------------------------------------------------ model
    def _reload_model(self) -> None:
        settings = self.store.settings
        current = self._current_rel
        entries = self.controller.entries
        self._model.set_all_entries(entries)
        self._model.set_filter(str(self._filter.currentData()))
        self._refresh_stats()
        self._reuse_button.setEnabled(bool(entries))
        if not entries:
            self._reuse_button.setText("差分管理（待检测）")
        if self._model.rowCount() == 0:
            self._stack.setCurrentIndex(0)
            self._preview.clear()
            self._current_rel = None
            return
        self._stack.setCurrentIndex(1)
        row = 0
        if current:
            for index in range(self._model.rowCount()):
                entry = self._model.entry_at(index)
                if entry and entry.rel == current:
                    row = index
                    break
        else:
            for index in range(self._model.rowCount()):
                entry = self._model.entry_at(index)
                if entry and entry.has_mask:
                    row = index
                    break
        self._table.selectRow(row)

    def _on_filter(self) -> None:
        self._model.set_filter(str(self._filter.currentData()))
        self._refresh_stats()
        if self._model.rowCount() == 0:
            self._preview.clear()
            self._current_rel = None
        else:
            self._table.selectRow(0)

    def _refresh_stats(self) -> None:
        summary = self.controller.summary()
        self._stats.setText(
            f"{summary['scanned']} 张 · {summary['masks']} 有遮罩 · {summary['edited']} 已编辑"
        )

    def _refresh_scope(self) -> None:
        include = self.store.settings.include_subdirs
        self._scope_badge.setText("含子目录" if include else "仅第一层")
        self._scope_badge.set_tone("accent" if include else "neutral")

    # ----------------------------------------------------------------- preview
    def _on_table_clicked(self, index: QModelIndex) -> None:
        if index.column() != 4:
            return
        entry = self._model.entry_at(index.row())
        if entry is None:
            return
        if self._model.has_group(entry.rel) or self._model.is_disabled(entry.rel):
            self._toggle_reuse(entry.rel)

    def _toggle_reuse(self, rel: str) -> None:
        output_dir = self.store.settings.output_dir
        if not output_dir:
            self._set_status("请先选择输出目录", "warn")
            return
        key = state_key(rel)
        if key in self._disabled:
            self._disabled.discard(key)
        else:
            self._disabled.add(key)
        if not save_disabled(output_dir, self._disabled):
            self._set_status("无法保存差分管理状态", "danger")
            return
        self._model.set_disabled(self._disabled)
        self._refresh_groups(silent=True)
        self._set_status("已移出复用组" if key in self._disabled else "已恢复复用组", "ok")

    def _on_select(self, current: QModelIndex, previous: QModelIndex) -> None:
        if not current.isValid():
            return
        entry = self._model.entry_at(current.row())
        if entry is None:
            return
        self._current_rel = entry.rel
        self._redo_one.setEnabled(not self.controller.running)
        self._show_entry(entry)

    def _show_entry(self, entry: PreflightEntry, force: bool = False) -> None:
        self._current_rel = entry.rel
        settings = self.store.settings
        store = ManualMaskStore(settings.output_dir)
        manual_mask = store.load(entry.rel)
        if manual_mask is not None:
            mask_png = encode_mask(manual_mask)
            core_mask_png = mask_png
        else:
            mask_png = entry_mask_png(entry)
            core_mask_png = entry_core_png(entry)
        self._preview_name.setText(entry.rel)
        details = []
        if entry.width and entry.height:
            details.append(f"{entry.width}×{entry.height}")
        if entry.error:
            details.append(entry.error)
        elif manual_mask is not None:
            regions, coverage = mask_stats(manual_mask)
            details.append(f"手动 {regions} 处 · 覆盖 {coverage:.2f}%")
        else:
            details.append(f"自动 {entry.regions} 处 · 覆盖 {entry.coverage:.2f}%")
        self._preview_meta.setText(" · ".join(details))
        self._manual_badge.setText("手动遮罩" if manual_mask is not None else "未编辑")
        self._manual_badge.set_tone("accent" if manual_mask is not None else "neutral")
        self._edit_button.setEnabled(
            bool(settings.output_dir) and not entry.error and not entry.animated
        )
        self._delete_button.setEnabled(manual_mask is not None)

        grow = 0 if manual_mask is not None else self._preview_grow()
        details.append(f"外扩 +{grow} px（仅预览）")
        self._preview_meta.setText(" · ".join(details))
        key = (
            entry.rel,
            entry.manual,
            entry.regions,
            mask_png,
            core_mask_png,
            self._show_mask,
            grow,
            bool(self.store.get("show_grow_band")),
            bool(self.store.get("show_nsfw_marks")),
            entry.nsfw_boxes,
        )
        if force or key != self._preview_key:
            # Compose with some headroom so wheel zoom keeps a sharp image,
            # but cap the proxy size: 4K sources would otherwise cost too much
            # on the UI thread.
            max_width = min(2000, max(900, int(self._preview.width() * 1.7)))
            max_height = min(2000, max(620, int(self._preview.height() * 1.7)))
            pixmap = compose_preview(
                entry.path,
                mask_png,
                max_width=max_width,
                max_height=max_height,
                show_mask=self._show_mask,
                grow=grow,
                show_grow=bool(self.store.get("show_grow_band")),
                nsfw_boxes=entry.nsfw_boxes,
                show_nsfw=bool(self.store.get("show_nsfw_marks")),
                core_mask_png=core_mask_png,
            )
            self._preview_pixmap = pixmap
            self._preview_key = key
        if self._preview_pixmap is not None and not self._preview_pixmap.isNull():
            self._preview.show_preview(self._preview_pixmap)
        else:
            self._preview.clear()

    def _on_zoom_changed(self, percent: float) -> None:
        self._zoom_label.setText("适应" if percent <= 0 else f"{percent:.0f}%")

    def _on_show_mask(self, checked: bool) -> None:
        self._show_mask = bool(checked)
        self._preview_key = None
        entry = self._model.entry_at(self._table.currentIndex().row())
        if entry:
            self._show_entry(entry)

    def _on_show_grow(self, checked: bool) -> None:
        self.store.set("show_grow_band", bool(checked))
        self._preview_key = None
        entry = self._model.entry_at(self._table.currentIndex().row())
        if entry:
            self._show_entry(entry)

    def _on_show_nsfw(self, checked: bool) -> None:
        self.store.set("show_nsfw_marks", bool(checked))
        self._preview_key = None
        entry = self._model.entry_at(self._table.currentIndex().row())
        if entry:
            self._show_entry(entry)

    # ------------------------------------------------------------------ edits
    def _edit_current(self) -> None:
        if self._table.currentIndex().column() == 4:
            return
        entry = self._model.entry_at(self._table.currentIndex().row())
        if entry is None or entry.error or entry.animated or not self.store.get("output_dir"):
            return
        settings = self.store.settings
        store = ManualMaskStore(settings.output_dir)
        manual = store.load(entry.rel)
        auto_png = entry_mask_png(entry)
        auto = load_mask_like(auto_png, (entry.height, entry.width))
        initial = manual if manual is not None and manual.shape == (entry.height, entry.width) else auto
        core_png = encode_mask(manual) if manual is not None else entry_core_png(entry)
        rel = entry.rel
        try:
            dialog = MaskEditorDialog(
                entry.path,
                auto_png,
                initial,
                self._palette,
                title=f"编辑遮罩 · {entry.rel}",
                parent=self,
                core_mask_png=core_png,
                auto_provider=lambda: self.controller.auto_payload(rel),
            )
        except ValueError as exc:
            QMessageBox.warning(self, "无法编辑", str(exc))
            return
        if dialog.exec() != QDialog.Accepted:
            return
        mask = dialog.result_mask()
        if mask is None:
            return
        try:
            store.save(entry.rel, mask)
        except OSError as exc:
            QMessageBox.warning(self, "保存失败", str(exc))
            return
        updated = self.controller.apply_manual(entry.rel, mask)
        if updated is not None:
            entry = updated
            self._model.update_entry(entry)
        else:
            entry.manual = True
            self.controller.mark_manual(entry.rel, True)
            self._model.update_entry(entry)
        self._show_entry(entry)
        self._refresh_stats()
        self._refresh_groups(silent=True)

    def _delete_manual(self) -> None:
        entry = self._model.entry_at(self._table.currentIndex().row())
        if entry is None or not self.store.get("output_dir"):
            return
        ManualMaskStore(self.store.get("output_dir")).delete(entry.rel)
        entry.manual = False
        self.controller.mark_manual(entry.rel, False)
        self._model.update_entry(entry)
        self._show_entry(entry)
        self._refresh_stats()
        # The automatic result is needed again, so re-detect this one image.
        self._start(mode="all", only_rels=[entry.rel])

    def _clear_manual(self) -> None:
        if not self.store.get("output_dir"):
            return
        answer = QMessageBox.question(
            self,
            "清除手动遮罩",
            "将删除输出目录中所有手动编辑的遮罩，恢复为自动检测。确定继续吗？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        rels = [entry.rel for entry in self.controller.entries if entry.manual]
        ManualMaskStore(self.store.get("output_dir")).clear()
        self._refresh_manual()
        if rels:
            # Automatic results are needed again for every cleared image.
            self._start(mode="all", only_rels=rels)
        else:
            self._reload_model()

    def _refresh_manual(self) -> None:
        self.controller.refresh_manual(self.store.settings)

    # --------------------------------------------------------------- settings
    def _apply_conf(self) -> None:
        try:
            value = float(self._conf_edit.text())
        except ValueError:
            self._sync_controls()
            return
        if not 0.01 <= value <= 1.0:
            self._sync_controls()
            return
        self.store.set("conf", value)

    def _preview_grow(self) -> int:
        return max(0, min(256, int(self._preview_grow_value)))

    def _on_grow_text(self, _text: str) -> None:
        try:
            value = int(self._grow_edit.text())
        except ValueError:
            return
        self._preview_grow_value = max(0, min(256, value))
        self._grow_timer.start()

    def _refresh_grow_preview(self) -> None:
        self._preview_key = None
        entry = self._current_entry()
        if entry:
            self._show_entry(entry, force=True)

    def _current_entry(self):
        rel = self._current_rel
        if rel:
            for entry in self.controller.entries:
                if entry.rel == rel:
                    return entry
        return self._model.entry_at(self._table.currentIndex().row())

    def _apply_grow(self) -> None:
        self._grow_timer.stop()
        try:
            value = int(self._grow_edit.text())
        except ValueError:
            self._sync_controls()
            return
        if not 0 <= value <= 256:
            self._sync_controls()
            return
        self._preview_grow_value = value
        self.store.set("grow", value)

    def _apply_nsfw_mode(self) -> None:
        value = str(self._nsfw_combo.currentData() or "off")
        if value != self.store.get("nsfw_mode"):
            self.store.set("nsfw_mode", value)

    def _apply_reuse_enabled(self, checked: bool) -> None:
        self.store.set("reuse_enabled", bool(checked))

    def _sync_controls(self) -> None:
        settings = self.store.settings
        with QSignalBlocker(self._conf_edit):
            self._conf_edit.setText(f"{settings.conf:g}")
        with QSignalBlocker(self._grow_edit):
            self._grow_edit.setText(str(settings.grow))
        if not self._grow_edit.hasFocus():
            self._preview_grow_value = int(settings.grow)
        with QSignalBlocker(self._reuse_switch):
            self._reuse_switch.setChecked(bool(settings.reuse_enabled))
        index = self._nsfw_combo.findData(settings.nsfw_mode)
        if index >= 0:
            with QSignalBlocker(self._nsfw_combo):
                self._nsfw_combo.setCurrentIndex(index)
        with QSignalBlocker(self._show_grow_switch):
            self._show_grow_switch.setChecked(bool(settings.show_grow_band))
        with QSignalBlocker(self._show_nsfw_switch):
            self._show_nsfw_switch.setChecked(bool(settings.show_nsfw_marks))

    def _on_setting_changed(self, key: str, value) -> None:
        self._refresh_scope()
        if key in ("conf", "grow", "nsfw_mode"):
            self._sync_controls()
            self._preview_key = None
            entry = self._current_entry()
            if entry:
                self._show_entry(entry)
        if key in ("show_grow_band", "show_nsfw_marks"):
            self._sync_controls()
            self._preview_key = None
            entry = self._current_entry()
            if entry:
                self._show_entry(entry)
            return
        if key == "output_dir":
            self._preview_key = None
            self._disabled = load_disabled(self.store.settings.output_dir) if value else set()
            self._model.set_disabled(self._disabled)
            self._refresh_manual()
            self._refresh_groups(silent=True)
            entry = self._current_entry()
            if entry:
                self._show_entry(entry)
            return
        if key in (
            "input_dir",
            "include_subdirs",
            "conf",
            "imgsz",
            "device",
            "nsfw_mode",
            "mosaic_model",
            "nsfw_model",
        ):
            if not self.controller.running and self.controller.has_results():
                self._set_status(
                    "检测设置已变化，点“重新预处理”将重新识别全部图片", "warn"
                )
                self._start_button.setText(self._idle_text())

    def _on_settings_replaced(self, settings: Settings) -> None:
        self._refresh_scope()
        self._sync_controls()
        self._disabled = load_disabled(settings.output_dir) if settings.output_dir else set()
        self._model.set_disabled(self._disabled)
        self._refresh_manual()
        self._refresh_groups(silent=True)
        if not self.controller.running and self.controller.is_stale(settings):
            self._set_status("输入或检测设置已变化，点“重新预处理”将重新识别全部图片", "warn")
            self._start_button.setText(self._idle_text())

    # ------------------------------------------------------------------ misc
    def _set_status(self, text: str, tone: str) -> None:
        self._status.setText(text)
        self._status.set_tone(tone)

    def _refresh_palette(self, palette: Palette) -> None:
        self._palette = palette
        self._model.set_palette(palette)

    def closeEvent(self, event):  # noqa: N802
        self.controller.stop()
        super().closeEvent(event)
