"""About page: what the project is, how it works, and its license."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QVBoxLayout

from ... import __version__
from ..theme import Palette
from ..widgets.base import Badge, Card
from ..widgets.page import Page
from ..widgets.sidebar import LogoMark

STEPS = (
    ("检测", "YOLO 分割模型找出马赛克区域，生成像素级黑白遮罩。"),
    ("裁切", "按最小裁切占比与背景倍数均匀外扩窗口，并把相邻区域合并为一次生成。"),
    ("重绘", "autoMosaic 工作流把裁切图与遮罩送入 ComfyUI 重绘。"),
    ("融合", "结果缩放回原尺寸，用无缝克隆或 Laplacian 融合贴回原图。"),
    ("保存", "保留原格式、EXIF、ICC 与透明通道，按原目录结构写出。"),
)


class StepCard(QFrame):
    def __init__(self, number: int, title: str, text: str, parent=None):
        super().__init__(parent)
        self.setObjectName("Inset")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(11)
        badge = QLabel(str(number))
        badge.setObjectName("StepNumber")
        badge.setAlignment(Qt.AlignCenter)
        badge.setFixedSize(26, 26)
        layout.addWidget(badge, 0, Qt.AlignTop)
        texts = QVBoxLayout()
        texts.setSpacing(2)
        label = QLabel(title)
        label.setObjectName("FormLabel")
        body = QLabel(text)
        body.setObjectName("FormHelp")
        body.setWordWrap(True)
        texts.addWidget(label)
        texts.addWidget(body)
        layout.addLayout(texts, 1)


class AboutPage(Page):
    def __init__(self, palette: Palette, parent=None):
        super().__init__(spacing=16)
        self._palette = palette

        hero = Card()
        hero_layout = QHBoxLayout()
        hero_layout.setSpacing(18)
        self._logo = LogoMark(palette, 56)
        hero_layout.addWidget(self._logo, 0, Qt.AlignTop)
        texts = QVBoxLayout()
        texts.setSpacing(4)
        title = QLabel("AnimeMosaicStudio")
        title.setObjectName("PageTitle")
        texts.addWidget(title)
        subtitle = QLabel(
            "一个面向 ComfyUI 的本地批量去码工具：只重绘被遮挡的区域，"
            "保留原图尺寸、格式与目录结构。"
        )
        subtitle.setObjectName("PageSubtitle")
        subtitle.setWordWrap(True)
        texts.addWidget(subtitle)
        badges = QHBoxLayout()
        badges.setSpacing(6)
        for text, tone in (
            ("PySide6", "accent"),
            ("ComfyUI", "info"),
            (f"v{__version__}", "neutral"),
            ("MIT", "success"),
        ):
            badges.addWidget(Badge(text, tone))
        badges.addStretch(1)
        texts.addLayout(badges)
        hero_layout.addLayout(texts, 1)
        hero.add_layout(hero_layout)
        self.add(hero)

        principles = Card(
            "设计原则",
            "Local-first、非破坏、可扩展。",
            "shield",
            palette,
        )
        for title_text, body_text in (
            ("本地优先", "图片与提示词只在本机与你的 ComfyUI 之间流转，不上传第三方服务。"),
            ("非破坏", "输入目录只读；输出目录按相对路径镜像，原图不会被覆盖。"),
            ("可恢复", "处理清单、预处理遮罩与输出状态均落盘，可中断、可复盘、可继续。"),
            ("可扩展", "core 不依赖 Qt，检测、裁切、融合与提示词均可独立替换。"),
        ):
            row = QVBoxLayout()
            row.setSpacing(1)
            label = QLabel(title_text)
            label.setObjectName("FormLabel")
            body = QLabel(body_text)
            body.setObjectName("FormHelp")
            body.setWordWrap(True)
            row.addWidget(label)
            row.addWidget(body)
            principles.add_layout(row)
        self.add(principles)

        flow = Card(
            "处理流程",
            "先预处理确认遮罩，再开始批量重绘；全程可暂停、取消与重跑单张。",
            "layers",
            palette,
        )
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)
        for index, (title_text, body_text) in enumerate(STEPS):
            grid.addWidget(StepCard(index + 1, title_text, body_text), index // 2, index % 2)
        flow.add_layout(grid)
        self.add(flow)

        license_card = Card("开源许可", "MIT License", "file", palette)
        license_text = QLabel(
            "Copyright (c) 2026 AnimeMosaicStudio contributors\n\n"
            "Permission is hereby granted, free of charge, to any person obtaining a copy "
            "of this software and associated documentation files, to deal in the Software "
            "without restriction, including without limitation the rights to use, copy, "
            "modify, merge, publish, distribute, sublicense, and/or sell copies of the "
            "Software, subject to the conditions of the MIT License."
        )
        license_text.setObjectName("FormHelp")
        license_text.setWordWrap(True)
        license_card.add(license_text)
        self.add(license_card)

    def apply_palette(self, palette: Palette) -> None:
        self._palette = palette
        self._logo.set_palette(palette)
        for card in self.findChildren(Card):
            card.set_palette(palette)
