"""Configuration constants for the Optiland GUI.

This module holds shared constants (file paths and application settings)
to avoid circular import issues between other modules.
"""

from __future__ import annotations

import os

# --- Theme and Style Paths ---
GUI_BASE_DIR = os.path.dirname(__file__)
RESOURCES_DIR = os.path.join(GUI_BASE_DIR, "resources")
STYLES_DIR = os.path.join(RESOURCES_DIR, "styles")

THEME_DARK_PATH = os.path.join(STYLES_DIR, "dark_theme.qss")
THEME_LIGHT_PATH = os.path.join(STYLES_DIR, "light_theme.qss")
SIDEBAR_QSS_PATH = os.path.join(STYLES_DIR, "sidebar.qss")
ICONS_DIR = os.path.join(RESOURCES_DIR, "icons")
OPTILAND_ICON_PATH = ":/icons/optiland_icon.png"


# --- Application Info ---
ORGANIZATION_NAME = "OptilandProject"
APPLICATION_NAME = "OptilandGUI"


# --- Shared Control Sizing ---
CONTROL_HEIGHT_PX = 24
CONTROL_MIN_HEIGHT_PX = 18
CONTROL_BORDER_RADIUS_PX = 6
BUTTON_PADDING_Y_PX = 4
BUTTON_PADDING_X_PX = 12
INPUT_PADDING_Y_PX = 4
INPUT_PADDING_LEFT_PX = 10
INPUT_PADDING_RIGHT_PX = 34
TOOLBUTTON_PADDING_PX = 4
SPIN_BUTTON_WIDTH_PX = 18
COMBO_DROPDOWN_WIDTH_PX = 26


def build_control_size_override() -> str:
    """Return a shared QSS block that standardizes control sizing across themes."""
    return f"""
QPushButton,
QLineEdit,
QSpinBox,
QDoubleSpinBox,
QComboBox {{
    min-height: {CONTROL_MIN_HEIGHT_PX}px;
    max-height: {CONTROL_HEIGHT_PX}px;
    border-radius: {CONTROL_BORDER_RADIUS_PX}px;
}}

QPushButton,
QLineEdit {{
    padding: {BUTTON_PADDING_Y_PX}px {BUTTON_PADDING_X_PX}px;
}}

QPushButton::menu-indicator {{
    subcontrol-origin: padding;
    subcontrol-position: center right;
    right: 8px;
    width: 10px;
}}

QSpinBox,
QDoubleSpinBox,
QComboBox {{
    padding: {INPUT_PADDING_Y_PX}px {INPUT_PADDING_RIGHT_PX}px {INPUT_PADDING_Y_PX}px {INPUT_PADDING_LEFT_PX}px;
}}

QToolButton {{
    min-height: {CONTROL_MIN_HEIGHT_PX}px;
    max-height: {CONTROL_HEIGHT_PX}px;
    padding: {TOOLBUTTON_PADDING_PX}px;
}}

QAbstractSpinBox::up-button,
QAbstractSpinBox::down-button {{
    width: {SPIN_BUTTON_WIDTH_PX}px;
}}

QComboBox::drop-down {{
    width: {COMBO_DROPDOWN_WIDTH_PX}px;
}}

#ViewerToolbarContainer QToolButton {{
    min-width: {CONTROL_HEIGHT_PX}px;
    max-width: {CONTROL_HEIGHT_PX}px;
    min-height: {CONTROL_HEIGHT_PX}px;
    max-height: {CONTROL_HEIGHT_PX}px;
    padding: {TOOLBUTTON_PADDING_PX}px;
}}

QToolBar#AnalysisPlotToolbarTitle QToolButton {{
    min-width: {CONTROL_HEIGHT_PX}px;
    max-width: {CONTROL_HEIGHT_PX}px;
    min-height: {CONTROL_HEIGHT_PX}px;
    max-height: {CONTROL_HEIGHT_PX}px;
    padding: {TOOLBUTTON_PADDING_PX}px;
}}
"""
