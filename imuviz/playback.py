"""Replays a CSV file recorded by SessionRecorder back through the same
orientation pipeline as live serial data, at its original real-time pace."""

from __future__ import annotations

import csv

from PySide6.QtCore import QObject, QTimer, Signal


class PlaybackController(QObject):
    orientationReceived = Signal(float, float, float, float)  # w, x, y, z
    positionChanged = Signal(float, float)  # current_t, total_t
    finished = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[tuple[float, float, float, float, float]] = []
        self._index = 0
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._emit_current)
        self._playing = False

    def load(self, path: str) -> float:
        """Loads a recorded CSV. Returns total duration in seconds (0 if empty)."""
        rows = []
        with open(path, "r", newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                try:
                    rows.append((
                        float(row["t"]), float(row["w"]), float(row["x"]),
                        float(row["y"]), float(row["z"]),
                    ))
                except (KeyError, ValueError):
                    continue

        self._rows = rows
        self._index = 0
        self._playing = False
        self._timer.stop()
        return self.duration

    @property
    def duration(self) -> float:
        return self._rows[-1][0] if self._rows else 0.0

    @property
    def is_playing(self) -> bool:
        return self._playing

    @property
    def has_data(self) -> bool:
        return bool(self._rows)

    def play(self) -> None:
        if not self._rows or self._index >= len(self._rows):
            return
        self._playing = True
        self._schedule_next()

    def pause(self) -> None:
        self._playing = False
        self._timer.stop()

    def stop(self) -> None:
        self._playing = False
        self._timer.stop()
        self._index = 0
        self.positionChanged.emit(0.0, self.duration)

    def _schedule_next(self) -> None:
        if not self._playing or self._index >= len(self._rows):
            return
        delay_ms = 0
        if self._index > 0:
            delay_ms = max(0, int((self._rows[self._index][0] - self._rows[self._index - 1][0]) * 1000))
        self._timer.start(delay_ms)

    def _emit_current(self) -> None:
        if self._index >= len(self._rows):
            self._playing = False
            self.finished.emit()
            return

        t, w, x, y, z = self._rows[self._index]
        self.orientationReceived.emit(w, x, y, z)
        self.positionChanged.emit(t, self.duration)
        self._index += 1

        if self._index >= len(self._rows):
            self._playing = False
            self.finished.emit()
        else:
            self._schedule_next()
