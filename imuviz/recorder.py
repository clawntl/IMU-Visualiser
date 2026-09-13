"""Records live orientation samples to a timestamped CSV file, so a session
can be replayed later (see playback.py) without hardware attached."""

from __future__ import annotations

import csv
import time

import numpy as np

HEADER = ["t", "w", "x", "y", "z", "roll_deg", "pitch_deg", "yaw_deg"]


class SessionRecorder:
    def __init__(self, path: str):
        self._file = open(path, "w", newline="", encoding="utf-8")
        self._writer = csv.writer(self._file)
        self._writer.writerow(HEADER)
        self._t0 = time.monotonic()
        self.sample_count = 0

    def record(self, q: np.ndarray, roll: float, pitch: float, yaw: float) -> float:
        t = time.monotonic() - self._t0
        self._writer.writerow([
            f"{t:.4f}",
            *[f"{v:.6f}" for v in q],
            f"{roll:.3f}", f"{pitch:.3f}", f"{yaw:.3f}",
        ])
        self._file.flush()
        self.sample_count += 1
        return t

    def close(self) -> None:
        self._file.close()
