from __future__ import annotations

import time
from collections import deque

import numpy as np
import pyqtgraph as pg
import serial.tools.list_ports
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from . import theme
from .model_loader import ModelLoadError
from .orientation_math import (
    build_axis_remap_matrix,
    euler_deg_to_quat,
    normalize_quat,
    quat_to_euler_deg,
    quat_to_rotation_matrix,
    rotation_matrix_to_quat,
)
from .playback import PlaybackController
from .recorder import SessionRecorder
from .serial_worker import SerialWorker
from .settings import AppSettings
from .viewport import DEFAULT_BOARD_SIZE, Viewport3D

COMMON_BAUD_RATES = ["9600", "19200", "38400", "57600", "115200", "230400", "460800", "921600"]
PLOT_WINDOW_SECONDS = 15.0
LOG_MAX_BLOCKS = 1000
LEFT_PANEL_WIDTH = 380
STALE_DATA_SECONDS = 3.0
RECONNECT_DELAY_MS = 2500
AXIS_OPTIONS = ["+X", "-X", "+Y", "-Y", "+Z", "-Z"]


class StatusDot(QFrame):
    def __init__(self):
        super().__init__()
        self.setFixedSize(12, 12)
        self._state = "off"
        self.set_state("off")

    def set_state(self, state: str):
        self._state = state
        color = {
            "off": theme.TEXT_DIM,
            "good": theme.GOOD,
            "bad": theme.BAD,
            "warn": theme.WARN,
        }.get(state, theme.TEXT_DIM)
        self.setStyleSheet(f"border-radius: 6px; background-color: {color};")

    def refresh(self):
        """Re-applies the current state's color using the current theme
        constants -- call after a theme switch."""
        self.set_state(self._state)


def _value_label(text: str = "--") -> QLabel:
    lbl = QLabel(text)
    lbl.setProperty("role", "value")
    return lbl


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("IMU Orientation Visualizer")
        self.resize(1400, 880)
        self.setMinimumSize(950, 620)

        self.settings = AppSettings()
        self.worker: SerialWorker | None = None
        self._last_connection: tuple[str, int, str] | None = None

        self._latest_R = np.eye(3)
        self._tare_R: np.ndarray | None = None
        self._axis_remap = np.eye(3)
        self._data_dirty = False
        self._sample_count = 0
        self._last_sample_time: float | None = None
        self._is_connected = False
        self._t0 = time.monotonic()
        self._plot_buf = deque()  # (t, roll, pitch, yaw)

        self.recorder: SessionRecorder | None = None
        self.playback = PlaybackController(self)
        self._playback_loaded = False

        self._dark_mode = True
        self._dim_labels: list[tuple[QLabel, bool]] = []
        self.plot_legend = None

        self.viewport = Viewport3D()

        self._build_ui()
        self._wire_up()
        self._restore_settings()

        self.render_timer = QTimer(self)
        self.render_timer.timeout.connect(self._on_render_tick)
        self.render_timer.start(16)

        self.rate_timer = QTimer(self)
        self.rate_timer.timeout.connect(self._on_rate_tick)
        self.rate_timer.start(1000)

        self.reconnect_timer = QTimer(self)
        self.reconnect_timer.setSingleShot(True)
        self.reconnect_timer.timeout.connect(self._attempt_reconnect)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        splitter = QSplitter(Qt.Horizontal)
        root.addWidget(splitter)

        splitter.addWidget(self._build_left_panel())
        splitter.addWidget(self._build_right_panel())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([LEFT_PANEL_WIDTH, 1020])

        self.status_dot = StatusDot()
        self.status_label = QLabel("Disconnected")
        self.rate_label = QLabel("-- Hz")
        self.statusBar().addWidget(self.status_dot)
        self.statusBar().addWidget(self.status_label, 1)
        self.statusBar().addPermanentWidget(self.rate_label)

    def _build_left_panel(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(LEFT_PANEL_WIDTH)
        scroll.setMaximumWidth(LEFT_PANEL_WIDTH + 80)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        header_row = QHBoxLayout()
        heading = QLabel("IMU Orientation Visualizer")
        heading.setProperty("role", "heading")
        heading.setWordWrap(True)
        header_row.addWidget(heading, 1)

        self.theme_toggle_btn = QPushButton("🌙")
        self.theme_toggle_btn.setToolTip("Toggle light/dark theme")
        self.theme_toggle_btn.setMaximumWidth(36)
        header_row.addWidget(self.theme_toggle_btn)
        layout.addLayout(header_row)

        layout.addWidget(self._build_connection_group())
        layout.addWidget(self._build_model_group())
        layout.addWidget(self._build_axis_remap_group())
        layout.addWidget(self._build_orientation_group())
        layout.addWidget(self._build_recording_group())
        layout.addWidget(self._build_readout_group())
        layout.addStretch(1)

        scroll.setWidget(panel)
        return scroll

    def _build_connection_group(self) -> QGroupBox:
        box = QGroupBox("Connection")
        form = QFormLayout(box)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.setLabelAlignment(Qt.AlignLeft)

        port_row = QHBoxLayout()
        self.port_combo = QComboBox()
        self.port_combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.port_combo.setMinimumContentsLength(8)
        self.port_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.setMaximumWidth(70)
        port_row.addWidget(self.port_combo, 1)
        port_row.addWidget(self.refresh_btn)
        form.addRow("Port", port_row)

        self.port_detail_label = QLabel("")
        self.port_detail_label.setWordWrap(True)
        self.port_detail_label.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 11px;")
        self._dim_labels.append((self.port_detail_label, True))
        form.addRow("", self.port_detail_label)

        self.baud_combo = QComboBox()
        self.baud_combo.setEditable(True)
        self.baud_combo.addItems(COMMON_BAUD_RATES)
        self.baud_combo.setCurrentText("115200")
        form.addRow("Baud", self.baud_combo)

        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Quaternion (w, x, y, z)", userData="quaternion")
        self.mode_combo.addItem("Euler angles (roll, pitch, yaw)", userData="euler")
        form.addRow("Data format", self.mode_combo)

        self.connect_btn = QPushButton("Connect")
        self.connect_btn.setProperty("accent", "true")
        form.addRow(self.connect_btn)

        self.auto_reconnect_check = QCheckBox("Auto-reconnect if the device drops")
        self.auto_reconnect_check.setChecked(True)
        form.addRow(self.auto_reconnect_check)

        self._refresh_ports()
        return box

    def _build_model_group(self) -> QGroupBox:
        box = QGroupBox("3D Model")
        layout = QVBoxLayout(box)

        self.model_label = QLabel("Using default board shape")
        self.model_label.setWordWrap(True)
        self.model_label.setStyleSheet(f"color: {theme.TEXT_DIM};")
        self._dim_labels.append((self.model_label, False))
        layout.addWidget(self.model_label)

        self.import_model_btn = QPushButton("Import STL/OBJ...")
        layout.addWidget(self.import_model_btn)

        self.reset_model_btn = QPushButton("Reset to Default Shape")
        layout.addWidget(self.reset_model_btn)

        color_row = QHBoxLayout()
        self.model_color_btn = QPushButton("Model Color...")
        self.model_color_swatch = QFrame()
        self.model_color_swatch.setFixedSize(26, 26)
        color_row.addWidget(self.model_color_btn, 1)
        color_row.addWidget(self.model_color_swatch)
        layout.addLayout(color_row)

        pivot_form = QFormLayout()
        pivot_form.setContentsMargins(0, 6, 0, 0)
        self.model_pivot_spins = {}
        for axis in "xyz":
            spin = QDoubleSpinBox()
            spin.setRange(-3.0, 3.0)
            spin.setSingleStep(0.05)
            spin.setDecimals(3)
            spin.setValue(0.0)
            spin.setEnabled(False)
            self.model_pivot_spins[axis] = spin
            pivot_form.addRow(f"Origin {axis.upper()}", spin)
        layout.addLayout(pivot_form)

        self.pivot_hint_label = QLabel(
            "The RGB axis triad marks the current origin — for an imported "
            "model, nudge these until it sits where the IMU actually is."
        )
        self.pivot_hint_label.setWordWrap(True)
        self.pivot_hint_label.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 11px;")
        self._dim_labels.append((self.pivot_hint_label, True))
        layout.addWidget(self.pivot_hint_label)

        self.reset_pivot_btn = QPushButton("Reset Origin to Model Center")
        self.reset_pivot_btn.setEnabled(False)
        layout.addWidget(self.reset_pivot_btn)

        size_form = QFormLayout()
        size_form.setContentsMargins(0, 6, 0, 0)
        self.board_size_spins = {}
        for axis, default in zip("xyz", DEFAULT_BOARD_SIZE):
            spin = QDoubleSpinBox()
            spin.setRange(0.2, 4.0)
            spin.setSingleStep(0.1)
            spin.setValue(default)
            self.board_size_spins[axis] = spin
            size_form.addRow(f"Board {axis.upper()} size", spin)
        layout.addLayout(size_form)

        self.reset_camera_btn = QPushButton("Reset Camera View")
        layout.addWidget(self.reset_camera_btn)

        self.screenshot_btn = QPushButton("Save Screenshot...")
        layout.addWidget(self.screenshot_btn)

        return box

    def _build_axis_remap_group(self) -> QGroupBox:
        box = QGroupBox("Axis Remap (mounting correction)")
        form = QFormLayout(box)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

        self.axis_combos = {}
        for label, key in (("Display X ←", "x"), ("Display Y ←", "y"), ("Display Z ←", "z")):
            combo = QComboBox()
            combo.addItems(AXIS_OPTIONS)
            self.axis_combos[key] = combo
            form.addRow(label, combo)
        self.axis_combos["x"].setCurrentText("+X")
        self.axis_combos["y"].setCurrentText("+Y")
        self.axis_combos["z"].setCurrentText("+Z")

        self.axis_status_label = QLabel("Identity (no remap)")
        self.axis_status_label.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 11px;")
        self.axis_status_label.setWordWrap(True)
        form.addRow("", self.axis_status_label)

        self.axis_reset_btn = QPushButton("Reset to Identity")
        form.addRow(self.axis_reset_btn)

        return box

    def _build_orientation_group(self) -> QGroupBox:
        box = QGroupBox("Orientation Reference")
        layout = QVBoxLayout(box)

        self.tare_btn = QPushButton("Set Zero (Tare)")
        layout.addWidget(self.tare_btn)

        self.clear_tare_btn = QPushButton("Clear Zero")
        self.clear_tare_btn.setEnabled(False)
        layout.addWidget(self.clear_tare_btn)
        return box

    def _build_recording_group(self) -> QGroupBox:
        box = QGroupBox("Recording && Playback")
        layout = QVBoxLayout(box)

        self.record_btn = QPushButton("● Start Recording...")
        layout.addWidget(self.record_btn)
        self.record_status_label = QLabel("")
        self.record_status_label.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 11px;")
        self.record_status_label.setWordWrap(True)
        self._dim_labels.append((self.record_status_label, True))
        layout.addWidget(self.record_status_label)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet(f"color: {theme.BORDER};")
        layout.addWidget(line)

        self.load_log_btn = QPushButton("Load Log for Playback...")
        layout.addWidget(self.load_log_btn)
        self.playback_file_label = QLabel("No log loaded")
        self.playback_file_label.setWordWrap(True)
        self.playback_file_label.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 11px;")
        self._dim_labels.append((self.playback_file_label, True))
        layout.addWidget(self.playback_file_label)

        play_row = QHBoxLayout()
        self.play_pause_btn = QPushButton("Play")
        self.play_pause_btn.setEnabled(False)
        self.stop_playback_btn = QPushButton("Stop")
        self.stop_playback_btn.setEnabled(False)
        play_row.addWidget(self.play_pause_btn)
        play_row.addWidget(self.stop_playback_btn)
        layout.addLayout(play_row)

        self.playback_position_label = QLabel("")
        self.playback_position_label.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 11px;")
        self._dim_labels.append((self.playback_position_label, True))
        layout.addWidget(self.playback_position_label)

        return box

    def _build_readout_group(self) -> QGroupBox:
        box = QGroupBox("Live Values")
        grid = QGridLayout(box)
        grid.setColumnStretch(1, 1)

        row = 0
        self.quat_value_labels = {}
        for key in ("w", "x", "y", "z"):
            grid.addWidget(QLabel(key), row, 0)
            lbl = _value_label()
            self.quat_value_labels[key] = lbl
            grid.addWidget(lbl, row, 1)
            row += 1

        self.euler_value_labels = {}
        for key, disp in (("roll", "Roll (°)"), ("pitch", "Pitch (°)"), ("yaw", "Yaw (°)")):
            grid.addWidget(QLabel(disp), row, 0)
            lbl = _value_label()
            self.euler_value_labels[key] = lbl
            grid.addWidget(lbl, row, 1)
            row += 1

        return box

    def _build_right_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        layout.addWidget(self.viewport.widget(), 3)

        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setFixedHeight(160)
        self.plot_widget.setLabel("left", "degrees")
        self.plot_widget.setLabel("bottom", "seconds")
        self.plot_legend = self.plot_widget.addLegend()
        self.plot_widget.showGrid(x=True, y=True, alpha=0.15)
        self.roll_curve = self.plot_widget.plot(pen=pg.mkPen("#ff5c6c", width=2), name="Roll")
        self.pitch_curve = self.plot_widget.plot(pen=pg.mkPen("#4fd68b", width=2), name="Pitch")
        self.yaw_curve = self.plot_widget.plot(pen=pg.mkPen("#4fa3ff", width=2), name="Yaw")
        layout.addWidget(self.plot_widget)

        layout.addWidget(self._build_console_group(), 2)

        return panel

    def _build_console_group(self) -> QGroupBox:
        box = QGroupBox("Serial Console")
        layout = QVBoxLayout(box)
        layout.setSpacing(6)

        header = QHBoxLayout()
        self.console_enabled_check = QCheckBox("Live")
        self.console_enabled_check.setChecked(True)
        self.console_autoscroll_check = QCheckBox("Autoscroll")
        self.console_autoscroll_check.setChecked(True)
        self.clear_console_btn = QPushButton("Clear")
        self.clear_console_btn.setMaximumWidth(70)
        header.addWidget(self.console_enabled_check)
        header.addWidget(self.console_autoscroll_check)
        header.addStretch(1)
        header.addWidget(self.clear_console_btn)
        layout.addLayout(header)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMinimumHeight(100)
        self.log_view.setPlaceholderText(
            "Raw lines from the MCU will appear here once connected "
            "(startup messages, debug prints, and unparsed data included)."
        )
        layout.addWidget(self.log_view)

        send_row = QHBoxLayout()
        self.console_input = QLineEdit()
        self.console_input.setPlaceholderText("Type a command to send to the device...")
        self.console_input.setEnabled(False)
        self.console_send_btn = QPushButton("Send")
        self.console_send_btn.setEnabled(False)
        self.console_send_btn.setMaximumWidth(70)
        send_row.addWidget(self.console_input, 1)
        send_row.addWidget(self.console_send_btn)
        layout.addLayout(send_row)

        return box

    # ------------------------------------------------------------------
    # Wiring
    # ------------------------------------------------------------------
    def _wire_up(self):
        self.refresh_btn.clicked.connect(self._refresh_ports)
        self.port_combo.currentIndexChanged.connect(self._update_port_detail)
        self.connect_btn.clicked.connect(self._on_connect_clicked)
        self.import_model_btn.clicked.connect(self._on_import_model)
        self.reset_model_btn.clicked.connect(self._on_reset_model)
        self.reset_camera_btn.clicked.connect(self._on_reset_camera)
        self.screenshot_btn.clicked.connect(self._on_screenshot)
        self.model_color_btn.clicked.connect(self._on_pick_model_color)
        self.theme_toggle_btn.clicked.connect(self._on_toggle_theme)
        self.tare_btn.clicked.connect(self._on_tare)
        self.clear_tare_btn.clicked.connect(self._on_clear_tare)
        self.clear_console_btn.clicked.connect(self.log_view.clear)
        self.console_send_btn.clicked.connect(self._on_console_send)
        self.console_input.returnPressed.connect(self._on_console_send)

        for spin in self.board_size_spins.values():
            spin.valueChanged.connect(self._on_board_size_changed)

        for spin in self.model_pivot_spins.values():
            spin.valueChanged.connect(self._on_model_pivot_changed)
        self.reset_pivot_btn.clicked.connect(self._on_reset_pivot)

        for combo in self.axis_combos.values():
            combo.currentIndexChanged.connect(self._on_axis_remap_changed)
        self.axis_reset_btn.clicked.connect(self._on_axis_remap_reset)

        self.record_btn.clicked.connect(self._on_toggle_recording)
        self.load_log_btn.clicked.connect(self._on_load_log)
        self.play_pause_btn.clicked.connect(self._on_play_pause)
        self.stop_playback_btn.clicked.connect(self._on_stop_playback)
        self.playback.orientationReceived.connect(self._on_playback_sample)
        self.playback.positionChanged.connect(self._on_playback_position)
        self.playback.finished.connect(self._on_playback_finished)

    # ------------------------------------------------------------------
    # Settings persistence
    # ------------------------------------------------------------------
    def _restore_settings(self):
        self._dark_mode = self.settings.get("dark_mode", True)
        self._apply_theme()

        saved_color = self.settings.get("body_color", "")
        if saved_color:
            color = QColor(saved_color)
            if color.isValid():
                self.viewport.set_body_color(color.redF(), color.greenF(), color.blueF())
        self._update_color_swatch()

        last_port = self.settings.get("port", "")
        if last_port:
            idx = self.port_combo.findData(last_port)
            if idx >= 0:
                self.port_combo.setCurrentIndex(idx)

        self.baud_combo.setCurrentText(self.settings.get("baud", "115200"))

        mode = self.settings.get("mode", "quaternion")
        idx = self.mode_combo.findData(mode)
        if idx >= 0:
            self.mode_combo.setCurrentIndex(idx)

        self.auto_reconnect_check.setChecked(self.settings.get("auto_reconnect", True))

        for axis in "xyz":
            saved = self.settings.get(f"axis_{axis}", f"+{axis.upper()}")
            if saved in AXIS_OPTIONS:
                self.axis_combos[axis].setCurrentText(saved)
        self._on_axis_remap_changed()

        for axis, default in zip("xyz", DEFAULT_BOARD_SIZE):
            val = self.settings.get(f"board_{axis}", default)
            try:
                self.board_size_spins[axis].setValue(float(val))
            except (TypeError, ValueError):
                pass

        model_path = self.settings.get("model_path", "")
        if model_path:
            try:
                self.viewport.load_model(model_path)
                self.model_label.setText(model_path)
                self._set_board_size_controls_enabled(False)
                self._set_pivot_controls_enabled(True)
                for axis in "xyz":
                    val = self.settings.get(f"pivot_{axis}", 0.0)
                    try:
                        self.model_pivot_spins[axis].setValue(float(val))
                    except (TypeError, ValueError):
                        pass
            except (ModelLoadError, OSError):
                pass

        self._update_port_detail()

    def _save_settings(self):
        port_data = self.port_combo.currentData()
        if port_data:
            self.settings.set("port", port_data)
        self.settings.set("baud", self.baud_combo.currentText())
        self.settings.set("mode", self.mode_combo.currentData())
        self.settings.set("auto_reconnect", self.auto_reconnect_check.isChecked())
        self.settings.set("dark_mode", self._dark_mode)
        r, g, b = self.viewport.body_color
        self.settings.set("body_color", QColor.fromRgbF(r, g, b).name())
        for axis in "xyz":
            self.settings.set(f"axis_{axis}", self.axis_combos[axis].currentText())
            self.settings.set(f"board_{axis}", self.board_size_spins[axis].value())
            self.settings.set(f"pivot_{axis}", self.model_pivot_spins[axis].value())

    # ------------------------------------------------------------------
    # Port / connection handling
    # ------------------------------------------------------------------
    def _refresh_ports(self):
        current = self.port_combo.currentData()
        self.port_combo.clear()
        ports = list(serial.tools.list_ports.comports())
        for p in ports:
            self.port_combo.addItem(p.device, userData=p.device)
            idx = self.port_combo.count() - 1
            self.port_combo.setItemData(idx, p.description or "", Qt.ToolTipRole)

        if current:
            idx = self.port_combo.findData(current)
            if idx >= 0:
                self.port_combo.setCurrentIndex(idx)

        if self.port_combo.count() == 0:
            self.port_combo.addItem("No ports found", userData=None)

        self._update_port_detail()

    def _update_port_detail(self):
        idx = self.port_combo.currentIndex()
        detail = self.port_combo.itemData(idx, Qt.ToolTipRole) if idx >= 0 else ""
        self.port_detail_label.setText(detail or "")

    def _on_connect_clicked(self):
        if self.reconnect_timer.isActive():
            self.reconnect_timer.stop()
            self.connect_btn.setText("Connect")
            self.connect_btn.setProperty("danger", "false")
            self.connect_btn.setProperty("accent", "true")
            self.connect_btn.style().unpolish(self.connect_btn)
            self.connect_btn.style().polish(self.connect_btn)
            self._set_controls_enabled(True)
            self.status_dot.set_state("off")
            self.status_label.setText("Disconnected")
            return

        if self.worker is not None:
            self._disconnect()
            return

        port = self.port_combo.currentData()
        if not port:
            QMessageBox.warning(self, "No port selected", "Select a valid serial port first.")
            return

        try:
            baud = int(self.baud_combo.currentText())
        except ValueError:
            QMessageBox.warning(self, "Invalid baud rate", "Baud rate must be a number.")
            return

        mode = self.mode_combo.currentData()
        self._save_settings()
        self._start_worker(port, baud, mode)

    def _start_worker(self, port: str, baud: int, mode: str):
        self._last_connection = (port, baud, mode)

        self.worker = SerialWorker(port, baud, mode)
        self.worker.quaternionReceived.connect(self._on_quaternion)
        self.worker.eulerReceived.connect(self._on_euler)
        self.worker.rawLine.connect(self._on_raw_line)
        self.worker.errorOccurred.connect(self._on_error)
        self.worker.connected.connect(self._on_connected)
        self.worker.disconnected.connect(self._on_disconnected)
        self.worker.start()

        self.connect_btn.setEnabled(False)
        self.connect_btn.setText("Connecting...")
        self._set_controls_enabled(False)

    def _disconnect(self):
        if self.worker is not None:
            self.worker.request_stop()

    def _set_controls_enabled(self, enabled: bool):
        self.port_combo.setEnabled(enabled)
        self.baud_combo.setEnabled(enabled)
        self.mode_combo.setEnabled(enabled)
        self.refresh_btn.setEnabled(enabled)
        self.load_log_btn.setEnabled(enabled)
        self.play_pause_btn.setEnabled(enabled and self._playback_loaded)
        self.stop_playback_btn.setEnabled(enabled and self._playback_loaded)

    def _on_connected(self):
        self._is_connected = True
        self._last_sample_time = time.monotonic()
        self.connect_btn.setEnabled(True)
        self.connect_btn.setText("Disconnect")
        self.connect_btn.setProperty("danger", "true")
        self.connect_btn.setProperty("accent", "false")
        self.connect_btn.style().unpolish(self.connect_btn)
        self.connect_btn.style().polish(self.connect_btn)
        self.status_dot.set_state("good")
        self.status_label.setText(f"Connected to {self.port_combo.currentData()}")
        self.console_input.setEnabled(True)
        self.console_send_btn.setEnabled(True)

    def _on_disconnected(self, reason: str):
        if self.worker is not None:
            self.worker.wait(2000)
        self.worker = None
        self._is_connected = False

        self.connect_btn.setEnabled(True)
        self.connect_btn.setText("Connect")
        self.connect_btn.setProperty("danger", "false")
        self.connect_btn.setProperty("accent", "true")
        self.connect_btn.style().unpolish(self.connect_btn)
        self.connect_btn.style().polish(self.connect_btn)
        self._set_controls_enabled(True)
        self.console_input.setEnabled(False)
        self.console_send_btn.setEnabled(False)

        if reason and self.auto_reconnect_check.isChecked() and self._last_connection:
            self.status_dot.set_state("bad")
            self.status_label.setText(f"Disconnected: {reason} — retrying...")
            self.connect_btn.setEnabled(True)
            self.connect_btn.setText("Cancel Reconnect")
            self._set_controls_enabled(False)
            self.reconnect_timer.start(RECONNECT_DELAY_MS)
        else:
            self.status_dot.set_state("bad" if reason else "off")
            self.status_label.setText(f"Disconnected: {reason}" if reason else "Disconnected")

    def _attempt_reconnect(self):
        if self.worker is not None or self._last_connection is None:
            return
        port, baud, mode = self._last_connection
        self._start_worker(port, baud, mode)

    def _on_error(self, message: str):
        self._append_log(f"[error] {message}")

    def _on_raw_line(self, text: str):
        self._append_log(text)

    def _append_log(self, text: str):
        if not self.console_enabled_check.isChecked():
            return
        self.log_view.appendPlainText(text)
        if self.log_view.document().blockCount() > LOG_MAX_BLOCKS:
            cursor = self.log_view.textCursor()
            cursor.movePosition(QTextCursor.Start)
            cursor.select(QTextCursor.BlockUnderCursor)
            cursor.removeSelectedText()
            cursor.deleteChar()
        if self.console_autoscroll_check.isChecked():
            bar = self.log_view.verticalScrollBar()
            bar.setValue(bar.maximum())

    def _on_console_send(self):
        text = self.console_input.text().strip()
        if not text or self.worker is None:
            return
        if self.worker.send(text):
            self._append_log(f"> {text}")
            self.console_input.clear()

    # ------------------------------------------------------------------
    # Orientation data
    # ------------------------------------------------------------------
    def _on_quaternion(self, w, x, y, z):
        q = normalize_quat(w, x, y, z)
        self._ingest_live(quat_to_rotation_matrix(q))

    def _on_euler(self, roll, pitch, yaw):
        q = euler_deg_to_quat(roll, pitch, yaw)
        self._ingest_live(quat_to_rotation_matrix(q))

    def _ingest_live(self, R_raw: np.ndarray):
        R = self._axis_remap @ R_raw @ self._axis_remap.T
        self._set_latest(R)

        if self.recorder is not None:
            q = rotation_matrix_to_quat(R)
            roll, pitch, yaw = quat_to_euler_deg(q)
            t = self.recorder.record(q, roll, pitch, yaw)
            self.record_status_label.setText(f"Recording: {t:.1f}s ({self.recorder.sample_count} samples)")

    def _on_playback_sample(self, w, x, y, z):
        q = normalize_quat(w, x, y, z)
        self._set_latest(quat_to_rotation_matrix(q))

    def _set_latest(self, R: np.ndarray):
        self._latest_R = R
        self._data_dirty = True
        self._sample_count += 1
        self._last_sample_time = time.monotonic()

    def _on_render_tick(self):
        if not self._data_dirty:
            return
        self._data_dirty = False

        R = self._latest_R
        if self._tare_R is not None:
            R = R @ self._tare_R.T

        self.viewport.set_orientation(R)

        q = rotation_matrix_to_quat(R)
        roll, pitch, yaw = quat_to_euler_deg(q)

        for name, val in zip("wxyz", q):
            self.quat_value_labels[name].setText(f"{val:+.4f}")
        self.euler_value_labels["roll"].setText(f"{roll:+.2f}")
        self.euler_value_labels["pitch"].setText(f"{pitch:+.2f}")
        self.euler_value_labels["yaw"].setText(f"{yaw:+.2f}")

        t = time.monotonic() - self._t0
        self._plot_buf.append((t, roll, pitch, yaw))
        while self._plot_buf and t - self._plot_buf[0][0] > PLOT_WINDOW_SECONDS:
            self._plot_buf.popleft()

        if self._plot_buf:
            arr = np.array(self._plot_buf)
            self.roll_curve.setData(arr[:, 0], arr[:, 1])
            self.pitch_curve.setData(arr[:, 0], arr[:, 2])
            self.yaw_curve.setData(arr[:, 0], arr[:, 3])

    def _on_rate_tick(self):
        self.rate_label.setText(f"{self._sample_count} Hz")
        self._sample_count = 0

        if not self._is_connected or self._last_sample_time is None:
            return

        idle = time.monotonic() - self._last_sample_time
        if idle > STALE_DATA_SECONDS:
            self.status_dot.set_state("warn")
            self.status_label.setText(f"Connected to {self.port_combo.currentData()} — no data for {idle:.0f}s")
        else:
            self.status_dot.set_state("good")
            self.status_label.setText(f"Connected to {self.port_combo.currentData()}")

    # ------------------------------------------------------------------
    # Model / camera / screenshot / board size
    # ------------------------------------------------------------------
    def _on_import_model(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Import 3D Model", "", "3D Models (*.stl *.obj)"
        )
        if not path:
            return
        try:
            self.viewport.load_model(path)
        except (ModelLoadError, OSError) as exc:
            QMessageBox.critical(self, "Failed to load model", str(exc))
            return
        self.model_label.setText(path)
        self.settings.set("model_path", path)
        self._set_board_size_controls_enabled(False)
        self._set_pivot_controls_enabled(True)
        for spin in self.model_pivot_spins.values():
            spin.blockSignals(True)
            spin.setValue(0.0)
            spin.blockSignals(False)

    def _on_reset_model(self):
        self.viewport.reset_to_default()
        self.model_label.setText("Using default board shape")
        self.settings.set("model_path", "")
        self._set_board_size_controls_enabled(True)
        self._set_pivot_controls_enabled(False)

    def _set_board_size_controls_enabled(self, enabled: bool):
        for spin in self.board_size_spins.values():
            spin.setEnabled(enabled)

    def _set_pivot_controls_enabled(self, enabled: bool):
        for spin in self.model_pivot_spins.values():
            spin.setEnabled(enabled)
        self.reset_pivot_btn.setEnabled(enabled)

    def _on_model_pivot_changed(self):
        self.viewport.set_model_pivot(
            self.model_pivot_spins["x"].value(),
            self.model_pivot_spins["y"].value(),
            self.model_pivot_spins["z"].value(),
        )

    def _on_reset_pivot(self):
        for spin in self.model_pivot_spins.values():
            spin.blockSignals(True)
            spin.setValue(0.0)
            spin.blockSignals(False)
        self.viewport.set_model_pivot(0.0, 0.0, 0.0)

    def _on_board_size_changed(self):
        self.viewport.set_board_size(
            self.board_size_spins["x"].value(),
            self.board_size_spins["y"].value(),
            self.board_size_spins["z"].value(),
        )

    def _on_reset_camera(self):
        self.viewport.view.setCameraPosition(distance=4.5, elevation=22, azimuth=45)

    def _on_screenshot(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Screenshot", "imu_snapshot.png", "PNG Image (*.png)"
        )
        if not path:
            return
        self.viewport.screenshot(path)
        self.statusBar().showMessage(f"Saved screenshot to {path}", 4000)

    def _on_pick_model_color(self):
        r, g, b = self.viewport.body_color
        current = QColor.fromRgbF(r, g, b)
        color = QColorDialog.getColor(current, self, "Choose Model Color")
        if not color.isValid():
            return
        self.viewport.set_body_color(color.redF(), color.greenF(), color.blueF())
        self._update_color_swatch()

    def _update_color_swatch(self):
        r, g, b = self.viewport.body_color
        color = QColor.fromRgbF(r, g, b)
        self.model_color_swatch.setStyleSheet(
            f"background-color: {color.name()}; border: 1px solid {theme.BORDER}; border-radius: 4px;"
        )

    # ------------------------------------------------------------------
    # Theme
    # ------------------------------------------------------------------
    def _on_toggle_theme(self):
        self._dark_mode = not self._dark_mode
        self._apply_theme()

    def _apply_theme(self):
        palette = theme.DARK if self._dark_mode else theme.LIGHT
        stylesheet = theme.activate(palette)

        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(stylesheet)
        theme.apply_pg_defaults(palette)

        self.viewport.set_theme(palette.viewport_bg, palette.grid_color)

        self.plot_widget.setBackground(palette.viewport_bg)
        for axis_name in ("left", "bottom"):
            axis = self.plot_widget.getAxis(axis_name)
            axis.setPen(palette.text_dim)
            axis.setTextPen(palette.text)
        if self.plot_legend is not None:
            # LegendItem.setLabelTextColor() only updates each label's
            # stored option -- it never re-renders the label's HTML, so the
            # color visually never changes. Force that regeneration directly.
            for _sample, label in self.plot_legend.items:
                label.setText(label.text, color=palette.text)

        for label, small in self._dim_labels:
            suffix = " font-size: 11px;" if small else ""
            label.setStyleSheet(f"color: {palette.text_dim};{suffix}")

        self.theme_toggle_btn.setText("🌙" if self._dark_mode else "☀")

        self.status_dot.refresh()
        self._on_axis_remap_changed()
        self._update_color_swatch()

    # ------------------------------------------------------------------
    # Axis remap / tare
    # ------------------------------------------------------------------
    def _on_axis_remap_changed(self):
        x_src = self.axis_combos["x"].currentText()
        y_src = self.axis_combos["y"].currentText()
        z_src = self.axis_combos["z"].currentText()

        M = build_axis_remap_matrix(x_src, y_src, z_src)
        if M is None:
            self.axis_status_label.setText("Invalid: the three axes must be mutually perpendicular.")
            self.axis_status_label.setStyleSheet(f"color: {theme.BAD}; font-size: 11px;")
            return

        self._axis_remap = M
        if np.allclose(M, np.eye(3)):
            self.axis_status_label.setText("Identity (no remap)")
            self.axis_status_label.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 11px;")
        else:
            self.axis_status_label.setText("Remap active")
            self.axis_status_label.setStyleSheet(f"color: {theme.GOOD}; font-size: 11px;")

    def _on_axis_remap_reset(self):
        self.axis_combos["x"].setCurrentText("+X")
        self.axis_combos["y"].setCurrentText("+Y")
        self.axis_combos["z"].setCurrentText("+Z")

    def _on_tare(self):
        self._tare_R = self._latest_R.copy()
        self.clear_tare_btn.setEnabled(True)

    def _on_clear_tare(self):
        self._tare_R = None
        self.clear_tare_btn.setEnabled(False)

    # ------------------------------------------------------------------
    # Recording / playback
    # ------------------------------------------------------------------
    def _on_toggle_recording(self):
        if self.recorder is not None:
            self.recorder.close()
            self.recorder = None
            self.record_btn.setText("● Start Recording...")
            self.record_status_label.setText("")
            return

        path, _ = QFileDialog.getSaveFileName(
            self, "Start Recording", "imu_session.csv", "CSV Files (*.csv)"
        )
        if not path:
            return
        self.recorder = SessionRecorder(path)
        self.record_btn.setText("■ Stop Recording")
        self.record_status_label.setText("Recording: 0.0s (0 samples)")

    def _on_load_log(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Log for Playback", "", "CSV Files (*.csv)"
        )
        if not path:
            return
        duration = self.playback.load(path)
        if not self.playback.has_data:
            QMessageBox.warning(self, "Empty or invalid log", "No usable rows found in that file.")
            return
        self._playback_loaded = True
        self.playback_file_label.setText(path)
        self.playback_position_label.setText(f"0.0s / {duration:.1f}s")
        self.play_pause_btn.setEnabled(True)
        self.stop_playback_btn.setEnabled(True)
        self.play_pause_btn.setText("Play")

    def _on_play_pause(self):
        if self.playback.is_playing:
            self.playback.pause()
            self.play_pause_btn.setText("Play")
            self.connect_btn.setEnabled(True)
            self.record_btn.setEnabled(True)
        else:
            self.playback.play()
            self.play_pause_btn.setText("Pause")
            self.connect_btn.setEnabled(False)
            self.record_btn.setEnabled(False)

    def _on_stop_playback(self):
        self.playback.stop()
        self.play_pause_btn.setText("Play")
        self.playback_position_label.setText(f"0.0s / {self.playback.duration:.1f}s")
        self.connect_btn.setEnabled(True)
        self.record_btn.setEnabled(True)

    def _on_playback_position(self, current: float, total: float):
        self.playback_position_label.setText(f"{current:.1f}s / {total:.1f}s")

    def _on_playback_finished(self):
        self.playback.stop()
        self.play_pause_btn.setText("Play")
        self.playback_position_label.setText(f"0.0s / {self.playback.duration:.1f}s (finished)")
        self.connect_btn.setEnabled(True)
        self.record_btn.setEnabled(True)

    # ------------------------------------------------------------------
    def closeEvent(self, event):
        self._save_settings()
        self.reconnect_timer.stop()
        if self.recorder is not None:
            self.recorder.close()
        if self.worker is not None:
            self.worker.request_stop()
            self.worker.wait(2000)
        super().closeEvent(event)
