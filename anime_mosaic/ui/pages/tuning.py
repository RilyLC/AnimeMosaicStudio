"""Tuning page: presets plus sampling, detection, crop, advanced and blend controls."""

from __future__ import annotations

from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ...core.settings import (
    GROUP_BLEND,
    GROUP_BLEND_LAPLACIAN,
    GROUP_BLEND_SEAMLESS,
    GROUP_CROP,
    GROUP_DETECTION,
    GROUP_SAMPLING,
    Settings,
    specs_in_group,
)
from ...services.presets import (
    CUSTOM_PRESET_ID,
    PRESET_CHOICES,
    Preset,
    preset_by_id,
    preset_values,
    resolve_preset_id,
    restore_preset_defaults,
)
from ..state import SettingsStore
from ..theme import Palette
from ..widgets.base import Badge, Card, IconTile
from ..widgets.buttons import Button
from ..widgets.fields import ChoiceField, NumberField
from ..widgets.page import Page
from ..widgets.switch import Switch


class PresetCard(QFrame):
    clicked = Signal()
    restoreRequested = Signal(str)

    def __init__(self, preset: Preset, palette: Palette, icon: str, parent=None):
        super().__init__(parent)
        self.setObjectName("PresetCard")
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAttribute(Qt.WA_Hover, True)
        self.preset = preset
        self.setProperty("selected", "false")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 13, 14, 13)
        layout.setSpacing(11)
        self._tile = IconTile(icon, palette, 34)
        layout.addWidget(self._tile, 0, Qt.AlignTop)
        texts = QVBoxLayout()
        texts.setSpacing(2)
        top = QHBoxLayout()
        top.setSpacing(7)
        title = QLabel(preset.label)
        title.setObjectName("CardTitle")
        top.addWidget(title)
        top.addWidget(Badge(preset.tagline, "accent"))
        top.addStretch(1)
        restore = Button("恢复默认", "link", "refresh", palette, size="sm")
        restore.setToolTip(f"把「{preset.label}」恢复为默认参数")
        restore.setVisible(preset.id != CUSTOM_PRESET_ID)
        restore.clicked.connect(lambda: self.restoreRequested.emit(preset.id))
        top.addWidget(restore)
        texts.addLayout(top)
        desc = QLabel(preset.description)
        desc.setObjectName("FormHelp")
        desc.setWordWrap(True)
        texts.addWidget(desc)
        layout.addLayout(texts, 1)

    def set_selected(self, selected: bool) -> None:
        self.setProperty("selected", "true" if selected else "false")
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def keyPressEvent(self, event):  # noqa: N802
        if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.clicked.emit()
        else:
            super().keyPressEvent(event)

    def set_palette(self, palette: Palette) -> None:
        self._tile.set_palette(palette)


class TuningPage(Page):
    notice = Signal(str, str)

    def __init__(self, store: SettingsStore, palette: Palette, parent=None):
        super().__init__(spacing=16)
        self.store = store
        self._palette = palette
        self._fields: dict[str, QWidget] = {}
        self._preset_cards: dict[str, PresetCard] = {}
        self._blend_sections: dict[str, QWidget] = {}

        self._build_presets()
        self._build_fields()
        self._connect()
        self.sync_from_store(store.settings)

    # ----------------------------------------------------------------- build
    def _build_presets(self) -> None:
        card = Card(
            "预设",
            "四个预设各自记住整页参数（检测、裁切、采样、融合）；点卡片切换，改动会保存在当前预设里。",
            "wand",
            self._palette,
        )
        reset = Button("恢复默认参数", "link", "refresh", self._palette, size="sm")
        reset.clicked.connect(self._reset_parameters)
        card.add_action(reset)
        row = QHBoxLayout()
        row.setSpacing(12)
        icons = {"fast": "zap", "balanced": "gauge", "quality": "gem", "custom": "sliders"}
        for preset in PRESET_CHOICES:
            widget = PresetCard(preset, self._palette, icons.get(preset.id, "sparkles"))
            widget.clicked.connect(lambda p=preset: self._apply_preset(p))
            widget.restoreRequested.connect(self._restore_preset)
            self._preset_cards[preset.id] = widget
            row.addWidget(widget, 1)
        card.add_layout(row)
        self.add(card)

    def _build_fields(self) -> None:
        detection = self._field_card(
            "检测", "YOLO 如何找到马赛克与遮挡条", "cpu", GROUP_DETECTION
        )
        cropping = self._field_card(
            "裁切", "决定每个马赛克周围带入多少画面", "scan", GROUP_CROP
        )
        crop_note = QLabel(
            "“最小裁切占比”给小马赛克保底背景，“背景倍数”让大马赛克也按比例留白；"
            "最终窗口取两者中较大的面积，再以区域为中心取正方形（放不下时才回退非方形），"
            "不会把马赛克裁掉。"
        )
        crop_note.setObjectName("FormHelp")
        crop_note.setWordWrap(True)
        cropping.body.addWidget(crop_note)

        sampling = self._field_card(
            "采样", "决定细节、速度与显存占用", "sliders", GROUP_SAMPLING
        )
        blending = self._field_card(
            "融合", "把重绘结果贴回原图的方式", "layers", GROUP_BLEND
        )
        self._add_blend_section(
            blending,
            "无缝融合（Poisson）",
            "泊松求解把生成图的颜色拉向周围画面；强度控制贴合程度，"
            "边缘过渡控制遮罩内侧的锐度。",
            GROUP_BLEND_SEAMLESS,
        )
        self._add_blend_section(
            blending,
            "多频段融合（Laplacian）",
            "层数决定过渡宽度，羽化决定遮罩边缘软硬；细节、过渡曲线与低频保护"
            "进一步调整贴回后的质感。",
            GROUP_BLEND_LAPLACIAN,
            columns=2,
        )
        self._fields["blend"].valueChanged.connect(self._update_blend_sections)

        # 两列纵向排布：卡片按内容收缩，短卡片不会再被等高网格拉出大片空白。
        left = QVBoxLayout()
        left.setSpacing(16)
        left.addWidget(detection)
        left.addWidget(sampling)
        right = QVBoxLayout()
        right.setSpacing(16)
        right.addWidget(cropping)
        right.addWidget(blending)

        columns = QHBoxLayout()
        columns.setSpacing(16)
        columns.addLayout(left, 1)
        columns.addLayout(right, 1)
        self.add_layout(columns)
        self._update_blend_sections(self.store.get("blend"))

        footnote = QLabel(
            "这些参数会在每次开始处理时写入 config.json；"
            "命令行可用 --conf / --size / --steps 等覆盖。"
        )
        footnote.setObjectName("FormHelp")
        footnote.setWordWrap(True)
        self.add(footnote)

    def _make_field(self, spec) -> QWidget:
        if spec.kind == "choice":
            widget = ChoiceField(spec, getattr(self.store.settings, spec.key), self._palette)
        else:
            widget = NumberField(spec, getattr(self.store.settings, spec.key), self._palette)
        widget.valueChanged.connect(
            lambda value, key=spec.key: self._on_field_changed(key, value)
        )
        self._fields[spec.key] = widget
        return widget

    def _field_card(
        self, title: str, subtitle: str, icon: str, group: str, columns: int = 1
    ) -> Card:
        card = Card(title, subtitle, icon, self._palette)
        card.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        specs = list(specs_in_group(group))
        if columns <= 1:
            for spec in specs:
                card.add(self._make_field(spec))
            return card
        fields = QGridLayout()
        fields.setHorizontalSpacing(16)
        fields.setVerticalSpacing(10)
        for index, spec in enumerate(specs):
            fields.addWidget(self._make_field(spec), index // columns, index % columns)
        for column in range(columns):
            fields.setColumnStretch(column, 1)
        card.add_layout(fields)
        return card

    def _add_blend_section(
        self, card: Card, title: str, help_text: str, group: str, columns: int = 1
    ) -> None:
        section = QWidget()
        layout = QVBoxLayout(section)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(8)
        heading = QLabel(title)
        heading.setObjectName("FormLabel")
        layout.addWidget(heading)
        hint = QLabel(help_text)
        hint.setObjectName("FormHelp")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        fields = QGridLayout()
        fields.setHorizontalSpacing(16)
        fields.setVerticalSpacing(10)
        for index, spec in enumerate(specs_in_group(group)):
            fields.addWidget(
                self._make_field(spec), index // columns, index % columns
            )
        for column in range(columns):
            fields.setColumnStretch(column, 1)
        layout.addLayout(fields)
        card.body.addWidget(section)
        self._blend_sections[group] = section

    def _update_blend_sections(self, mode: str) -> None:
        if GROUP_BLEND_SEAMLESS in self._blend_sections:
            self._blend_sections[GROUP_BLEND_SEAMLESS].setVisible(mode == "seamless")
        if GROUP_BLEND_LAPLACIAN in self._blend_sections:
            self._blend_sections[GROUP_BLEND_LAPLACIAN].setVisible(mode == "laplacian")

    def _connect(self) -> None:
        self.store.changed.connect(self._on_changed)
        self.store.replaced.connect(self.sync_from_store)

    # ------------------------------------------------------------------ api
    def _apply_preset(self, preset: Preset) -> None:
        values = preset_values(self.store.settings, preset.id)
        self.store.update({"preset": preset.id, **values})
        if preset.id == CUSTOM_PRESET_ID:
            self.notice.emit("已切换到「自定义」", "info")
        else:
            self.notice.emit(f"已应用「{preset.label}」预设", "success")

    def _restore_preset(self, preset_id: str) -> None:
        settings = self.store.settings
        applied = restore_preset_defaults(settings, preset_id)
        if applied == settings:
            return
        changes = {
            key: getattr(applied, key)
            for key in applied.to_mapping()
            if getattr(applied, key) != getattr(settings, key)
        }
        self.store.update(changes)
        preset = preset_by_id(preset_id)
        if preset is not None:
            self.notice.emit(f"「{preset.label}」已恢复默认值", "success")

    def _on_field_changed(self, key: str, value) -> None:
        # The store saves preset-owned edits into the active preset, so the
        # selection stays on that preset instead of jumping to "custom".
        self.store.set(key, value)

    def _reset_parameters(self) -> None:
        defaults = Settings()
        groups = (
            GROUP_SAMPLING,
            GROUP_DETECTION,
            GROUP_CROP,
            GROUP_BLEND,
            GROUP_BLEND_SEAMLESS,
            GROUP_BLEND_LAPLACIAN,
        )
        keys = {spec.key for group in groups for spec in specs_in_group(group)}
        values = {key: getattr(defaults, key) for key in keys}
        values["preset"] = defaults.preset
        values["preset_values"] = {}
        self.store.update(values)
        self.notice.emit("参数已恢复默认值", "info")

    def sync_from_store(self, settings) -> None:
        for key, widget in self._fields.items():
            value = getattr(settings, key)
            if isinstance(widget, Switch):
                with QSignalBlocker(widget):
                    widget.setChecked(bool(value))
            else:
                widget.set_value(value)
        self._update_blend_sections(settings.blend)
        self._refresh_presets(settings)

    def _on_changed(self, key: str, value) -> None:
        widget = self._fields.get(key)
        if widget is not None:
            if isinstance(widget, Switch):
                with QSignalBlocker(widget):
                    widget.setChecked(bool(value))
            else:
                widget.set_value(value)
        if key == "blend":
            self._update_blend_sections(value)
        self._refresh_presets(self.store.settings)

    def _refresh_presets(self, settings) -> None:
        active = resolve_preset_id(settings)
        for preset_id, card in self._preset_cards.items():
            card.set_selected(preset_id == active)

    def apply_palette(self, palette: Palette) -> None:
        self._palette = palette
        for card in self._preset_cards.values():
            card.set_palette(palette)
