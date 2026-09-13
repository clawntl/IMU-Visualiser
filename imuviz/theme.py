"""A flat dark theme for the app, plus matching pyqtgraph defaults."""

import pyqtgraph as pg

ACCENT = "#4fa3ff"
ACCENT_HOVER = "#6db4ff"
BG = "#1b1d21"
PANEL = "#232630"
PANEL_ALT = "#2a2e3a"
BORDER = "#363b48"
TEXT = "#e6e8ec"
TEXT_DIM = "#9aa0ad"
GOOD = "#4fd68b"
BAD = "#ff5c6c"


def apply_pg_defaults():
    pg.setConfigOption("background", (22, 24, 28))
    pg.setConfigOption("foreground", TEXT)
    pg.setConfigOption("antialias", True)


STYLESHEET = f"""
* {{
    font-family: 'Segoe UI', 'Inter', sans-serif;
    font-size: 13px;
    color: {TEXT};
}}

QMainWindow, QWidget {{
    background-color: {BG};
}}

QGroupBox {{
    background-color: {PANEL};
    border: 1px solid {BORDER};
    border-radius: 8px;
    margin-top: 14px;
    padding: 10px 8px 8px 8px;
    font-weight: 600;
}}

QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    top: 2px;
    padding: 0 4px;
    color: {TEXT_DIM};
}}

QLabel {{
    background: transparent;
}}

QLabel[role="value"] {{
    color: {ACCENT};
    font-weight: 600;
}}

QLabel[role="heading"] {{
    font-size: 16px;
    font-weight: 700;
}}

QPushButton {{
    background-color: {PANEL_ALT};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 6px 14px;
}}

QPushButton:hover {{
    border-color: {ACCENT};
}}

QPushButton:pressed {{
    background-color: {BORDER};
}}

QPushButton:disabled {{
    color: {TEXT_DIM};
}}

QPushButton[accent="true"] {{
    background-color: {ACCENT};
    color: #0b0d10;
    font-weight: 600;
    border: none;
}}

QPushButton[accent="true"]:hover {{
    background-color: {ACCENT_HOVER};
}}

QPushButton[danger="true"] {{
    background-color: {BAD};
    color: #1a0505;
    font-weight: 600;
    border: none;
}}

QComboBox, QSpinBox, QLineEdit {{
    background-color: {PANEL_ALT};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 4px 8px;
    min-height: 22px;
}}

QComboBox:hover, QSpinBox:hover {{
    border-color: {ACCENT};
}}

QComboBox::drop-down {{
    border: none;
    width: 20px;
}}

QComboBox QAbstractItemView {{
    background-color: {PANEL_ALT};
    border: 1px solid {BORDER};
    selection-background-color: {ACCENT};
    selection-color: #0b0d10;
}}

QCheckBox {{
    spacing: 8px;
}}

QSplitter::handle {{
    background-color: {BORDER};
}}

QStatusBar {{
    background-color: {PANEL};
    border-top: 1px solid {BORDER};
}}

QPlainTextEdit {{
    background-color: #14161a;
    border: 1px solid {BORDER};
    border-radius: 6px;
    font-family: Consolas, monospace;
    font-size: 11px;
    color: {TEXT_DIM};
}}

QScrollArea {{
    border: none;
}}

QToolTip {{
    background-color: {PANEL_ALT};
    color: {TEXT};
    border: 1px solid {BORDER};
}}
"""
