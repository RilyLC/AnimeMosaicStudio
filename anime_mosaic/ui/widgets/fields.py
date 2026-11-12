"""Form controls generated from :class:`FieldSpec` metadata."""

from __future__ import annotations

from PySide6.QtCore import QLocale, QSignalBlocker, Qt, Signal
from PySide6.QtGui import QDoubleValidator, QIntValidator
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from ...core.settings import FieldSpec
from ..theme import Palette
from .buttons import IconButton
from .switch import Switch


def _form_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("FormLabel")
    return label


def _help_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("FormHelp")
    label.setWordWrap(True)
    return label


class NumberField(QWidget):
    """A label, a precise numeric entry and (optionally) a slider.

    A plain ``QLineEdit`` with a validator is used instead of ``QSpinBox``:
    Qt's stylesheet layout for spin boxes collapses the internal editor, and
    this form gives us full control over presentation and validation.
    """

    valueChanged = Signal(object)

    def __init__(self, spec: FieldSpec, value, palette: Palette | None = None, parent=None):
        super().__init__(parent)
        self.spec = spec
        self._palette = palette
        self._updating = False
        self._is_float = spec.kind == "float"
        self._value = self._clamp(value)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        top = QHBoxLayout()
        top.setSpacing(6)
        top.addWidget(_form_label(spec.label), 1)
        edit = QLineEdit()
        edit.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        edit.setFixedWidth(92)
        edit.setMinimumHeight(36)
        if self._is_float:
            validator = QDoubleValidator(float(spec.minimum or 0), float(spec.maximum or 1e9), spec.decimals, self)
            validator.setNotation(QDoubleValidator.StandardNotation)
            validator.setLocale(QLocale.c())
        else:
            validator = QIntValidator(int(spec.minimum or 0), int(spec.maximum or 2**31 - 1), self)
        validator.setLocale(QLocale.c())
        edit.setValidator(validator)
        edit.editingFinished.connect(self._commit_text)
        edit.returnPressed.connect(self._commit_text)
        self._edit = edit
        top.addWidget(edit, 0)
        if spec.suffix:
            suffix = QLabel(spec.suffix)
            suffix.setObjectName("Caption")
            top.addWidget(suffix, 0)
        root.addLayout(top)

        self._slider: QSlider | None = None
        if spec.slider and spec.minimum is not None and spec.maximum is not None:
            slider = QSlider(Qt.Horizontal)
            slider.setCursor(Qt.PointingHandCursor)
            steps = max(1, int(round((spec.maximum - spec.minimum) / spec.step)))
            slider.setRange(0, steps)
            slider.setPageStep(max(1, steps // 10))
            self._slider = slider
            root.addWidget(slider)
            slider.valueChanged.connect(self._on_slider)

        if spec.help:
            root.addWidget(_help_label(spec.help))

        self.set_value(self._value)

    # ------------------------------------------------------------------ api
    def value(self):
        return self._value

    def set_value(self, value) -> None:
        value = self._clamp(value)
        self._value = value
        self._updating = True
        try:
            with QSignalBlocker(self._edit):
                self._edit.setText(self._format(value))
            if self._slider is not None:
                with QSignalBlocker(self._slider):
                    self._slider.setValue(self._to_slider(value))
        finally:
            self._updating = False

    # -------------------------------------------------------------- internal
    def _clamp(self, value):
        try:
            number = float(value)
        except (TypeError, ValueError):
            return 0.0 if self._is_float else 0
        if self.spec.minimum is not None:
            number = max(float(self.spec.minimum), number)
        if self.spec.maximum is not None:
            number = min(float(self.spec.maximum), number)
        if self._is_float:
            return round(number, self.spec.decimals)
        return int(round(number))

    def _format(self, value) -> str:
        if self._is_float:
            return f"{float(value):.{self.spec.decimals}f}"
        return str(int(value))

    def _to_slider(self, value) -> int:
        if self.spec.minimum is None or self.spec.step <= 0:
            return 0
        return int(round((float(value) - self.spec.minimum) / self.spec.step))

    def _from_slider(self, position: int):
        value = (self.spec.minimum or 0) + position * self.spec.step
        return self._clamp(round(value, self.spec.decimals + 2) if self._is_float else round(value))

    def _commit_text(self) -> None:
        if self._updating:
            return
        text = self._edit.text().replace(",", "").strip()
        try:
            value = float(text) if self._is_float else int(float(text))
        except ValueError:
            self.set_value(self._value)
            return
        value = self._clamp(value)
        changed = value != self._value
        self._value = value
        with QSignalBlocker(self._edit):
            self._edit.setText(self._format(value))
        if self._slider is not None:
            with QSignalBlocker(self._slider):
                self._slider.setValue(self._to_slider(value))
        if changed:
            self.valueChanged.emit(value)

    def _on_slider(self, position: int) -> None:
        if self._updating:
            return
        value = self._from_slider(position)
        self._value = value
        with QSignalBlocker(self._edit):
            self._edit.setText(self._format(value))
        self.valueChanged.emit(value)

    def set_palette(self, palette: Palette) -> None:
        self._palette = palette


class ChoiceField(QWidget):
    valueChanged = Signal(str)

    def __init__(self, spec: FieldSpec, value, palette: Palette | None = None, parent=None):
        super().__init__(parent)
        self.spec = spec
        self._updating = False
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        top = QHBoxLayout()
        top.setSpacing(10)
        top.addWidget(_form_label(spec.label), 1)
        combo = QComboBox()
        combo.setMinimumWidth(190)
        combo.setMinimumHeight(36)
        for choice in spec.choices:
            combo.addItem(choice.label, choice.value)
            if choice.help:
                combo.setItemData(combo.count() - 1, choice.help, Qt.ToolTipRole)
        self._combo = combo
        top.addWidget(combo, 0)
        root.addLayout(top)

        if spec.help:
            root.addWidget(_help_label(spec.help))

        combo.currentIndexChanged.connect(self._on_index)
        self.set_value(value)

    def value(self) -> str:
        data = self._combo.currentData()
        return str(data) if data is not None else ""

    def set_value(self, value) -> None:
        self._updating = True
        try:
            index = self._combo.findData(value)
            if index >= 0:
                with QSignalBlocker(self._combo):
                    self._combo.setCurrentIndex(index)
        finally:
            self._updating = False

    def _on_index(self, index: int) -> None:
        if self._updating or index < 0:
            return
        self.valueChanged.emit(str(self._combo.itemData(index)))

    def set_palette(self, palette: Palette) -> None:
        pass


class SwitchField(QWidget):
    valueChanged = Signal(bool)

    def __init__(self, spec: FieldSpec, value: bool, palette: Palette | None = None, parent=None):
        super().__init__(parent)
        self.spec = spec
        self._updating = False
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(5)

        top = QHBoxLayout()
        top.setSpacing(10)
        top.addWidget(_form_label(spec.label), 1)
        switch = Switch(bool(value), palette)
        self._switch = switch
        top.addWidget(switch, 0, Qt.AlignVCenter)
        root.addLayout(top)
        if spec.help:
            root.addWidget(_help_label(spec.help))
        switch.toggled.connect(self._on_toggled)

    def value(self) -> bool:
        return self._switch.isChecked()

    def set_value(self, value: bool) -> None:
        self._updating = True
        try:
            with QSignalBlocker(self._switch):
                self._switch.setChecked(bool(value))
            self._switch.set_position(1.0 if value else 0.0)
        finally:
            self._updating = False

    def _on_toggled(self, checked: bool) -> None:
        if not self._updating:
            self.valueChanged.emit(bool(checked))

    def set_palette(self, palette: Palette) -> None:
        self._switch.set_palette(palette)


class PathRow(QWidget):
    """Label + path line edit + native picker, used for folders and files."""

    pathChanged = Signal(str)

    def __init__(
        self,
        label: str,
        path: str = "",
        mode: str = "file",
        file_filter: str = "所有文件 (*.*)",
        palette: Palette | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self._mode = mode
        self._filter = file_filter
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(5)

        top = QHBoxLayout()
        top.setSpacing(8)
        top.addWidget(_form_label(label), 1)
        self._edit = QLineEdit(path)
        self._edit.setMinimumHeight(36)
        self._edit.setPlaceholderText("点击右侧按钮选择，或直接粘贴路径")
        top.addWidget(self._edit, 3)
        browse = IconButton(
            "folder",
            "浏览…" if mode == "dir" else "选择文件…",
            palette,
            size=36,
            icon_size=17,
        )
        browse.clicked.connect(self._browse)
        self._browse_button = browse
        top.addWidget(browse, 0)
        root.addLayout(top)

        self._edit.editingFinished.connect(self._emit)
        if palette is not None:
            self._palette = palette

    def set_palette(self, palette: Palette) -> None:
        self._browse_button.set_palette(palette)

    def path(self) -> str:
        return self._edit.text().strip()

    def set_path(self, path: str) -> None:
        with QSignalBlocker(self._edit):
            self._edit.setText(path or "")

    def _emit(self) -> None:
        self.pathChanged.emit(self.path())

    def _browse(self) -> None:
        current = self.path()
        if self._mode == "dir":
            selected = QFileDialog.getExistingDirectory(self, "选择文件夹", current)
        else:
            selected, _ = QFileDialog.getOpenFileName(self, "选择文件", current, self._filter)
        if selected:
            self.set_path(selected)
            self._emit()


class TextField(QWidget):
    valueChanged = Signal(str)

    def __init__(self, label: str, value: str = "", placeholder: str = "", parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(5)
        root.addWidget(_form_label(label))
        self._edit = QLineEdit(value)
        self._edit.setPlaceholderText(placeholder)
        self._edit.setMinimumHeight(36)
        root.addWidget(self._edit)
        self._edit.textChanged.connect(self.valueChanged.emit)

    def value(self) -> str:
        return self._edit.text()

    def set_value(self, value: str) -> None:
        with QSignalBlocker(self._edit):
            self._edit.setText(value)
