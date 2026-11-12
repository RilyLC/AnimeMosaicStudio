"""Single observable owner of the application settings."""

from __future__ import annotations

from PySide6.QtCore import QObject, QTimer, Signal

from ..core.settings import CONFIG_PATH, Settings, load_settings, save_settings
from ..services.presets import PRESET_VALUE_KEYS, remember_preset_values


class SettingsStore(QObject):
    """Holds an immutable ``Settings`` snapshot and persists changes.

    Pages write through :meth:`set`/:meth:`update` and listen to :attr:`changed`
    or :attr:`replaced`; they never mutate settings directly.
    """

    changed = Signal(str, object)
    replaced = Signal(object)
    saved = Signal()

    def __init__(
        self,
        settings: Settings | None = None,
        path: str = CONFIG_PATH,
        autosave: bool = True,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self._path = path
        self._settings = settings or Settings()
        self._autosave = autosave
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(600)
        self._save_timer.timeout.connect(self.save_now)
        self._dirty = False

    @property
    def settings(self) -> Settings:
        return self._settings

    @property
    def dirty(self) -> bool:
        return self._dirty

    def get(self, key: str):
        return getattr(self._settings, key)

    def set(self, key: str, value) -> bool:
        try:
            updated = self._settings.merged(**{key: value})
        except (KeyError, TypeError, ValueError):
            return False
        if getattr(updated, key) == getattr(self._settings, key):
            return False
        if key in PRESET_VALUE_KEYS:
            # Editing a preset-owned value keeps the preset active and saves the
            # change into that preset instead of silently switching to custom.
            updated = remember_preset_values(updated)
        self._settings = updated
        self._dirty = True
        self.changed.emit(key, getattr(updated, key))
        self._schedule_save()
        return True

    def update(self, values: dict) -> bool:
        try:
            updated = self._settings.merged(**values)
        except (KeyError, TypeError, ValueError):
            return False
        if updated == self._settings:
            return False
        self._settings = updated
        self._dirty = True
        self.replaced.emit(updated)
        self._schedule_save()
        return True

    def replace(self, settings: Settings) -> None:
        self._settings = settings
        self._dirty = True
        self.replaced.emit(settings)
        self._schedule_save()

    def reset(self) -> None:
        self.replace(Settings())

    def reload(self) -> None:
        self.replace(load_settings(self._path))

    def save_now(self) -> None:
        self._save_timer.stop()
        save_settings(self._settings, self._path)
        self._dirty = False
        self.saved.emit()

    def _schedule_save(self) -> None:
        if self._autosave:
            self._save_timer.start()
