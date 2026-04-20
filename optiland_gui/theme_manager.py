"""Theme registry and palette-driven stylesheet overrides for the GUI."""

from __future__ import annotations

from dataclasses import dataclass

from .config import THEME_DARK_PATH, THEME_LIGHT_PATH


@dataclass(frozen=True)
class ThemeDefinition:
    """Describes a selectable application theme."""

    theme_id: str
    label: str
    mode: str
    base_path: str
    palette: dict[str, str]


def _theme(
    theme_id: str, label: str, mode: str, base_path: str, palette: dict[str, str]
) -> ThemeDefinition:
    return ThemeDefinition(theme_id, label, mode, base_path, palette)


THEMES: tuple[ThemeDefinition, ...] = (
    _theme(
        "github_dark",
        "GitHub Dark",
        "dark",
        THEME_DARK_PATH,
        {
            "window_bg": "#0d1117",
            "app_bg": "#161b22",
            "surface_bg": "#161b22",
            "elevated_bg": "#21262d",
            "toolbar_bg": "#161b22",
            "sidebar_bg": "#0f141a",
            "sidebar_hover_bg": "#1f2733",
            "sidebar_active_bg": "#1b2a41",
            "text": "#e6edf3",
            "muted_text": "#b6c2cf",
            "border": "#30363d",
            "accent": "#4c78a8",
            "accent_hover": "#5b88b8",
            "accent_pressed": "#3d6289",
            "accent_soft": "#17304d",
            "input_bg": "#0f141a",
            "hover_bg": "#262c36",
            "selection_bg": "#4c78a8",
            "selection_text": "#ffffff",
            "scrollbar": "#465363",
            "tooltip_bg": "#20262e",
            "tooltip_text": "#f0f6fc",
        },
    ),
    _theme(
        "nord_dark",
        "Nord Dark",
        "dark",
        THEME_DARK_PATH,
        {
            "window_bg": "#2e3440",
            "app_bg": "#3b4252",
            "surface_bg": "#3b4252",
            "elevated_bg": "#434c5e",
            "toolbar_bg": "#3b4252",
            "sidebar_bg": "#2b303b",
            "sidebar_hover_bg": "#465066",
            "sidebar_active_bg": "#40526b",
            "text": "#eceff4",
            "muted_text": "#d8dee9",
            "border": "#4c566a",
            "accent": "#5e81ac",
            "accent_hover": "#6f93be",
            "accent_pressed": "#4e6c90",
            "accent_soft": "#33435a",
            "input_bg": "#2e3440",
            "hover_bg": "#4b5568",
            "selection_bg": "#5e81ac",
            "selection_text": "#ffffff",
            "scrollbar": "#66758d",
            "tooltip_bg": "#434c5e",
            "tooltip_text": "#eceff4",
        },
    ),
    _theme(
        "tokyo_night",
        "Tokyo Night",
        "dark",
        THEME_DARK_PATH,
        {
            "window_bg": "#1a1b26",
            "app_bg": "#1f2335",
            "surface_bg": "#1f2335",
            "elevated_bg": "#24283b",
            "toolbar_bg": "#1f2335",
            "sidebar_bg": "#181b2b",
            "sidebar_hover_bg": "#2a3148",
            "sidebar_active_bg": "#22304a",
            "text": "#c0caf5",
            "muted_text": "#a9b1d6",
            "border": "#3b4261",
            "accent": "#6582c6",
            "accent_hover": "#7593d8",
            "accent_pressed": "#4f6aa8",
            "accent_soft": "#1f3354",
            "input_bg": "#161927",
            "hover_bg": "#2b3250",
            "selection_bg": "#6582c6",
            "selection_text": "#ffffff",
            "scrollbar": "#4f5f7a",
            "tooltip_bg": "#24283b",
            "tooltip_text": "#e0e6ff",
        },
    ),
    _theme(
        "everforest_dark",
        "Everforest Dark",
        "dark",
        THEME_DARK_PATH,
        {
            "window_bg": "#232a2e",
            "app_bg": "#2d353b",
            "surface_bg": "#2d353b",
            "elevated_bg": "#343f44",
            "toolbar_bg": "#2d353b",
            "sidebar_bg": "#272e33",
            "sidebar_hover_bg": "#3d484d",
            "sidebar_active_bg": "#31474e",
            "text": "#d3c6aa",
            "muted_text": "#9da9a0",
            "border": "#4f585e",
            "accent": "#5f9ea0",
            "accent_hover": "#71afb1",
            "accent_pressed": "#4b7d7f",
            "accent_soft": "#294044",
            "input_bg": "#232a2e",
            "hover_bg": "#414b50",
            "selection_bg": "#5f9ea0",
            "selection_text": "#ffffff",
            "scrollbar": "#606b70",
            "tooltip_bg": "#343f44",
            "tooltip_text": "#efebd4",
        },
    ),
    _theme(
        "solarized_dark",
        "Solarized Dark",
        "dark",
        THEME_DARK_PATH,
        {
            "window_bg": "#002b36",
            "app_bg": "#073642",
            "surface_bg": "#073642",
            "elevated_bg": "#0a4452",
            "toolbar_bg": "#073642",
            "sidebar_bg": "#002b36",
            "sidebar_hover_bg": "#174954",
            "sidebar_active_bg": "#1a5561",
            "text": "#eee8d5",
            "muted_text": "#93a1a1",
            "border": "#586e75",
            "accent": "#5b8db8",
            "accent_hover": "#6ca0cc",
            "accent_pressed": "#4b7295",
            "accent_soft": "#17495f",
            "input_bg": "#002b36",
            "hover_bg": "#1b5966",
            "selection_bg": "#5b8db8",
            "selection_text": "#ffffff",
            "scrollbar": "#6a7f85",
            "tooltip_bg": "#0a4452",
            "tooltip_text": "#fdf6e3",
        },
    ),
    _theme(
        "github_light",
        "GitHub Light",
        "light",
        THEME_LIGHT_PATH,
        {
            "window_bg": "#f6f8fa",
            "app_bg": "#ffffff",
            "surface_bg": "#ffffff",
            "elevated_bg": "#f6f8fa",
            "toolbar_bg": "#f6f8fa",
            "sidebar_bg": "#f6f8fa",
            "sidebar_hover_bg": "#eaeef2",
            "sidebar_active_bg": "#ddeefe",
            "text": "#1f2328",
            "muted_text": "#57606a",
            "border": "#d0d7de",
            "accent": "#4c78a8",
            "accent_hover": "#5b88b8",
            "accent_pressed": "#3d6289",
            "accent_soft": "#dce9f6",
            "input_bg": "#ffffff",
            "hover_bg": "#eef2f6",
            "selection_bg": "#4c78a8",
            "selection_text": "#ffffff",
            "scrollbar": "#b4bec8",
            "tooltip_bg": "#ffffff",
            "tooltip_text": "#1f2328",
        },
    ),
    _theme(
        "nord_light",
        "Nord Light",
        "light",
        THEME_LIGHT_PATH,
        {
            "window_bg": "#eceff4",
            "app_bg": "#f4f6fb",
            "surface_bg": "#fbfcfe",
            "elevated_bg": "#e5e9f0",
            "toolbar_bg": "#eef1f6",
            "sidebar_bg": "#e5e9f0",
            "sidebar_hover_bg": "#dbe2ec",
            "sidebar_active_bg": "#d6e4f2",
            "text": "#2e3440",
            "muted_text": "#4c566a",
            "border": "#cfd8e3",
            "accent": "#5e81ac",
            "accent_hover": "#6f93be",
            "accent_pressed": "#4e6c90",
            "accent_soft": "#d8e4f1",
            "input_bg": "#ffffff",
            "hover_bg": "#e3e9f2",
            "selection_bg": "#5e81ac",
            "selection_text": "#ffffff",
            "scrollbar": "#b0bccd",
            "tooltip_bg": "#fbfcfe",
            "tooltip_text": "#2e3440",
        },
    ),
    _theme(
        "catppuccin_latte",
        "Catppuccin Latte",
        "light",
        THEME_LIGHT_PATH,
        {
            "window_bg": "#eff1f5",
            "app_bg": "#ffffff",
            "surface_bg": "#ffffff",
            "elevated_bg": "#e6e9ef",
            "toolbar_bg": "#eff1f5",
            "sidebar_bg": "#e6e9ef",
            "sidebar_hover_bg": "#dce0e8",
            "sidebar_active_bg": "#dbe8f6",
            "text": "#4c4f69",
            "muted_text": "#6c6f85",
            "border": "#ccd0da",
            "accent": "#7287bd",
            "accent_hover": "#8197cb",
            "accent_pressed": "#6175a7",
            "accent_soft": "#e0e7f5",
            "input_bg": "#ffffff",
            "hover_bg": "#e8ebf2",
            "selection_bg": "#7287bd",
            "selection_text": "#ffffff",
            "scrollbar": "#b8bec9",
            "tooltip_bg": "#ffffff",
            "tooltip_text": "#4c4f69",
        },
    ),
    _theme(
        "solarized_light",
        "Solarized Light",
        "light",
        THEME_LIGHT_PATH,
        {
            "window_bg": "#fdf6e3",
            "app_bg": "#fffaf0",
            "surface_bg": "#fffdf7",
            "elevated_bg": "#f4ebd2",
            "toolbar_bg": "#fdf6e3",
            "sidebar_bg": "#f4ebd2",
            "sidebar_hover_bg": "#eee2c2",
            "sidebar_active_bg": "#e6dfc4",
            "text": "#586e75",
            "muted_text": "#657b83",
            "border": "#d6cfbe",
            "accent": "#5b8db8",
            "accent_hover": "#6ca0cc",
            "accent_pressed": "#4b7295",
            "accent_soft": "#dde9f1",
            "input_bg": "#fffdf7",
            "hover_bg": "#f3ebd5",
            "selection_bg": "#5b8db8",
            "selection_text": "#ffffff",
            "scrollbar": "#b9b3a3",
            "tooltip_bg": "#fffdf7",
            "tooltip_text": "#586e75",
        },
    ),
    _theme(
        "everforest_light",
        "Everforest Light",
        "light",
        THEME_LIGHT_PATH,
        {
            "window_bg": "#fdf6e3",
            "app_bg": "#fffdf8",
            "surface_bg": "#fffef9",
            "elevated_bg": "#f3ead3",
            "toolbar_bg": "#f8f1df",
            "sidebar_bg": "#f3ead3",
            "sidebar_hover_bg": "#ebe0c4",
            "sidebar_active_bg": "#dfe8d6",
            "text": "#5c6a72",
            "muted_text": "#708089",
            "border": "#d8ceb7",
            "accent": "#6f8f72",
            "accent_hover": "#82a285",
            "accent_pressed": "#5a755d",
            "accent_soft": "#e3ecda",
            "input_bg": "#fffef9",
            "hover_bg": "#f0e7cf",
            "selection_bg": "#6f8f72",
            "selection_text": "#ffffff",
            "scrollbar": "#beb39c",
            "tooltip_bg": "#fffef9",
            "tooltip_text": "#5c6a72",
        },
    ),
)

THEME_MAP = {theme.theme_id: theme for theme in THEMES}
DEFAULT_THEME_ID = THEMES[0].theme_id


def get_theme(theme_id: str) -> ThemeDefinition:
    """Return the theme definition for *theme_id* or the default theme."""
    return THEME_MAP.get(theme_id, THEME_MAP[DEFAULT_THEME_ID])


def get_theme_ids(mode: str | None = None) -> list[str]:
    """Return theme ids, optionally filtered by dark/light mode."""
    if mode is None:
        return [theme.theme_id for theme in THEMES]
    return [theme.theme_id for theme in THEMES if theme.mode == mode]


def build_palette_override(theme: ThemeDefinition) -> str:
    """Build a final stylesheet override block for a palette-based theme."""
    p = theme.palette
    return f"""
/* ============================================================
   Palette Override: {theme.label}
   ============================================================ */
QWidget {{
    color: {p["text"]};
    background-color: {p["app_bg"]};
}}

QMainWindow {{
    background-color: {p["window_bg"]};
    color: {p["text"]};
}}

QMainWindow::separator,
QSplitter::handle {{
    background-color: {p["border"]};
    border: 1px solid {p["border"]};
}}

QMainWindow::separator:hover,
QSplitter::handle:hover,
QSplitter::handle:pressed {{
    background-color: {p["accent"]};
    border-color: {p["accent"]};
}}

QDockWidget {{
    border: 1px solid {p["border"]};
    border-radius: 6px;
}}

QDockWidget > QWidget {{
    background-color: {p["surface_bg"]};
    border: 1px solid {p["border"]};
    border-top: none;
}}

QDockWidget::title,
QWidget#CustomDockTitleBar {{
    background-color: {p["elevated_bg"]};
    color: {p["text"]};
    border: none;
    border-bottom: 1px solid {p["border"]};
}}

QWidget#CustomDockTitleBar QLabel,
QDockWidget::title,
QLabel,
QCheckBox,
QRadioButton,
QGroupBox {{
    color: {p["text"]};
}}

#CustomTitleBar,
#TitleBarMenuBar,
QToolBar#QuickActionsToolbar {{
    background-color: {p["toolbar_bg"]};
    color: {p["text"]};
    border: none;
    border-bottom: 1px solid {p["border"]};
}}

#TitleBarOptilandLabel,
#TitleBarProjectLabel,
#TitleBarMenuBar,
#TitleBarMenuBar::item,
#TitleBarMinimizeButton,
#TitleBarMaximizeButton,
#TitleBarCloseButton,
QToolButton#TitleBarFullscreenButton,
QToolButton#TitleBarSettingsButton,
QToolButton#TitleBarGitHubButton,
QToolButton#TitleBarHelpButton {{
    color: {p["text"]};
}}

#TitleBarMenuBar::item:selected,
#TitleBarMinimizeButton:hover,
#TitleBarMaximizeButton:hover,
QToolButton#TitleBarFullscreenButton:hover,
QToolButton#TitleBarSettingsButton:hover,
QToolButton#TitleBarGitHubButton:hover,
QToolButton#TitleBarHelpButton:hover,
QToolBar#QuickActionsToolbar QToolButton:hover {{
    background-color: {p["hover_bg"]};
}}

#TitleBarMenuBar::item:pressed,
QToolButton#TitleBarFullscreenButton:pressed,
QToolBar#QuickActionsToolbar QToolButton:pressed,
QToolBar#QuickActionsToolbar QToolButton:checked {{
    background-color: {p["elevated_bg"]};
}}

QFrame#TitleBarSeparator,
QFrame#TitleBarToolsSeparator {{
    background-color: {p["border"]};
    max-width: 2px;
    min-width: 2px;
    max-height: 15px;
    border: none;
}}

QMenuBar,
QMenu {{
    background-color: {p["surface_bg"]};
    color: {p["text"]};
    border: 1px solid {p["border"]};
}}

QMenu::item:selected {{
    background-color: {p["accent"]};
    color: {p["selection_text"]};
}}

#SidebarWidget {{
    background-color: {p["sidebar_bg"]};
    border-right: 1px solid {p["border"]};
}}

#SidebarTitleLabel,
#SidebarWidget QToolButton {{
    color: {p["text"]};
    background-color: transparent;
}}

#SidebarWidget QToolButton:hover {{
    background-color: {p["sidebar_hover_bg"]};
    color: {p["text"]};
}}

#SidebarWidget QToolButton:checked,
#SidebarWidget QToolButton:pressed {{
    background-color: {p["sidebar_active_bg"]};
    color: {p["selection_text"]};
    border-left: 3px solid {p["accent"]};
}}

QTabWidget::pane,
QTabBar::tab:selected {{
    background-color: {p["surface_bg"]};
    color: {p["text"]};
    border: 1px solid {p["border"]};
}}

QTabBar::tab {{
    background-color: {p["elevated_bg"]};
    color: {p["muted_text"]};
    border: 1px solid {p["border"]};
    padding: 7px 14px;
}}

QTabBar::tab:!selected:hover {{
    background-color: {p["hover_bg"]};
    color: {p["text"]};
}}

QTabBar::tab:selected {{
    border-top: 2px solid {p["accent"]};
}}

QGroupBox {{
    border: 1px solid {p["border"]};
    border-radius: 6px;
    margin-top: 10px;
    padding-top: 10px;
}}

QGroupBox::title {{
    subcontrol-origin: margin;
    left: 8px;
    padding: 0 4px;
    color: {p["muted_text"]};
}}

QPushButton {{
    background-color: {p["accent"]};
    color: {p["selection_text"]};
    border: 1px solid {p["accent"]};
    border-radius: 6px;
    padding: 6px 12px;
}}

QPushButton:hover {{
    background-color: {p["accent_hover"]};
    border-color: {p["accent_hover"]};
}}

QPushButton:pressed {{
    background-color: {p["accent_pressed"]};
    border-color: {p["accent_pressed"]};
}}

QPushButton:disabled {{
    background-color: {p["elevated_bg"]};
    border-color: {p["border"]};
    color: {p["muted_text"]};
}}

QLineEdit,
QPlainTextEdit,
QTextEdit,
QSpinBox,
QDoubleSpinBox,
QComboBox,
QAbstractItemView,
QTreeWidget,
QListWidget,
QTableWidget {{
    background-color: {p["input_bg"]};
    color: {p["text"]};
    border: 1px solid {p["border"]};
    selection-background-color: {p["selection_bg"]};
    selection-color: {p["selection_text"]};
}}

QLineEdit:focus,
QPlainTextEdit:focus,
QTextEdit:focus,
QSpinBox:focus,
QDoubleSpinBox:focus,
QComboBox:focus,
QTreeWidget:focus,
QListWidget:focus,
QTableWidget:focus {{
    border: 1px solid {p["accent"]};
}}

QHeaderView::section {{
    background-color: {p["elevated_bg"]};
    color: {p["text"]};
    border: 1px solid {p["border"]};
    padding: 5px 8px;
}}

QHeaderView::section:hover {{
    background-color: {p["hover_bg"]};
}}

QTableWidget::item:hover,
QTreeWidget::item:hover,
QListWidget::item:hover {{
    background-color: {p["accent_soft"]};
}}

QScrollBar:horizontal,
QScrollBar:vertical {{
    background-color: {p["sidebar_bg"]};
    border: 1px solid {p["border"]};
}}

QScrollBar::handle:horizontal,
QScrollBar::handle:vertical {{
    background-color: {p["scrollbar"]};
    border-radius: 5px;
}}

QScrollBar::handle:horizontal:hover,
QScrollBar::handle:vertical:hover {{
    background-color: {p["muted_text"]};
}}

QToolTip {{
    background-color: {p["tooltip_bg"]};
    color: {p["tooltip_text"]};
    border: 1px solid {p["border"]};
    padding: 5px 8px;
}}
"""
