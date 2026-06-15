"""PortaPack/Mayhem visual identity — colours, fonts and Qt stylesheet."""

from __future__ import annotations

# Mayhem-style palette (dark, high-contrast, cyan/orange accents)
BG = "#000000"
BG_PANEL = "#0a0a14"
BG_RAISED = "#13131f"
FG = "#e0e0e0"
FG_DIM = "#7a7a8a"
ACCENT = "#00c0c0"          # cyan — selection/focus
ACCENT2 = "#ff9000"         # orange — TX / warnings
GREEN = "#00d000"
RED = "#e02020"
BLUE = "#3060ff"
GREY = "#303040"
SELECT_BG = "#005f5f"

# Waterfall colormap control points (Mayhem-like: black->blue->cyan->yellow->white)
WATERFALL_STOPS = [
    (0.0, (0, 0, 0)),
    (0.25, (0, 0, 80)),
    (0.45, (0, 60, 160)),
    (0.62, (0, 200, 200)),
    (0.78, (220, 220, 0)),
    (0.92, (255, 120, 0)),
    (1.0, (255, 255, 255)),
]

MONO_FONT = "DejaVu Sans Mono"


def stylesheet() -> str:
    return f"""
    QMainWindow, QWidget {{
        background-color: {BG};
        color: {FG};
        font-family: '{MONO_FONT}';
        font-size: 13px;
    }}
    QFrame#StatusBar {{
        background-color: {BG_RAISED};
        border-bottom: 1px solid {GREY};
    }}
    QFrame#NavPanel {{
        background-color: {BG_PANEL};
        border-right: 1px solid {GREY};
    }}
    QLabel {{ background: transparent; }}
    QLabel#Title {{
        color: {ACCENT}; font-size: 15px; font-weight: bold;
    }}
    QTreeWidget {{
        background-color: {BG_PANEL};
        border: none;
        outline: 0;
    }}
    QTreeWidget::item {{
        padding: 6px 4px;
        border-radius: 3px;
    }}
    QTreeWidget::item:selected {{
        background-color: {SELECT_BG};
        color: #ffffff;
    }}
    QTreeWidget::item:hover {{
        background-color: {BG_RAISED};
    }}
    QPushButton {{
        background-color: {BG_RAISED};
        border: 1px solid {GREY};
        border-radius: 4px;
        padding: 6px 12px;
        color: {FG};
    }}
    QPushButton:hover {{ border-color: {ACCENT}; }}
    QPushButton:pressed {{ background-color: {SELECT_BG}; }}
    QPushButton:checked {{
        background-color: {SELECT_BG};
        border-color: {ACCENT};
        color: #ffffff;
    }}
    QPushButton#TxButton {{
        border-color: {ACCENT2};
        color: {ACCENT2};
    }}
    QPushButton#TxButton:checked {{
        background-color: {ACCENT2};
        color: #000000;
    }}
    QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit {{
        background-color: {BG_RAISED};
        border: 1px solid {GREY};
        border-radius: 3px;
        padding: 3px 6px;
        color: {FG};
    }}
    QComboBox:focus, QLineEdit:focus, QSpinBox:focus {{
        border-color: {ACCENT};
    }}
    QComboBox QAbstractItemView {{
        background-color: {BG_RAISED};
        selection-background-color: {SELECT_BG};
    }}
    QSlider::groove:horizontal {{
        height: 4px; background: {GREY}; border-radius: 2px;
    }}
    QSlider::handle:horizontal {{
        background: {ACCENT}; width: 14px; margin: -6px 0; border-radius: 7px;
    }}
    QGroupBox {{
        border: 1px solid {GREY};
        border-radius: 4px;
        margin-top: 8px;
        padding-top: 8px;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 8px;
        color: {ACCENT};
    }}
    QScrollBar:vertical {{ background: {BG}; width: 10px; }}
    QScrollBar::handle:vertical {{ background: {GREY}; border-radius: 5px; }}
    """
