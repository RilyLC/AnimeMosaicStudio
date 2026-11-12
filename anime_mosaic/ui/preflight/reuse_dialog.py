"""Preview and manage candidate differential-reuse groups."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QDoubleValidator, QIntValidator
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...core.manual_mask import encode_mask
from ...core.settings import Settings
from ...services.preflight import entry_core_png, entry_mask_png
from ...services.reuse_groups import ReuseGroup, save_disabled, state_key
from ..state import SettingsStore
from ..theme import Palette
from ..widgets.base import Card
from ..widgets.buttons import Button
from .preview import MaskPreview, compose_preview


class ReuseGroupsDialog(QDialog):
    """Foldable differential-management view.

    Groups are top-level rows; every image in a group is a child row. Unchecking
    a group or a single image writes that rel into the disabled list.
    """

    def __init__(
        self,
        groups: list[ReuseGroup],
        entries_by_rel: dict,
        disabled: set[str],
        output_dir: str,
        palette: Palette,
        parent=None,
        *,
        store: SettingsStore | None = None,
        rebuild=None,
    ):
        super().__init__(parent)
        self._groups = list(groups)
        self._entries = entries_by_rel
        self._disabled = {state_key(rel) for rel in disabled}
        self._output_dir = output_dir
        self._palette = palette
        self._store = store
        self._settings = store.settings if store is not None else Settings()
        self._rebuild = rebuild
        self._param_edits: dict[str, QLineEdit] = {}
        self._loading = False
        self.setObjectName("ReuseGroupsDialog")
        self.setWindowTitle("差分管理")
        self.resize(1040, 640)
        self._build()
        self._fill()
        if self._tree.topLevelItemCount():
            self._tree.setCurrentItem(self._tree.topLevelItem(0))

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(12)

        title = QLabel("差分管理")
        title.setObjectName("PageTitle")
        root.addWidget(title)
        subtitle = QLabel(
            "按预处理遮罩相似度预分组；真正复用前仍会做像素差分校验。"
            "展开组即可看到组内每一张图片；取消整组或单张图片的勾选即可移出，"
            "重新勾选恢复。保存后从下一次处理开始生效。"
        )
        subtitle.setObjectName("PageSubtitle")
        subtitle.setWordWrap(True)
        root.addWidget(subtitle)
        root.addWidget(self._build_params())

        body = QHBoxLayout()
        body.setSpacing(12)

        left = Card("差分组", "展开组查看组内图片；勾选状态决定是否参与复用", "layers", self._palette)
        self._tree = QTreeWidget()
        self._tree.setObjectName("ReuseTree")
        self._tree.setColumnCount(3)
        self._tree.setHeaderLabels(["组 / 图片", "区域", "覆盖"])
        self._tree.setRootIsDecorated(True)
        self._tree.setItemsExpandable(True)
        self._tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self._tree.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._tree.setAlternatingRowColors(True)
        self._tree.setIndentation(18)
        self._tree.setUniformRowHeights(True)
        self._tree.header().setStretchLastSection(False)
        self._tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._tree.header().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._tree.itemChanged.connect(self._on_item_changed)
        self._tree.currentItemChanged.connect(self._preview_selected)
        self._tree.itemClicked.connect(lambda item, _column: self._preview_selected(item))
        left.add(self._tree, 1)
        body.addWidget(left, 3)

        right = Card("组内遮罩", "红色区域为该组共用的马赛克区域", "grid", self._palette)
        self._preview = MaskPreview(self._palette)
        self._preview.setMinimumHeight(240)
        right.add(self._preview, 1)
        self._summary = QLabel("展开并选择一个组查看详情")
        self._summary.setObjectName("Caption")
        self._summary.setWordWrap(True)
        right.add(self._summary)
        hint = QLabel(
            "树中每个子项就是组内的一张图片。取消勾选会把它移出复用组，"
            "行文字变灰；重新勾选即可恢复。"
        )
        hint.setObjectName("FormHelp")
        hint.setWordWrap(True)
        right.add(hint)
        body.addWidget(right, 2)
        root.addLayout(body, 1)

        footer = QHBoxLayout()
        footer.setSpacing(8)
        self._status = QLabel(f"共 {len(self._groups)} 组")
        self._status.setObjectName("Caption")
        footer.addWidget(self._status, 1)
        close = Button("取消", "ghost", None, self._palette)
        close.clicked.connect(self.reject)
        footer.addWidget(close)
        save = Button("保存管理", "primary", "save", self._palette)
        save.clicked.connect(self._save)
        footer.addWidget(save)
        root.addLayout(footer)

    def _build_params(self) -> Card:
        card = Card(
            "差分判定",
            "阈值越严格，可复用组越少；候选组在实际处理时仍会做完整像素校验。",
            "sliders",
            self._palette,
        )
        actions = QWidget()
        action_row = QHBoxLayout(actions)
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.setSpacing(6)
        reset = Button("恢复默认", "ghost", "undo", self._palette, size="sm")
        reset.clicked.connect(self._reset_params)
        action_row.addWidget(reset)
        redetect = Button("重新检测差分", "secondary", "refresh", self._palette, size="sm")
        redetect.setToolTip("按当前判定参数重新计算候选组，不重新检测遮罩")
        redetect.clicked.connect(self._redetect)
        action_row.addWidget(redetect)
        card.add_action(actions)

        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(14)
        specs = (
            ("reuse_max_diff", "最大平均差", "%", "遮罩外区域的平均像素差上限", QDoubleValidator(0.0, 100.0, 2)),
            ("reuse_context_px", "比较上下文", "px", "遮罩外扩多少像素参与比较", QIntValidator(0, 256)),
            ("reuse_min_group_iou", "分组最小 IoU", "", "遮罩重叠度达到该值才归组", QDoubleValidator(0.5, 1.0, 3)),
            ("reuse_min_mask_iou", "复用最小 IoU", "", "实际复用要求的最低重叠度", QDoubleValidator(0.9, 1.0, 3)),
            ("reuse_p99_factor", "99 分位倍数", "×", "允许的极端像素差倍数", QDoubleValidator(1.0, 10.0, 1)),
        )
        for key, label, suffix, help_text, validator in specs:
            block = QVBoxLayout()
            block.setSpacing(3)
            caption = QLabel(label)
            caption.setObjectName("FormLabel")
            block.addWidget(caption)
            value_row = QHBoxLayout()
            value_row.setSpacing(5)
            edit = QLineEdit()
            edit.setValidator(validator)
            edit.setFixedWidth(72)
            edit.setMinimumHeight(30)
            self._param_edits[key] = edit
            value_row.addWidget(edit)
            if suffix:
                unit = QLabel(suffix)
                unit.setObjectName("Caption")
                value_row.addWidget(unit)
            value_row.addStretch(1)
            block.addLayout(value_row)
            help_label = QLabel(help_text)
            help_label.setObjectName("FormHelp")
            help_label.setWordWrap(True)
            block.addWidget(help_label)
            row.addLayout(block, 1)
        card.add(holder)
        self._sync_params()
        return card

    def _sync_params(self) -> None:
        for key, edit in self._param_edits.items():
            value = getattr(self._settings, key)
            text = f"{value:g}" if isinstance(value, float) else str(value)
            edit.setText(text)

    def _param_values(self) -> dict:
        values: dict = {}
        for key, edit in self._param_edits.items():
            text = edit.text().strip()
            if not text:
                raise ValueError("参数不能为空")
            default = getattr(self._settings, key)
            values[key] = float(text) if isinstance(default, float) else int(text)
        return values

    def _reset_params(self) -> None:
        defaults = Settings()
        for key, edit in self._param_edits.items():
            value = getattr(defaults, key)
            edit.setText(f"{value:g}" if isinstance(value, float) else str(value))

    def _redetect(self) -> None:
        if self._rebuild is None:
            return
        try:
            values = self._param_values()
        except ValueError:
            QMessageBox.warning(self, "参数无效", "请检查差分判定参数。")
            return
        try:
            groups = self._rebuild(values["reuse_min_group_iou"])
        except Exception as error:  # noqa: BLE001 - surface a readable dialog
            QMessageBox.warning(self, "重新检测失败", str(error))
            return
        self._groups = list(groups)
        self._fill()
        self._status.setText(f"重新检测完成 · 共 {len(self._groups)} 组")
        if self._tree.topLevelItemCount():
            self._tree.setCurrentItem(self._tree.topLevelItem(0))
        else:
            self._preview.clear()
            self._summary.setText("当前参数下没有可复用的差分候选组")

    # ------------------------------------------------------------------ data
    def _fill(self) -> None:
        self._loading = True
        self._tree.clear()
        for group in self._groups:
            item = QTreeWidgetItem(
                [f"{group.key} · {len(group.rels)} 张", f"{group.regions} 处", f"{group.coverage:.2f}%"]
            )
            item.setFlags(
                Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable
            )
            item.setData(0, Qt.UserRole, ("group", group.key))
            item.setToolTip(0, group.summary)
            for rel in group.rels:
                child = QTreeWidgetItem([rel, "", ""])
                child.setFlags(
                    Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable
                )
                child.setData(0, Qt.UserRole, ("member", rel))
                child.setToolTip(0, rel)
                item.addChild(child)
            self._tree.addTopLevelItem(item)
            item.setExpanded(True)
            self._sync_group_item(item, group)
        self._loading = False

    def _sync_group_item(self, item: QTreeWidgetItem, group: ReuseGroup) -> None:
        was_loading = self._loading
        self._loading = True
        enabled = [rel for rel in group.rels if state_key(rel) not in self._disabled]
        if not enabled:
            state = Qt.Unchecked
        elif len(enabled) == len(group.rels):
            state = Qt.Checked
        else:
            state = Qt.PartiallyChecked
        item.setCheckState(0, state)
        for index in range(item.childCount()):
            child = item.child(index)
            rel = str(child.data(0, Qt.UserRole)[1])
            child_disabled = state_key(rel) in self._disabled
            child.setCheckState(0, Qt.Unchecked if child_disabled else Qt.Checked)
            child_brush = QBrush(
                self._palette.muted if child_disabled else self._palette.text
            )
            for column in range(3):
                child.setForeground(column, child_brush)
        disabled = not enabled
        brush = QBrush(self._palette.muted if disabled else self._palette.text)
        for column in range(3):
            item.setForeground(column, brush)
        self._loading = was_loading

    def _group_for_item(self, item: QTreeWidgetItem | None) -> ReuseGroup | None:
        if item is None:
            return None
        parent = item.parent()
        target = parent if parent is not None else item
        data = target.data(0, Qt.UserRole)
        if not data or data[0] != "group":
            return None
        for group in self._groups:
            if group.key == data[1]:
                return group
        return None

    def _group_item(self, group: ReuseGroup) -> QTreeWidgetItem | None:
        for index in range(self._tree.topLevelItemCount()):
            item = self._tree.topLevelItem(index)
            data = item.data(0, Qt.UserRole)
            if data and data[0] == "group" and data[1] == group.key:
                return item
        return None

    # --------------------------------------------------------------- preview
    def _preview_selected(self, current: QTreeWidgetItem | None, previous=None) -> None:
        group = self._group_for_item(current)
        if group is None:
            self._preview.clear()
            self._summary.setText("展开并选择一个组查看详情")
            return
        data = current.data(0, Qt.UserRole) if current is not None else None
        rel = group.representative
        mask_png = encode_mask(group.mask)
        core_png = None
        if data and data[0] == "member":
            rel = str(data[1])
            entry = self._entries.get(rel)
            if entry is not None:
                data = entry_mask_png(entry)
                if data:
                    mask_png = data
                    core_png = entry_core_png(entry)
        entry = self._entries.get(rel)
        self._summary.setText(
            f"{group.summary}\n当前：{rel} · 组内 {len(group.rels)} 张"
        )
        if entry is None:
            self._preview.clear()
            return
        pixmap = compose_preview(
            entry.path,
            mask_png,
            max_width=520,
            max_height=360,
            grow=0,
            show_grow=False,
            show_nsfw=False,
            core_mask_png=core_png,
        )
        self._preview.show_preview(pixmap)

    # --------------------------------------------------------------- toggles
    def _on_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if self._loading or column != 0:
            return
        data = item.data(0, Qt.UserRole)
        if not data:
            return
        kind, value = data
        if kind == "group":
            group = self._group_for_item(item)
            if group is None:
                return
            checked = item.checkState(0) == Qt.Checked
            for rel in group.rels:
                key = state_key(rel)
                if checked:
                    self._disabled.discard(key)
                else:
                    self._disabled.add(key)
            self._sync_group_item(item, group)
        else:
            rel = str(value)
            key = state_key(rel)
            if item.checkState(0) == Qt.Checked:
                self._disabled.discard(key)
            else:
                self._disabled.add(key)
            group = self._group_for_item(item)
            if group is not None:
                group_item = self._group_item(group)
                if group_item is not None:
                    self._sync_group_item(group_item, group)
        self._status.setText(f"共 {len(self._groups)} 组")

    def _save(self) -> None:
        try:
            values = self._param_values()
        except ValueError:
            QMessageBox.warning(self, "参数无效", "请检查差分判定参数。")
            return
        candidate = self._settings.merged(**values)
        problems = [problem for problem in candidate.validate() if problem.key in values]
        if problems:
            QMessageBox.warning(self, "参数无效", problems[0].message)
            return
        disabled = set(self._disabled)
        if not save_disabled(self._output_dir, disabled):
            QMessageBox.warning(self, "保存失败", "无法写入差分管理状态文件。")
            return
        if self._store is not None:
            self._store.update(values)
        self._disabled = disabled
        self.accept()
