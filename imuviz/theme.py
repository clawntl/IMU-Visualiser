"""Light/dark theming for the app, plus matching pyqtgraph defaults.

Widgets styled purely through Qt stylesheets (buttons, combo boxes, group
boxes, the dynamic accent/danger properties) restyle automatically when the
app-wide stylesheet is reapplied. A handful of labels use direct
setStyleSheet() calls for a dim/status color that isn't expressible as a
plain QSS selector -- MainWindow keeps a list of those and re-applies their
color itself on toggle (see MainWindow._apply_theme)."""

from dataclasses import dataclass

import pyqtgraph as pg


@dataclass(frozen=True)
class Palette:
    name: str
    accent: str
    accent_hover: str
    bg: str
    panel: str
    panel_alt: str
    border: str
    text: str
    text_dim: str
    good: str
    bad: str
    warn: str
    viewport_bg: tuple[int, int, int]
    grid_color: tuple[int, int, int, int]


DARK = Palette(
    name="dark",
    accent="#4fa3ff", accent_hover="#6db4ff",
    bg="#1b1d21", panel="#232630", panel_alt="#2a2e3a", border="#363b48",
    text="#e6e8ec", text_dim="#9aa0ad",
    good="#4fd68b", bad="#ff5c6c", warn="#e0a934",
    viewport_bg=(22, 24, 28), grid_color=(255, 255, 255, 40),
)

LIGHT = Palette(
    name="light",
    accent="#1f6fd6", accent_hover="#3782e8",
    bg="#f4f5f7", panel="#ffffff", panel_alt="#eef0f4", border="#d7dae0",
    text="#1c1e22", text_dim="#6a7180",
    good="#1f9d5a", bad="#d33a4b", warn="#b3790a",
    viewport_bg=(238, 240, 244), grid_color=(20, 24, 30, 40),
)

# Mutable "current theme" module attributes. Kept for existing call sites
# that read these at widget-construction time (e.g. theme.TEXT_DIM); code
# that must react live to a theme change re-applies itself explicitly, see
# MainWindow._apply_theme.
ACCENT = DARK.accent
ACCENT_HOVER = DARK.accent_hover
BG = DARK.bg
PANEL = DARK.panel
PANEL_ALT = DARK.panel_alt
BORDER = DARK.border
TEXT = DARK.text
TEXT_DIM = DARK.text_dim
GOOD = DARK.good
BAD = DARK.bad
WARN = DARK.warn


def activate(palette: Palette) -> str:
    """Updates the mutable current-theme constants and returns the QSS for
    this palette; caller applies it via QApplication.setStyleSheet()."""
    global ACCENT, ACCENT_HOVER, BG, PANEL, PANEL_ALT, BORDER, TEXT, TEXT_DIM, GOOD, BAD, WARN
    ACCENT = palette.accent
    ACCENT_HOVER = palette.accent_hover
    BG = palette.bg
    PANEL = palette.panel
    PANEL_ALT = palette.panel_alt
    BORDER = palette.border
    TEXT = palette.text
    TEXT_DIM = palette.text_dim
    GOOD = palette.good
    BAD = palette.bad
    WARN = palette.warn
    return build_stylesheet(palette)


def apply_pg_defaults(palette: Palette = DARK):
    pg.setConfigOption("background", palette.viewport_bg)
    pg.setConfigOption("foreground", palette.text)
    pg.setConfigOption("antialias", True)


def build_stylesheet(p: Palette) -> str:
    return f"""
* {{
    font-family: 'Segoe UI', 'Inter', sans-serif;
    font-size: 13px;
    color: {p.text};
}}

QMainWindow, QWidget {{
    background-color: {p.bg};
}}

QGroupBox {{
    background-color: {p.panel};
    border: 1px solid {p.border};
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
    color: {p.text_dim};
}}

QLabel {{
    background: transparent;
}}

QLabel[role="value"] {{
    color: {p.accent};
    font-weight: 600;
}}

QLabel[role="heading"] {{
    font-size: 16px;
    font-weight: 700;
}}

QPushButton {{
    background-color: {p.panel_alt};
    border: 1px solid {p.border};
    border-radius: 6px;
    padding: 6px 14px;
}}

QPushButton:hover {{
    border-color: {p.accent};
}}

QPushButton:pressed {{
    background-color: {p.border};
}}

QPushButton:disabled {{
    color: {p.text_dim};
}}

QPushButton[accent="true"] {{
    background-color: {p.accent};
    color: #ffffff;
    font-weight: 600;
    border: none;
}}

QPushButton[accent="true"]:hover {{
    background-color: {p.accent_hover};
}}

QPushButton[danger="true"] {{
    background-color: {p.bad};
    color: #ffffff;
    font-weight: 600;
    border: none;
}}

QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit {{
    background-color: {p.panel_alt};
    border: 1px solid {p.border};
    border-radius: 6px;
    padding: 4px 8px;
    min-height: 22px;
}}

QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover {{
    border-color: {p.accent};
}}

QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QLineEdit:disabled {{
    background-color: transparent;
    border-color: {p.border};
    color: {p.text_dim};
}}

QComboBox::drop-down {{
    border: none;
    width: 20px;
}}

QComboBox QAbstractItemView {{
    background-color: {p.panel_alt};
    border: 1px solid {p.border};
    selection-background-color: {p.accent};
    selection-color: #ffffff;
}}

QCheckBox {{
    spacing: 8px;
}}

QSplitter::handle {{
    background-color: {p.border};
}}

QStatusBar {{
    background-color: {p.panel};
    border-top: 1px solid {p.border};
}}

QPlainTextEdit {{
    background-color: {p.bg};
    border: 1px solid {p.border};
    border-radius: 6px;
    font-family: Consolas, monospace;
    font-size: 11px;
    color: {p.text_dim};
}}

QScrollArea {{
    border: none;
}}

QToolTip {{
    background-color: {p.panel_alt};
    color: {p.text};
    border: 1px solid {p.border};
}}
"""


# Kept for compatibility with any external reference to a static sheet;
# prefer build_stylesheet(DARK)/build_stylesheet(LIGHT) or activate(palette).
STYLESHEET = build_stylesheet(DARK)
