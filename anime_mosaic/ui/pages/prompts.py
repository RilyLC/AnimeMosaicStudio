"""Prompt page: positive / negative text with guidance and safe resets."""

from __future__ import annotations

from PySide6.QtCore import QSignalBlocker, QTimer, Signal
from PySide6.QtWidgets import (
    QGridLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from ...core.settings import DEFAULT_NEGATIVE, DEFAULT_POSITIVE, NSFW_PROMPT_CLASSES
from ..state import SettingsStore
from ..theme import Palette
from ..widgets.base import Badge, Card
from ..widgets.buttons import Button
from ..widgets.page import Page
from ..widgets.switch import Switch


class PromptEditor(QWidget):
    changed = Signal(str)

    def __init__(self, text: str, palette: Palette, height: int = 120, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._editor = QPlainTextEdit()
        self._editor.setObjectName("PromptEditor")
        self._editor.setPlainText(text)
        self._editor.setFixedHeight(height)
        self._editor.setPlaceholderText("用英文描述，逗号分隔")
        layout.addWidget(self._editor)
        self._editor.textChanged.connect(lambda: self.changed.emit(self._editor.toPlainText()))

    def text(self) -> str:
        return self._editor.toPlainText()

    def set_text(self, text: str) -> None:
        with QSignalBlocker(self._editor):
            self._editor.setPlainText(text)


class PromptsPage(Page):
    notice = Signal(str, str)

    def __init__(self, store: SettingsStore, palette: Palette, parent=None):
        super().__init__(spacing=16)
        self.store = store
        self._palette = palette
        self._syncing = False
        self._dirty: set[str] = set()
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(450)
        self._save_timer.timeout.connect(self._flush)
        self._nsfw_editors: dict[str, QLineEdit] = {}
        self._nsfw_switch: Switch | None = None

        self._build()
        self.store.replaced.connect(self.sync_from_store)
        self.store.changed.connect(self._on_store_changed)
        self.sync_from_store(store.settings)

    def _build(self) -> None:
        self.positive_card = self._prompt_card(
            "正向提示词",
            "描述希望模型生成的细节。",
            "sparkles",
            DEFAULT_POSITIVE,
            132,
            "positive",
        )
        self.negative_card = self._prompt_card(
            "负向提示词",
            "列出要避免的内容，例如马赛克、遮挡条与低画质。",
            "shield",
            DEFAULT_NEGATIVE,
            96,
            "negative",
        )
        self.add(self.positive_card[0])
        self.add(self.negative_card[0])
        self.add(self._build_nsfw_card())

        tips = Card("提示词小贴士", "改一处、跑一张，更容易判断效果", "info", self._palette)
        for text in (
            "正向词描述“想要什么”：uncensored、detailed anatomy、best quality。",
            "负向词描述“不要什么”：censored、bar censor、mosaic censoring、blurry。",
            "原图会直接送给 ComfyUI，无需在提示词里复述构图。",
            "改完建议先用“快速”预设跑 1–3 张，确认稳定后再全量。",
        ):
            label = QLabel("•  " + text)
            label.setObjectName("FormHelp")
            label.setWordWrap(True)
            tips.body.addWidget(label)
        self.add(tips)

    def _build_nsfw_card(self) -> Card:
        settings = self.store.settings
        card = Card(
            "NSFW 部位提示词",
            "可选：按当前图实际检出的部位追加到正向提示词，不改变检测结果。",
            "shield",
            self._palette,
        )
        self._nsfw_switch = Switch(bool(settings.nsfw_prompt_enabled), self._palette)
        card.add_action(QLabel("启用注入"))
        card.add_action(self._nsfw_switch)
        self._nsfw_switch.toggled.connect(
            lambda checked: self.store.set("nsfw_prompt_enabled", bool(checked))
        )

        grid_host = QWidget()
        grid = QGridLayout(grid_host)
        grid.setContentsMargins(0, 2, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(8)
        labels = {
            "pussy": "小穴 pussy",
            "anus": "肛门 anus",
            "penis": "阴茎 penis",
            "testicles": "睾丸 testicles",
        }
        for index, name in enumerate(NSFW_PROMPT_CLASSES):
            row, col = divmod(index, 2)
            label = QLabel(labels[name])
            label.setObjectName("FormLabel")
            edit = QLineEdit(str(getattr(settings, f"nsfw_prompt_{name}", name)))
            edit.setPlaceholderText(name)
            edit.setMinimumHeight(34)
            edit.setToolTip("留空则不注入；多个词用英文逗号分隔")
            edit.textChanged.connect(
                lambda value, key=f"nsfw_prompt_{name}": self._on_edited(key, value)
            )
            self._nsfw_editors[name] = edit
            grid.addWidget(label, row * 2, col)
            grid.addWidget(edit, row * 2 + 1, col)
        card.add(grid_host)
        hint = QLabel("当前检测器只会输出 pussy / anus / penis / testicles 四类")
        hint.setObjectName("FormHelp")
        hint.setWordWrap(True)
        card.body.addWidget(hint)
        return card

    def _prompt_card(
        self,
        title: str,
        subtitle: str,
        icon: str,
        default: str,
        height: int,
        key: str,
    ):
        card = Card(title, subtitle, icon, self._palette)
        badge = Badge(f"{len(default)} 字符", "neutral")
        card.add_action(badge)
        reset = Button("恢复默认", "link", "refresh", self._palette, size="sm")
        reset.clicked.connect(lambda _, k=key, d=default: self._reset_prompt(k, d))
        card.add_action(reset)
        editor = PromptEditor(default, self._palette, height)
        editor.changed.connect(lambda value, k=key: self._on_edited(k, value))
        card.add(editor)
        return card, editor, badge

    # ---------------------------------------------------------------- events
    def _on_edited(self, key: str, value: str) -> None:
        if self._syncing:
            return
        self._dirty.add(key)
        if key == "positive":
            self.positive_card[2].setText(f"{len(value)} 字符")
        elif key == "negative":
            self.negative_card[2].setText(f"{len(value)} 字符")
        self._save_timer.start()

    def _editor_for(self, key: str) -> QLineEdit | QPlainTextEdit | None:
        if key == "positive":
            return self.positive_card[1]._editor
        if key == "negative":
            return self.negative_card[1]._editor
        if key.startswith("nsfw_prompt_"):
            return self._nsfw_editors.get(key.removeprefix("nsfw_prompt_"))
        return None

    def _flush(self) -> None:
        for key in list(self._dirty):
            editor = self._editor_for(key)
            if editor is not None:
                self.store.set(key, editor.text())
        self._dirty.clear()

    def _reset_prompt(self, key: str, default: str) -> None:
        editor = self.positive_card[1] if key == "positive" else self.negative_card[1]
        editor.set_text(default)
        self.store.set(key, default)
        badge = self.positive_card[2] if key == "positive" else self.negative_card[2]
        badge.setText(f"{len(default)} 字符")
        self.notice.emit("已恢复默认提示词", "info")

    def _on_store_changed(self, key: str, value) -> None:
        if self._syncing:
            return
        if key == "nsfw_prompt_enabled":
            if self._nsfw_switch is not None and self._nsfw_switch.isChecked() != bool(value):
                self._nsfw_switch.setChecked(bool(value))
            return
        if key not in ("positive", "negative") and not key.startswith("nsfw_prompt_"):
            return
        editor = self._editor_for(key)
        if editor is None or editor.text() == value:
            return
        self._syncing = True
        try:
            editor.setPlainText(value) if isinstance(editor, QPlainTextEdit) else editor.setText(value)
        finally:
            self._syncing = False

    def sync_from_store(self, settings) -> None:
        self._syncing = True
        try:
            self.positive_card[1].set_text(settings.positive)
            self.negative_card[1].set_text(settings.negative)
            if self._nsfw_switch is not None:
                self._nsfw_switch.setChecked(bool(settings.nsfw_prompt_enabled))
            for name, editor in self._nsfw_editors.items():
                editor.setText(str(getattr(settings, f"nsfw_prompt_{name}", "")))
        finally:
            self._syncing = False
        self.positive_card[2].setText(f"{len(settings.positive)} 字符")
        self.negative_card[2].setText(f"{len(settings.negative)} 字符")

    def apply_palette(self, palette: Palette) -> None:
        self._palette = palette
        self.positive_card[0].set_palette(palette)
        self.negative_card[0].set_palette(palette)
        if self._nsfw_switch is not None:
            self._nsfw_switch.set_palette(palette)
