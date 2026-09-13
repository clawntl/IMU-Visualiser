"""Thin wrapper around QSettings so the app remembers the last port, baud
rate, mode, and imported model between runs."""

from __future__ import annotations

from PySide6.QtCore import QSettings

ORG = "IMUViz"
APP = "AccelerometerPlotter"


class AppSettings:
    def __init__(self):
        self._s = QSettings(ORG, APP)

    def get(self, key: str, default=None):
        value = self._s.value(key, default)
        if isinstance(default, bool):
            return str(value).lower() in ("true", "1")
        if isinstance(default, int) and not isinstance(default, bool):
            try:
                return int(value)
            except (TypeError, ValueError):
                return default
        return value

    def set(self, key: str, value) -> None:
        self._s.setValue(key, value)
