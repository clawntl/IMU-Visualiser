"""Background serial reader. Runs on a QThread so the GUI never blocks on
readline(), and can be told to stop/reconnect cleanly."""

from __future__ import annotations

import re
import time

import serial
from PySide6.QtCore import QThread, Signal

FIELD_SPLIT_RE = re.compile(r"[;,\s]+")


class SerialWorker(QThread):
    quaternionReceived = Signal(float, float, float, float)
    eulerReceived = Signal(float, float, float)
    rawLine = Signal(str)
    errorOccurred = Signal(str)
    connected = Signal()
    disconnected = Signal(str)  # reason ("" for a clean user-requested close)

    def __init__(self, port: str, baudrate: int, mode: str, parent=None):
        super().__init__(parent)
        self.port = port
        self.baudrate = baudrate
        self.mode = mode  # "quaternion" or "euler"
        self._stop_requested = False
        self._had_error = False
        self.ser: serial.Serial | None = None

    def request_stop(self):
        self._stop_requested = True

    def send(self, text: str) -> bool:
        """Write a line to the device. Safe to call from the GUI thread
        while this worker is reading in the background. Returns False if
        not currently connected."""
        ser = self.ser
        if ser is None or not ser.is_open:
            return False
        try:
            ser.write((text + "\n").encode("ascii", errors="ignore"))
            return True
        except serial.SerialException as exc:
            self.errorOccurred.emit(str(exc))
            return False

    def run(self):
        try:
            ser = serial.Serial(self.port, baudrate=self.baudrate, timeout=0.25)
        except serial.SerialException as exc:
            self.errorOccurred.emit(str(exc))
            self.disconnected.emit(str(exc))
            return

        self.ser = ser

        try:
            time.sleep(1.5)  # let an ESP32/Arduino finish its reset-on-open
            ser.reset_input_buffer()
        except serial.SerialException:
            pass

        self.connected.emit()

        expected_fields = 4 if self.mode == "quaternion" else 3

        while not self._stop_requested:
            try:
                raw = ser.readline()
            except serial.SerialException as exc:
                self.errorOccurred.emit(str(exc))
                self._had_error = True
                break

            if not raw:
                continue

            try:
                text = raw.decode("ascii", errors="ignore").strip()
            except UnicodeDecodeError:
                continue

            if not text:
                continue

            self.rawLine.emit(text)

            parts = [p for p in FIELD_SPLIT_RE.split(text) if p]
            if len(parts) != expected_fields:
                continue

            try:
                values = [float(p) for p in parts]
            except ValueError:
                continue

            if self.mode == "quaternion":
                self.quaternionReceived.emit(*values)
            else:
                self.eulerReceived.emit(*values)

        self.ser = None
        try:
            ser.close()
        except serial.SerialException:
            pass

        if self._had_error and not self._stop_requested:
            self.disconnected.emit("Connection lost")
        else:
            self.disconnected.emit("")
