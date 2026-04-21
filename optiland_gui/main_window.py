"""Defines the main window of the Optiland GUI application.

This module contains the `MainWindow` class, which serves as the main entry point
and container for all GUI elements, including the lens editor, analysis panels,
viewers, and toolbars. It manages window layout, themes, actions, and the
connection to the backend via the `OptilandConnector`.

Author: Manuel Fragata Mendes, 2025
"""

from __future__ import annotations

import contextlib
import inspect
import logging
import os
from collections import defaultdict

from PySide6.QtCore import (
    QByteArray,
    QEasingCurve,
    QEvent,
    QPropertyAnimation,
    QSettings,
    Qt,
    QUrl,
    Slot,
)
from PySide6.QtGui import (
    QAction,
    QDesktopServices,
    QIcon,
    QKeySequence,
    QMoveEvent,
    QResizeEvent,
    QShortcut,
)
from PySide6.QtWidgets import (
    QDialog,
    QDockWidget,
    QFileDialog,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMenuBar,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

import optiland.samples
from optiland.optic import Optic

from . import gui_plot_utils
from .action_manager import ActionManager
from .config import (
    APPLICATION_NAME,
    OPTILAND_ICON_PATH,
    ORGANIZATION_NAME,
    SIDEBAR_QSS_PATH,
)
from .optiland_connector import OptilandConnector
from .panel_manager import PanelManager
from .theme_manager import (
    DEFAULT_THEME_ID,
    THEMES,
    build_palette_override,
    get_theme,
)
from .services.catalog_service import EDMUND_ZEMAX_PAGE_URL, THORLABS_ZEMAX_PAGE_URL
from .utils import logging_handler as _log_handler
from .utils.plot_theme import apply_plot_theme
from .widgets.command_palette import (
    CommandPaletteWidget,
    CommandRegistry,
    PaletteCommand,
)
from .widgets.custom_title_bar import CustomTitleBar
from .widgets.frameless_window import FramelessWindow
from .widgets.sidebar import (
    SIDEBAR_MAX_WIDTH,
    SIDEBAR_MIN_WIDTH,
)
from .widgets.toast import ToastManager

try:
    from .resources import resources_rc  # noqa: F401
except ImportError as e:
    import logging as _import_logging

    _import_logging.getLogger(__name__).warning(
        "Could not import resources_rc.py: %s", e
    )

logger = logging.getLogger(__name__)


class MainWindow(FramelessWindow):
    """The main application window for the Optiland GUI.

    This class orchestrates the entire graphical user interface. It initializes
    and manages all dockable widgets (like the Lens Editor and Analysis Panel),
    handles user actions through menus and toolbars, manages window layout and
    theming, and provides a scripting interface to control the application.

    Attributes:
        connector (OptilandConnector): The central connector for backend communication.
        iface (OptilandInterface): The scripting interface exposed to the Python
                                    console.
        all_managed_docks (list): A list of all dock widgets managed by the main
                                    window.
    """

    MAX_LAYOUT_SLOTS = 4
    MAX_RECENT_FILES = 10

    class OptilandInterface:
        """A high-level interface for controlling the Optiland GUI via scripting.

        This object is made available in the integrated Python console as 'iface',
        allowing users to programmatically interact with the main application
        components, such as opening panels, refreshing views, and accessing data.

        Args:
            main_window (MainWindow): A reference to the main application window.
        """

        def __init__(self, main_window):
            self._win = main_window

        def get_main_window(self):
            """Returns the main application window instance.

            Returns:
                MainWindow: The main QMainWindow instance.
            """
            return self._win

        def get_analysis_panel(self):
            """Returns the primary AnalysisPanel widget instance.

            Returns:
                AnalysisPanel: The main analysis panel widget.
            """
            return self._win.panel_manager.analysis_panel

        def get_lens_editor(self):
            """Returns the LensEditor widget instance.

            Returns:
                LensEditor: The lens data editor widget.
            """
            return self._win.panel_manager.lens_editor

        def get_viewer_panel(self):
            """Returns the ViewerPanel widget instance.

            Returns:
                ViewerPanel: The 2D/3D viewer panel widget.
            """
            return self._win.panel_manager.viewer_panel

        def get_catalog_browser_panel(self):
            """Returns the stock lens catalog browser panel."""
            return self._win.panel_manager.catalog_browser_panel

        def show_lens_editor(self):
            """Brings the Lens Data Editor dock widget to the front."""
            self._win.focus_dock_widget(self._win.panel_manager.lens_editor_dock)

        def show_analysis_panel(self):
            """Brings the Analysis Panel dock widget to the front."""
            dock = self._win.panel_manager.analysis_dock
            self._win.focus_dock_widget(dock)

        def show_catalog_browser(self):
            """Bring the stock lens catalog dock widget to the front."""
            dock = self._win.panel_manager.catalog_browser_dock
            self._win.focus_dock_widget(dock)

        def refresh_all(self):
            """Triggers a full refresh of all GUI panels.

            This is a convenience method that emits the `opticChanged` signal from
            the connector, prompting all connected widgets to reload their data.
            """
            print("GUI refresh requested via iface.refresh_all()")
            self._win.connector.opticChanged.emit()

    def __init__(self):
        """Initializes the MainWindow by orchestrating the setup of all
        UI components."""
        super().__init__()
        self._configure_window()
        self._init_core_components()
        self._init_ui()
        self._finalize_setup()

    def _init_ui(self):
        """Initializes the main UI components, panels, docks, and toolbars."""
        self.panel_manager.create_all_panels(self)
        self.action_manager.create_all_actions()
        self._setup_menus_and_toolbars()
        self._setup_layout()

    def _configure_window(self):
        """Sets up the main window's flags, title, and geometry."""
        self.setWindowTitle("Optiland GUI")
        self.setWindowIcon(QIcon(OPTILAND_ICON_PATH))
        self.setGeometry(100, 100, 1600, 900)

    def _init_core_components(self):
        """Initializes non-UI core components like settings, the connector,
        and the scripting interface."""
        self.analysis_panels = []
        self.settings = QSettings(ORGANIZATION_NAME, APPLICATION_NAME)
        self.current_theme_id = self.settings.value(
            "Appearance/ThemeId", DEFAULT_THEME_ID, type=str
        )
        self.current_theme_id = get_theme(self.current_theme_id).theme_id
        saved_slot_index = self.settings.value("Layouts/NextSaveSlot", 1, type=int)
        self.next_save_slot_index = min(max(saved_slot_index, 1), self.MAX_LAYOUT_SLOTS)
        self.connector = OptilandConnector()
        self.iface = self.OptilandInterface(self)
        self.panel_manager = PanelManager(self, self.connector)
        self.action_manager = ActionManager(self, self.connector)
        self.dock_animations = {}
        self.dock_original_sizes = {}
        self.about_dialog = None
        # These are initialised after the window is shown (needs parent geometry)
        self.toast_manager: ToastManager | None = None
        self.command_palette: CommandPaletteWidget | None = None
        self.command_registry = CommandRegistry.instance()
        self._recent_file_menus: list = []

    def _setup_menus_and_toolbars(self):
        """Creates and populates the main menu bar, custom title bar, and toolbars."""
        # Main Menu Bar
        self._native_menu_bar_instance = self.menuBar()
        self._populate_main_menu_bar(self._native_menu_bar_instance)

        self._fullscreen_menu_bar_instance = QMenuBar(self)
        self._populate_main_menu_bar(self._fullscreen_menu_bar_instance)

        # Custom Title Bar
        self.custom_title_bar_widget = CustomTitleBar(
            self._fullscreen_menu_bar_instance, self
        )
        self.custom_title_bar_widget.minimize_requested.connect(self.showMinimized)
        self.custom_title_bar_widget.maximize_restore_requested.connect(
            self._handle_maximize_restore
        )
        self.custom_title_bar_widget.fullscreen_requested.connect(
            self._toggle_fullscreen
        )
        self.custom_title_bar_widget.close_requested.connect(self.close)
        self.custom_title_bar_widget.settings_requested.connect(self.show_settings_wip)

        self.title_bar_as_toolbar = QToolBar("CustomTitleBarToolbar")
        self.title_bar_as_toolbar.setObjectName("CustomTitleBarToolbar")
        self.title_bar_as_toolbar.setMovable(False)
        self.title_bar_as_toolbar.setFloatable(False)
        self.title_bar_as_toolbar.addWidget(self.custom_title_bar_widget)
        self.addToolBar(Qt.TopToolBarArea, self.title_bar_as_toolbar)
        self.title_bar_as_toolbar.hide()

        # Quick Actions Toolbar
        self.quick_actions_toolbar = QToolBar("QuickActionsToolbar")
        self.quick_actions_toolbar.setObjectName("QuickActionsToolbar")
        self.quick_actions_toolbar.setMovable(True)
        self._populate_quick_actions_toolbar(self.quick_actions_toolbar)
        self.addToolBarBreak(Qt.TopToolBarArea)
        self.addToolBar(Qt.TopToolBarArea, self.quick_actions_toolbar)

    def _setup_layout(self):
        """Sets up the central widget and the default dock layout."""
        self.setDockNestingEnabled(True)
        self.setDockOptions(
            self.dockOptions()
            | QMainWindow.DockOption.AllowNestedDocks
            | QMainWindow.DockOption.AllowTabbedDocks
            | QMainWindow.DockOption.GroupedDragging
        )
        self._apply_revised_default_dock_layout()

    def _finalize_setup(self):
        """Applies stylesheets, connects signals, and sets the initial UI state."""
        self.load_stylesheets()
        self._sync_theme_actions()

        self._connect_dock_animations()
        self.panel_manager.connect_signals()

        self.connector.opticLoaded.connect(self._update_project_name_in_title_bar)
        self.connector.opticChanged.connect(self._update_project_name_in_title_bar)
        self.connector.modifiedStateChanged.connect(
            self._update_project_name_in_title_bar
        )

        # Toast manager — must be created after the window exists
        self.toast_manager = ToastManager(self)
        # Expose on connector so services can call it
        self.connector.toast_manager = self.toast_manager

        # Logging handler: route Python WARNING+ to toasts
        self._gui_log_handler = _log_handler.install(self.toast_manager)

        # Command palette (Ctrl+K)
        self.command_palette = CommandPaletteWidget(
            self, self.command_registry, self.settings
        )
        palette_shortcut = QShortcut(QKeySequence("Ctrl+K"), self)
        palette_shortcut.activated.connect(self.command_palette.toggle)

        # Register commands
        self._register_palette_commands()

        self._initial_narrow_check_done = False
        self._update_project_name_in_title_bar()
        self._was_maximized_before_fullscreen = False
        self._last_normal_geometry = self.settings.value("Window/NormalGeometry")
        self._apply_window_chrome(False)
        self._restore_window_placement()
        self._restore_current_layout_state()

    def _apply_revised_default_dock_layout(self):
        """Applies the default docking layout to the main window.

        This function arranges the dock widgets in a predefined layout, splitting
        and tabbing them to create a functional and organized user interface.
        This is called on first launch and when resetting the layout.
        """
        self._normalize_all_docks()
        self.panel_manager.setup_default_layout()

        # Initial plot/render
        viewer_panel = self.panel_manager.viewer_panel
        if viewer_panel.viewer2D and hasattr(viewer_panel.viewer2D, "plot_optic"):
            viewer_panel.viewer2D.plot_optic()
        if viewer_panel.viewer3D and hasattr(viewer_panel.viewer3D, "render_optic"):
            viewer_panel.viewer3D.render_optic()

    def _normalize_all_docks(self) -> None:
        """Clear transient animation state so docks return to normal Qt sizing."""
        if not hasattr(self, "panel_manager"):
            return
        for dock in self.panel_manager.get_all_docks():
            if dock:
                self._restore_dock_size_constraints(dock)

    def showEvent(self, event: QResizeEvent):
        """Handles the window show event.

        This overridden method performs initial setup tasks the first time the
        window is shown, such as adjusting the sidebar's collapsed state based
        on the initial window width.

        Args:
            event: The QShowEvent.
        """
        super().showEvent(event)
        if not self._initial_narrow_check_done:
            sidebar_widget = self.panel_manager.sidebar_content_widget
            sidebar_dock = self.panel_manager.sidebar
            if hasattr(self, "panel_manager") and sidebar_widget and sidebar_dock:
                if self.width() < (SIDEBAR_MAX_WIDTH + 300):
                    sidebar_widget.force_set_collapse_state(True)
                    if sidebar_dock.width() > SIDEBAR_MIN_WIDTH:
                        self.resizeDocks(
                            [sidebar_dock], [SIDEBAR_MIN_WIDTH], Qt.Horizontal
                        )
                else:
                    sidebar_widget.force_set_collapse_state(False)
                    if sidebar_dock.width() < SIDEBAR_MAX_WIDTH:
                        self.resizeDocks(
                            [sidebar_dock], [SIDEBAR_MAX_WIDTH], Qt.Horizontal
                        )
            self._initial_narrow_check_done = True

        self._sync_theme_actions()

    def _connect_dock_animations(self):
        """Connects dock widget view actions to an animation handler.

        This method disconnects the default `triggered` signal from each dock's
        toggle view action and reconnects it to a custom slot that provides a
        fade-in/out animation for a smoother user experience.
        """
        if not hasattr(self, "panel_manager"):
            return
        for dock_widget_ref in self.panel_manager.get_all_docks():
            if dock_widget_ref:
                if dock_widget_ref == self.panel_manager.sidebar:
                    continue
                action = dock_widget_ref.toggleViewAction()
                if action:
                    with contextlib.suppress(TypeError, RuntimeError):
                        action.triggered.disconnect()
                    action.triggered.connect(
                        lambda checked, dock=dock_widget_ref: self.animate_dock_toggle(
                            dock, checked
                        )
                    )

    def _populate_main_menu_bar(self, menu_bar: QMenuBar):
        """Populates the main menu bar with actions and sub-menus.

        Args:
            menu_bar: The QMenuBar instance to populate.
        """
        am = self.action_manager
        file_menu = menu_bar.addMenu("&File")
        file_menu.addActions(am.get_actions("new", "open", "save", "save_as"))
        file_menu.addSeparator()
        recent_menu = file_menu.addMenu("Recent Files")
        self._recent_file_menus.append(recent_menu)
        self._populate_recent_files_menu(recent_menu)
        file_menu.addSeparator()
        import_menu = file_menu.addMenu("&Import")
        import_menu.addActions(am.get_actions("import_zemax", "import_codev"))
        catalog_import_menu = import_menu.addMenu("&Catalog")
        catalog_import_menu.addActions(
            am.get_actions(
                "download_excelitas_catalog",
                "download_edmund_catalog",
                "download_thorlabs_catalog",
                "import_edmund_catalog",
                "import_thorlabs_catalog",
            )
        )
        export_menu = file_menu.addMenu("&Export")
        export_menu.addActions(am.get_actions("export_zemax", "export_codev"))
        file_menu.addSeparator()
        file_menu.addAction(am.get_action("exit"))

        edit_menu = menu_bar.addMenu("&Edit")
        edit_menu.addActions(am.get_actions("undo", "redo"))

        view_menu = menu_bar.addMenu("&View")
        view_menu.addActions(
            am.get_actions(
                "dock_all",
                "reset_layout",
                "toggle_fullscreen",
                "show_catalog_browser",
            )
        )
        view_menu.addSeparator()
        theme_menu = view_menu.addMenu("&Theme")
        dark_theme_menu = theme_menu.addMenu("&Dark")
        dark_theme_menu.addActions(am.get_theme_actions("dark"))
        light_theme_menu = theme_menu.addMenu("&Light")
        light_theme_menu.addActions(am.get_theme_actions("light"))
        view_menu.addSeparator()

        view_menu.addSeparator()

        # Add toggle actions for all managed docks
        if hasattr(self, "panel_manager"):
            for dock in self.panel_manager.get_all_docks():
                if dock and dock.toggleViewAction():
                    if dock == self.panel_manager.sidebar:
                        continue
                    # Create a friendlier name for the menu
                    action_text = f"Toggle {dock.windowTitle()}"
                    dock.toggleViewAction().setText(action_text)
                    view_menu.addAction(dock.toggleViewAction())

        self._populate_gallery_menu(menu_bar)

        menu_bar.addMenu("&Run")
        help_menu = menu_bar.addMenu("&Help")
        help_menu.addAction(am.get_action("about"))

    def _get_recent_files(self) -> list[str]:
        """Return the persisted recent file list, filtered to existing paths."""
        recent_files = self.settings.value("Files/Recent", [], type=list)
        if not isinstance(recent_files, list):
            return []
        return [path for path in recent_files if isinstance(path, str) and os.path.isfile(path)]

    def _set_recent_files(self, recent_files: list[str]) -> None:
        """Persist and refresh the recent file list."""
        self.settings.setValue("Files/Recent", recent_files[: self.MAX_RECENT_FILES])
        self._refresh_recent_file_menus()

    def _remember_recent_file(self, filepath: str) -> None:
        """Move *filepath* to the top of the recent file list."""
        normalized = os.path.normpath(filepath)
        recent_files = [
            path
            for path in self._get_recent_files()
            if os.path.normpath(path) != normalized
        ]
        recent_files.insert(0, filepath)
        self._set_recent_files(recent_files)

    def _populate_recent_files_menu(self, recent_menu) -> None:  # noqa: ANN001
        """Fill a single recent-files submenu."""
        recent_menu.clear()
        recent_files = self._get_recent_files()
        if not recent_files:
            action = recent_menu.addAction("No recent files")
            action.setEnabled(False)
            return

        for filepath in recent_files:
            action = recent_menu.addAction(os.path.basename(filepath))
            action.setToolTip(filepath)
            action.triggered.connect(
                lambda checked=False, path=filepath: self._open_recent_file(path)
            )

        recent_menu.addSeparator()
        clear_action = recent_menu.addAction("Clear Recent Files")
        clear_action.triggered.connect(lambda: self._set_recent_files([]))

    def _refresh_recent_file_menus(self) -> None:
        """Refresh all recent-files submenus currently attached to menu bars."""
        for recent_menu in self._recent_file_menus:
            self._populate_recent_files_menu(recent_menu)

    def _open_recent_file(self, filepath: str) -> None:
        """Open a file from the recent-files list if it still exists."""
        if not os.path.isfile(filepath):
            if self.toast_manager:
                self.toast_manager.notify(
                    f"Recent file not found: {filepath}", "warning"
                )
            recent_files = [
                path
                for path in self._get_recent_files()
                if os.path.normpath(path) != os.path.normpath(filepath)
            ]
            self._set_recent_files(recent_files)
            return
        self._open_system_from_path(filepath)

    def _open_system_from_path(self, filepath: str) -> None:
        """Load a system file and update related UI state."""
        self._remember_dialog_path("Paths/LastOpenDir", filepath)
        self._remember_recent_file(filepath)
        self.connector.load_optic_from_file(filepath)
        self._update_project_name_in_title_bar()
        logger.debug("Open System action triggered: %s", filepath)

    def _populate_quick_actions_toolbar(self, toolbar: QToolBar):
        """Populates the quick actions toolbar with common actions.

        Args:
            toolbar: The QToolBar instance to populate.
        """
        am = self.action_manager
        toolbar.addActions(am.get_actions("new", "open", "save"))
        toolbar.addSeparator()
        toolbar.addActions(
            am.get_actions(
                "load_layout_1",
                "load_layout_2",
                "load_layout_3",
                "load_layout_4",
                "save_layout",
            )
        )
        toolbar.addSeparator()
        toolbar.addActions(am.get_actions("dock_all", "reset_layout"))

    def _handle_maximize_restore(self) -> None:
        """Toggle between maximized and normal window states."""
        if self.isFullScreen():
            self._exit_fullscreen_to_previous_state()
            return
        self._capture_normal_window_geometry()
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def _toggle_fullscreen(self) -> None:
        """Toggle fullscreen while preserving the last normal window placement."""
        if self.isFullScreen():
            self._exit_fullscreen_to_previous_state()
            return

        self._capture_normal_window_geometry()
        self._was_maximized_before_fullscreen = self.isMaximized()
        self._apply_window_chrome(True)
        self.showFullScreen()

    def _exit_fullscreen_to_previous_state(self) -> None:
        """Leave fullscreen and restore the prior maximized/normal state."""
        self.showNormal()
        self._apply_window_chrome(False)
        if self._was_maximized_before_fullscreen:
            self.showMaximized()
        else:
            self._restore_last_normal_geometry()

    @Slot()
    def toggle_fullscreen_action(self) -> None:
        """Menu/shortcut entry point for fullscreen toggling."""
        self._toggle_fullscreen()

    def _apply_window_chrome(self, frameless: bool) -> None:
        """Switch between native window chrome and fullscreen frameless chrome."""
        self.set_frameless_mode(frameless)
        if hasattr(self, "title_bar_as_toolbar"):
            self.title_bar_as_toolbar.setVisible(frameless)
        if hasattr(self, "_native_menu_bar_instance") and self._native_menu_bar_instance:
            native_menu_bar = self._native_menu_bar_instance
            menu_action = getattr(native_menu_bar, "menuAction", None)
            if callable(menu_action):
                menu_action().setVisible(not frameless)
            else:
                native_menu_bar.setVisible(not frameless)

    def _capture_normal_window_geometry(self) -> None:
        """Remember the last non-maximized, non-fullscreen window geometry."""
        if not self.isMaximized() and not self.isFullScreen():
            self._last_normal_geometry = self.saveGeometry()

    def _restore_last_normal_geometry(self) -> None:
        """Restore the last remembered normal window geometry."""
        if isinstance(self._last_normal_geometry, QByteArray) and self._last_normal_geometry:
            self.restoreGeometry(self._last_normal_geometry)

    def _restore_window_placement(self) -> None:
        """Restore the last normal geometry and maximized state from settings."""
        self._last_normal_geometry = self.settings.value("Window/NormalGeometry")
        if isinstance(self._last_normal_geometry, QByteArray) and self._last_normal_geometry:
            self.restoreGeometry(self._last_normal_geometry)
        if self.settings.value("Window/WasMaximized", False, type=bool):
            self.showMaximized()

    def _save_window_placement(self) -> None:
        """Persist the last normal geometry and whether the window was maximized."""
        if self.isFullScreen():
            was_maximized = False
        else:
            self._capture_normal_window_geometry()
            was_maximized = self.isMaximized()

        if isinstance(self._last_normal_geometry, QByteArray) and self._last_normal_geometry:
            self.settings.setValue("Window/NormalGeometry", self._last_normal_geometry)
        self.settings.setValue("Window/WasMaximized", was_maximized)

    def _restore_current_layout_state(self) -> None:
        """Restore the last automatically persisted dock layout, if available."""
        state = self.settings.value("Layouts/CurrentState")
        if not isinstance(state, QByteArray) or state.isEmpty():
            return
        if not self.restoreState(state):
            logger.warning("Failed to restore the last session dock layout.")
            return
        self._normalize_all_docks()

    def _save_current_layout_state(self) -> None:
        """Persist the current dock layout, including docking and visibility."""
        self._normalize_all_docks()
        self.settings.setValue("Layouts/CurrentState", self.saveState())

    def changeEvent(self, event: QEvent) -> None:
        """Update the maximize button state when the window state changes."""
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange and (
            hasattr(self, "custom_title_bar_widget") and self.custom_title_bar_widget
        ):
            if not self.isFullScreen():
                self._capture_normal_window_geometry()
            self.custom_title_bar_widget.update_maximize_button_state(
                self.isMaximized()
            )
            self.custom_title_bar_widget.update_fullscreen_button_state(
                self.isFullScreen()
            )

    def load_stylesheets(self) -> None:
        """Load and apply the current theme and sidebar stylesheets."""
        style_str = ""
        theme = get_theme(self.current_theme_id)
        try:
            with open(theme.base_path) as f_theme:
                style_str += f_theme.read()
        except Exception as e:
            print(f"Error loading main theme {theme.base_path}: {e}")

        if os.path.exists(SIDEBAR_QSS_PATH):
            try:
                with open(SIDEBAR_QSS_PATH) as f_sidebar:
                    style_str += "\n" + f_sidebar.read()

            except Exception as e:
                print(f"Error loading sidebar stylesheet {SIDEBAR_QSS_PATH}: {e}")

        style_str += "\n" + build_palette_override(theme)
        self.setStyleSheet(style_str)

        is_dark = theme.mode == "dark"
        theme_name = theme.mode
        gui_plot_utils.apply_gui_matplotlib_styles(theme=theme_name)
        # Also apply the new theme-specific rcParams overrides
        apply_plot_theme(is_dark)

        if hasattr(self, "panel_manager"):
            self.panel_manager.update_theme(theme_name)
        if hasattr(self, "custom_title_bar_widget"):
            self.custom_title_bar_widget.setStyleSheet(style_str)
            self.custom_title_bar_widget.update_theme_icons(theme_name)
            self.custom_title_bar_widget.update_maximize_button_state(
                self.isMaximized()
            )
            self.custom_title_bar_widget.update_fullscreen_button_state(
                self.isFullScreen()
            )
        self._sync_theme_actions()

    def _sync_theme_actions(self) -> None:
        """Update check state for all theme actions."""
        for theme in THEMES:
            action = self.action_manager.get_action(f"theme_{theme.theme_id}")
            if action:
                action.setChecked(theme.theme_id == self.current_theme_id)

    def _update_project_name_in_title_bar(self) -> None:
        """Update the project name displayed in the custom title bar."""
        if hasattr(self, "custom_title_bar_widget") and self.custom_title_bar_widget:
            display_name = "UnnamedProject.json"
            current_file = self.connector.get_current_filepath()
            is_modified = self.connector.is_modified()

            if current_file:
                display_name = os.path.basename(current_file)

            if not current_file:
                is_modified = True

            if is_modified:
                display_name += "*"

            self.custom_title_bar_widget.set_project_name(display_name)

    def _animate_dock_show(
        self, dock_widget, is_left_or_right, original_dimension, duration, curve
    ):
        """Handles the animation for showing a dock widget."""
        if dock_widget.isHidden():
            dock_widget.show()
            self.focus_dock_widget(dock_widget)
            target_prop = b"maximumWidth" if is_left_or_right else b"maximumHeight"
            animation = QPropertyAnimation(dock_widget, target_prop)
            animation.setStartValue(0)
            animation.setEndValue(original_dimension)
            self._set_dock_dimension_limit(
                dock_widget,
                is_left_or_right,
                original_dimension if original_dimension > 0 else 5000,
            )
            animation.setDuration(duration)
            animation.setEasingCurve(curve)
            self._track_dock_animation(dock_widget, animation)
            animation.start()
        else:
            self.focus_dock_widget(dock_widget)

    def focus_dock_widget(self, dock_widget: QDockWidget) -> None:
        """Show and focus a dock without forcing invalid top-level raises."""
        if dock_widget is None:
            return
        dock_widget.show()
        parent_tab_widget = dock_widget.parentWidget()
        if isinstance(parent_tab_widget, QTabWidget):
            parent_tab_widget.setCurrentWidget(dock_widget)
        dock_widget.setFocus(Qt.FocusReason.OtherFocusReason)
        if dock_widget.isFloating():
            top_level = dock_widget.window()
            if top_level is not None and top_level.isWindow():
                top_level.raise_()
                top_level.activateWindow()

    def _animate_dock_hide(
        self, dock_widget, is_left_or_right, original_dimension, duration, curve
    ):
        """Handles the animation for hiding a dock widget."""
        if not dock_widget.isHidden():
            current_size = (
                dock_widget.width() if is_left_or_right else dock_widget.height()
            )
            if current_size > 0:
                self.dock_original_sizes[dock_widget] = current_size
            target_prop = b"maximumWidth" if is_left_or_right else b"maximumHeight"
            animation = QPropertyAnimation(dock_widget, target_prop)
            animation.setStartValue(current_size)
            animation.setEndValue(0)
            animation.setDuration(duration)
            animation.setEasingCurve(curve)
            animation.finished.connect(dock_widget.hide)
            animation.finished.connect(lambda: self._restore_dock_size_constraints(dock_widget))
            self._track_dock_animation(dock_widget, animation)
            animation.start()

    def _set_dock_dimension_limit(
        self, dock_widget: QDockWidget, is_left_or_right: bool, value: int
    ) -> None:
        """Set the active animation limit on the dimension being animated."""
        if is_left_or_right:
            dock_widget.setMaximumWidth(value)
        else:
            dock_widget.setMaximumHeight(value)

    def _restore_dock_size_constraints(self, dock_widget: QDockWidget) -> None:
        """Remove temporary max-size limits applied during dock animations."""
        dock_widget.setMaximumSize(16777215, 16777215)

    def _track_dock_animation(
        self, dock_widget: QDockWidget, animation: QPropertyAnimation
    ) -> None:
        """Store a live dock animation and clear it when the Qt object goes away."""
        self.dock_animations[dock_widget] = animation

        def cleanup() -> None:
            if self.dock_animations.get(dock_widget) is animation:
                self.dock_animations.pop(dock_widget, None)

        animation.finished.connect(cleanup)
        animation.finished.connect(lambda: self._restore_dock_size_constraints(dock_widget))
        animation.finished.connect(animation.deleteLater)
        animation.destroyed.connect(cleanup)

    def _get_live_dock_animation(
        self, dock_widget: QDockWidget
    ) -> QPropertyAnimation | None:
        """Return the current dock animation if its underlying Qt object still exists."""
        animation = self.dock_animations.get(dock_widget)
        if animation is None:
            return None
        try:
            animation.state()
        except RuntimeError:
            self.dock_animations.pop(dock_widget, None)
            return None
        return animation

    def animate_dock_toggle(
        self, dock_widget: QDockWidget, show_state_after_toggle: bool
    ) -> None:
        """Toggle a dock widget visibility with a slide/fade animation.

        Args:
            dock_widget: The dock widget to show or hide.
            show_state_after_toggle: ``True`` to show, ``False`` to hide.
        """
        animation_duration = 150
        easing_curve = QEasingCurve.InOutQuad
        is_left_or_right_dock = self.dockWidgetArea(dock_widget) in [
            Qt.LeftDockWidgetArea,
            Qt.RightDockWidgetArea,
        ]

        # Determine the dimension to animate
        if (
            hasattr(self, "panel_manager")
            and dock_widget == self.panel_manager.sidebar
            and self.panel_manager.sidebar_content_widget
        ):
            original_dimension = (
                self.panel_manager.sidebar_content_widget.maximumWidth()
                if not self.panel_manager.sidebar_content_widget._is_collapsed
                else self.panel_manager.sidebar_content_widget.minimumWidth()
            )
        else:
            default_size = 300 if is_left_or_right_dock else 200
            current_size = (
                dock_widget.width() if is_left_or_right_dock else dock_widget.height()
            )
            original_dimension = self.dock_original_sizes.get(
                dock_widget, current_size if current_size > 0 else default_size
            )

        # Stop any currently running animation on this dock
        current_animation = self._get_live_dock_animation(dock_widget)
        if current_animation and current_animation.state() == QPropertyAnimation.Running:
            current_animation.stop()

        if show_state_after_toggle:
            self._animate_dock_show(
                dock_widget,
                is_left_or_right_dock,
                original_dimension,
                animation_duration,
                easing_curve,
            )
        else:
            self._animate_dock_hide(
                dock_widget,
                is_left_or_right_dock,
                original_dimension,
                animation_duration,
                easing_curve,
            )

    @Slot(str)
    def switch_theme(self, theme_id: str) -> None:
        """Switch the application theme to *theme_id*.

        Args:
            theme_id: Registered theme id to apply.
        """
        theme = get_theme(theme_id)
        if theme.theme_id != self.current_theme_id:
            self.current_theme_id = theme.theme_id
            self.settings.setValue("Appearance/ThemeId", self.current_theme_id)
            self.load_stylesheets()

    @Slot()
    def refresh_all_gui_panels(self) -> None:
        """Re-emit :attr:`opticChanged` to refresh all connected panels."""
        self.connector.opticChanged.emit()

    def _remember_dialog_path(self, key: str, filepath: str) -> None:
        """Persist the parent directory of *filepath* for future dialogs."""
        directory = os.path.dirname(filepath)
        if directory:
            self.settings.setValue(key, directory)

    def _get_dialog_start_dir(self, primary_key: str, fallback_key: str = "") -> str:
        """Return the preferred start directory for file dialogs."""
        for key in (primary_key, fallback_key):
            if not key:
                continue
            value = self.settings.value(key, "", type=str)
            if value and os.path.isdir(value):
                return value

        current_path = self.connector.get_current_filepath()
        if current_path:
            current_dir = os.path.dirname(current_path)
            if current_dir and os.path.isdir(current_dir):
                return current_dir
        return ""

    @Slot()
    def new_system_action(self) -> None:
        """Slot for the *New System* action."""
        self.connector.new_system()
        self._update_project_name_in_title_bar()
        logger.debug("New System action triggered")

    @Slot()
    def open_system_action(self) -> None:
        """Slot for the *Open System* action — shows a file chooser dialog."""
        filepath, _ = QFileDialog.getOpenFileName(
            self,
            "Open Optiland System",
            self._get_dialog_start_dir("Paths/LastOpenDir", "Paths/LastSaveDir"),
            "Optiland JSON Files (*.json);;Zemax Files (*.zmx);;All Files (*)",
        )
        if filepath:
            self._open_system_from_path(filepath)

    @Slot()
    def save_system_action(self) -> None:
        """Slot for the *Save System* action — saves to the current file path."""
        current_path = self.connector.get_current_filepath()
        if current_path:
            self.connector.save_optic_to_file(current_path)
            self._remember_dialog_path("Paths/LastSaveDir", current_path)
            self._update_project_name_in_title_bar()
            logger.debug("Save System action triggered: %s", current_path)
        else:
            self.save_system_as_action()

    @Slot()
    def save_system_as_action(self) -> None:
        """Slot for *Save System As* — prompts for a file path."""
        filepath, selected_filter = QFileDialog.getSaveFileName(
            self,
            "Save Optiland System As...",
            self._get_dialog_start_dir("Paths/LastSaveDir", "Paths/LastOpenDir"),
            "Optiland JSON Files (*.json);;All Files (*)",
        )
        if filepath:
            if (
                not filepath.lower().endswith(".json")
                and "(*.json)" in selected_filter.split(";;")[0]
            ):
                filepath += ".json"
            self.connector.save_optic_to_file(filepath)
            self._remember_dialog_path("Paths/LastSaveDir", filepath)
            self._update_project_name_in_title_bar()
            logger.debug("Save System As action triggered: %s", filepath)

    def _confirm_discard_changes(self) -> bool:
        """Prompt the user to confirm discarding unsaved changes.

        Returns:
            ``True`` if the user confirms (or there are no unsaved changes),
            ``False`` if the user cancels.
        """
        if not self.connector.is_modified():
            return True
        reply = QMessageBox.question(
            self,
            "Unsaved Changes",
            "The current system has unsaved changes. "
            "Importing will replace it. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        return reply == QMessageBox.StandardButton.Yes

    @Slot()
    def import_zemax_action(self):
        """Show a file dialog and import a Zemax .zmx file."""
        if not self._confirm_discard_changes():
            return
        filepath, _ = QFileDialog.getOpenFileName(
            self,
            "Import Zemax File",
            self._get_dialog_start_dir("Paths/LastOpenDir", "Paths/LastSaveDir"),
            "Zemax Files (*.zmx);;All Files (*)",
        )
        if filepath:
            self._remember_dialog_path("Paths/LastOpenDir", filepath)
            self.connector.import_zemax(filepath)
            self._update_project_name_in_title_bar()

    @Slot()
    def import_codev_action(self):
        """Show a file dialog and import a CODE V .seq file."""
        if not self._confirm_discard_changes():
            return
        filepath, _ = QFileDialog.getOpenFileName(
            self,
            "Import CODE V File",
            self._get_dialog_start_dir("Paths/LastOpenDir", "Paths/LastSaveDir"),
            "CODE V Files (*.seq);;All Files (*)",
        )
        if filepath:
            self._remember_dialog_path("Paths/LastOpenDir", filepath)
            self.connector.import_codev(filepath)
            self._update_project_name_in_title_bar()

    def _import_catalog_file_for_manufacturer(self, manufacturer: str) -> None:
        """Show a file dialog and import a local catalog file."""
        filepaths, _ = QFileDialog.getOpenFileNames(
            self,
            f"Import {manufacturer} Catalog",
            self._get_dialog_start_dir("Paths/LastOpenDir", "Paths/LastSaveDir"),
            "Catalog Files (*.zip *.zmx *.zmf *.json);;Catalog Archives (*.zip);;Zemax Files (*.zmx);;Zemax Catalog Files (*.zmf);;Normalized Catalog JSON (*.json);;All Files (*)",
        )
        if not filepaths:
            return
        try:
            count = self.connector.import_catalog_file(manufacturer, filepaths)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Catalog Import Failed", str(exc))
            return
        self._remember_dialog_path("Paths/LastOpenDir", filepaths[0])
        if self.toast_manager:
            self.toast_manager.notify(
                f"Imported {count} {manufacturer} catalog entries.",
                "success",
            )

    @Slot()
    def import_edmund_catalog_action(self) -> None:
        """Import a local Edmund stock-lens catalog file."""
        self._import_catalog_file_for_manufacturer("Edmund")

    @Slot()
    def download_edmund_catalog_action(self) -> None:
        """Download Edmund's official online catalog archive and import supported files."""
        try:
            result = self.connector.download_edmund_catalog()
        except Exception as exc:  # noqa: BLE001
            self._show_edmund_download_help(str(exc))
            return
        if self.toast_manager:
            level = "success" if result.imported_count else "info"
            self.toast_manager.notify(result.message, level, sub_message=result.archive_path)

    @Slot()
    def download_excelitas_catalog_action(self) -> None:
        """Download Excelitas / LINOS official shop metadata and linked Zemax files."""
        try:
            result = self.connector.download_excelitas_catalog()
        except Exception as exc:  # noqa: BLE001
            self._show_excelitas_download_help(str(exc))
            return
        if self.toast_manager:
            level = "success" if result.imported_count else "info"
            self.toast_manager.notify(result.message, level, sub_message=result.archive_path)

    @Slot()
    def download_thorlabs_catalog_action(self) -> None:
        """Download Thorlabs' official online catalog package and import supported files."""
        try:
            result = self.connector.download_thorlabs_catalog()
        except Exception as exc:  # noqa: BLE001
            self._show_thorlabs_download_help(str(exc))
            return
        if self.toast_manager:
            level = "success" if result.imported_count else "info"
            self.toast_manager.notify(result.message, level, sub_message=result.archive_path)

    def _show_edmund_download_help(self, error_text: str) -> None:
        """Show a guided fallback dialog when Edmund blocks auto-download."""
        dialog = QMessageBox(self)
        dialog.setIcon(QMessageBox.Icon.Warning)
        dialog.setWindowTitle("Edmund Catalog Download Failed")
        dialog.setText("Automatic download was blocked by Edmund.")
        dialog.setInformativeText(
            "Open the official Edmund Zemax Catalog page in your browser, download the "
            "archive manually, and then import the downloaded ZIP, ZMX, or ZMF file."
        )
        dialog.setDetailedText(error_text)
        open_button = dialog.addButton(
            "Open Download Page",
            QMessageBox.ButtonRole.ActionRole,
        )
        import_button = dialog.addButton(
            "Import Downloaded File...",
            QMessageBox.ButtonRole.ActionRole,
        )
        dialog.addButton(QMessageBox.StandardButton.Close)
        dialog.exec()

        clicked = dialog.clickedButton()
        if clicked == open_button:
            QDesktopServices.openUrl(QUrl(EDMUND_ZEMAX_PAGE_URL))
        elif clicked == import_button:
            self._import_catalog_file_for_manufacturer("Edmund")

    def _show_excelitas_download_help(self, error_text: str) -> None:
        """Show a guided fallback dialog when Excelitas auto-download is incomplete."""
        dialog = QMessageBox(self)
        dialog.setIcon(QMessageBox.Icon.Warning)
        dialog.setWindowTitle("Excelitas / LINOS Catalog Download Failed")
        dialog.setText("Automatic catalog download could not be completed.")
        dialog.setInformativeText(
            "Open the official LINOS / Excelitas product pages in your browser and "
            "download any available ZEMAX files manually. You can then import the "
            "downloaded ZIP, ZMX, or ZMF file."
        )
        dialog.setDetailedText(error_text)
        open_button = dialog.addButton(
            "Open Product Pages",
            QMessageBox.ButtonRole.ActionRole,
        )
        import_button = dialog.addButton(
            "Import Downloaded File...",
            QMessageBox.ButtonRole.ActionRole,
        )
        dialog.addButton(QMessageBox.StandardButton.Close)
        dialog.exec()

        clicked = dialog.clickedButton()
        if clicked == open_button:
            QDesktopServices.openUrl(QUrl("https://linosoptics.excelitas.com/en/"))
        elif clicked == import_button:
            self._import_catalog_file_for_manufacturer("Excelitas")

    def _show_thorlabs_download_help(self, error_text: str) -> None:
        """Show a guided fallback dialog when Thorlabs auto-download fails."""
        dialog = QMessageBox(self)
        dialog.setIcon(QMessageBox.Icon.Warning)
        dialog.setWindowTitle("Thorlabs Catalog Download Failed")
        dialog.setText("Automatic download was not available from Thorlabs.")
        dialog.setInformativeText(
            "Open the official Thorlabs Zemax page in your browser, download the "
            "catalog package manually, and then import the downloaded ZIP, ZMX, or ZMF file."
        )
        dialog.setDetailedText(error_text)
        open_button = dialog.addButton(
            "Open Download Page",
            QMessageBox.ButtonRole.ActionRole,
        )
        import_button = dialog.addButton(
            "Import Downloaded File...",
            QMessageBox.ButtonRole.ActionRole,
        )
        dialog.addButton(QMessageBox.StandardButton.Close)
        dialog.exec()

        clicked = dialog.clickedButton()
        if clicked == open_button:
            QDesktopServices.openUrl(QUrl(THORLABS_ZEMAX_PAGE_URL))
        elif clicked == import_button:
            self._import_catalog_file_for_manufacturer("Thorlabs")

    @Slot()
    def import_thorlabs_catalog_action(self) -> None:
        """Import a local Thorlabs stock-lens catalog file."""
        self._import_catalog_file_for_manufacturer("Thorlabs")

    @Slot()
    def show_catalog_browser_action(self) -> None:
        """Show and raise the stock lens catalog browser dock."""
        if hasattr(self, "panel_manager") and self.panel_manager.catalog_browser_dock:
            self.focus_dock_widget(self.panel_manager.catalog_browser_dock)

    @Slot()
    def export_zemax_action(self):
        """Show a file dialog and export the current system as a Zemax .zmx file."""
        filepath, _ = QFileDialog.getSaveFileName(
            self,
            "Export to Zemax",
            self._get_dialog_start_dir("Paths/LastSaveDir", "Paths/LastOpenDir"),
            "Zemax Files (*.zmx);;All Files (*)",
        )
        if filepath:
            if not filepath.lower().endswith(".zmx"):
                filepath += ".zmx"
            self._remember_dialog_path("Paths/LastSaveDir", filepath)
            self.connector.export_zemax(filepath)

    @Slot()
    def export_codev_action(self):
        """Show a file dialog and export the current system as a CODE V .seq file."""
        filepath, _ = QFileDialog.getSaveFileName(
            self,
            "Export to CODE V",
            self._get_dialog_start_dir("Paths/LastSaveDir", "Paths/LastOpenDir"),
            "CODE V Files (*.seq);;All Files (*)",
        )
        if filepath:
            if not filepath.lower().endswith(".seq"):
                filepath += ".seq"
            self._remember_dialog_path("Paths/LastSaveDir", filepath)
            self.connector.export_codev(filepath)

    @Slot()
    def about_action(self):
        if not self.about_dialog:
            self.about_dialog = QDialog(self)
            self.about_dialog.setWindowTitle("About Optiland GUI")
            layout = QVBoxLayout(self.about_dialog)
            about_text = QLabel(
                "<p><b>Optiland GUI</b></p>"
                "<p>A modern interface for the Optiland optical simulation package.</p>"
                "<p>Version: 0.2.1 (Frameless Layout Refined)</p>"
                "<p>Built with PySide6.</p>"
                "<hr>"
                "<p><b>Icon Copyright Notice:</b></p>"
                "<p>Icons are provided under the MIT License.</p>"
                "<p>Copyright (c) 2020-2024 Paweł Kuna</p>"
            )
            about_text.setTextFormat(Qt.TextFormat.RichText)
            about_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(about_text)
            ok_button = QPushButton("OK")
            ok_button.clicked.connect(self.about_dialog.accept)
            layout.addWidget(ok_button, alignment=Qt.AlignmentFlag.AlignCenter)
            self.about_dialog.setLayout(layout)
            self.about_dialog.setMinimumSize(350, 220)
            self.about_dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
            self.about_dialog.setWindowOpacity(0.0)
            self.about_dialog_animation = QPropertyAnimation(
                self.about_dialog, b"windowOpacity"
            )
            self.about_dialog_animation.setDuration(300)
            self.about_dialog_animation.setStartValue(0.0)
            self.about_dialog_animation.setEndValue(1.0)
            self.about_dialog_animation.setEasingCurve(QEasingCurve.InOutQuad)
            self.about_dialog_animation.start(
                QPropertyAnimation.DeletionPolicy.DeleteWhenStopped
            )
        self.about_dialog.exec()

    @Slot()
    def reset_windows_action(self) -> None:
        """Reset the dock layout to the application default."""
        logger.debug("Reset Windows action triggered.")
        self._apply_revised_default_dock_layout()
        if hasattr(self, "panel_manager"):
            for dock in self.panel_manager.get_all_docks():
                if dock and dock.toggleViewAction():
                    if dock == self.panel_manager.sidebar:
                        continue
                    dock.toggleViewAction().setChecked(True)

    @Slot()
    def save_layout_slot(self):
        target_slot, ok = QInputDialog.getInt(
            self,
            "Save Layout",
            "Save current layout to slot:",
            value=self.next_save_slot_index,
            minValue=1,
            maxValue=self.MAX_LAYOUT_SLOTS,
        )
        if not ok:
            return

        window_geometry = self.saveGeometry()
        dock_toolbar_state = self.saveState()
        self.settings.setValue(f"Layouts/Config{target_slot}Geometry", window_geometry)
        self.settings.setValue(f"Layouts/Config{target_slot}State", dock_toolbar_state)
        if self.toast_manager:
            self.toast_manager.notify(
                f"Layout saved to configuration — {target_slot}", "success"
            )
        self.next_save_slot_index = target_slot
        self.settings.setValue("Layouts/NextSaveSlot", self.next_save_slot_index)
        self._update_layout_slot_actions()
        logger.debug(
            "Layout saved to slot %d. Next save dialog will default to slot %d.",
            target_slot,
            self.next_save_slot_index,
        )

    def _update_layout_slot_actions(self) -> None:
        """Refresh enabled state for all layout-slot load actions."""
        for slot in range(1, self.MAX_LAYOUT_SLOTS + 1):
            load_action = self.action_manager.get_action(f"load_layout_{slot}")
            if load_action:
                load_action.setEnabled(
                    self.settings.contains(f"Layouts/Config{slot}Geometry")
                )

    def _load_layout_from_slot(self, slot_number):
        geometry_key = f"Layouts/Config{slot_number}Geometry"
        state_key = f"Layouts/Config{slot_number}State"
        if self.settings.contains(geometry_key) and self.settings.contains(state_key):
            window_geometry = self.settings.value(geometry_key)
            dock_toolbar_state = self.settings.value(state_key)
            if isinstance(window_geometry, QByteArray) and isinstance(
                dock_toolbar_state, QByteArray
            ):
                if not self.restoreGeometry(window_geometry):
                    logger.warning(
                        "Failed to restore window geometry from slot %d.",
                        slot_number,
                    )
                if not self.restoreState(dock_toolbar_state):
                    logger.warning(
                        "Failed to restore dock/toolbar state from slot %d.",
                        slot_number,
                    )
                self._normalize_all_docks()
                if self.toast_manager:
                    self.toast_manager.notify(
                        f"Layout from configuration — {slot_number} loaded.", "success"
                    )
            else:
                if self.toast_manager:
                    self.toast_manager.notify(
                        f"Invalid layout data in configuration — {slot_number}.",
                        "warning",
                    )
        else:
            if self.toast_manager:
                self.toast_manager.notify(
                    f"No layout saved in configuration — {slot_number}.", "info"
                )

    @Slot()
    def load_layout_1_slot(self) -> None:
        """Load the window layout saved in slot 1."""
        logger.debug("Loading layout from slot 1.")
        self._load_layout_from_slot(1)

    @Slot()
    def load_layout_2_slot(self) -> None:
        """Load the window layout saved in slot 2."""
        logger.debug("Loading layout from slot 2.")
        self._load_layout_from_slot(2)

    @Slot()
    def load_layout_3_slot(self) -> None:
        """Load the window layout saved in slot 3."""
        logger.debug("Loading layout from slot 3.")
        self._load_layout_from_slot(3)

    @Slot()
    def load_layout_4_slot(self) -> None:
        """Load the window layout saved in slot 4."""
        logger.debug("Loading layout from slot 4.")
        self._load_layout_from_slot(4)

    def closeEvent(self, event: QEvent) -> None:
        """Shut down the Jupyter kernel and accept the close event."""
        logger.debug("Closing application.")
        self._save_window_placement()
        self._save_current_layout_state()
        if hasattr(self, "panel_manager") and self.panel_manager.python_terminal:
            self.panel_manager.python_terminal.shutdown_kernel()
        event.accept()

    @Slot()
    def show_settings_wip(self):
        """Shows a 'Work in Progress' message for the settings panel."""
        if self.toast_manager:
            self.toast_manager.notify(
                "The settings panel is currently under development.", "info"
            )

    def _populate_gallery_menu(self, menu_bar: QMenuBar) -> None:
        """Create the 'Gallery' menu by inspecting the samples package."""
        gallery_menu = menu_bar.addMenu("&Gallery")
        samples_menu = gallery_menu.addMenu("&Samples")

        systems_by_module = defaultdict(list)

        for _, obj_class in inspect.getmembers(optiland.samples, inspect.isclass):
            if issubclass(obj_class, Optic) and obj_class is not Optic:
                module_name = obj_class.__module__.split(".")[-1]
                systems_by_module[module_name].append(obj_class)

        if not systems_by_module:
            samples_menu.addAction("No samples found.").setEnabled(False)
            return

        for module_name, classes in sorted(systems_by_module.items()):
            submenu_name = module_name.replace("_", " ").title()
            submenu = samples_menu.addMenu(submenu_name)
            for optic_class in sorted(classes, key=lambda c: c.__name__):
                action_name = optic_class.__name__.replace("_", " ").title()
                action = QAction(action_name, self)
                action.triggered.connect(
                    lambda checked=False, cls=optic_class: self._load_sample_action(cls)
                )
                submenu.addAction(action)

    def _register_palette_commands(self) -> None:
        """Populate the :class:`CommandRegistry` with app-level commands."""
        reg = self.command_registry
        am = self.action_manager

        # --- File actions ---
        _file_cmds = [
            ("New", "Create a new optical system", "new", "Ctrl+N", "File"),
            ("Open", "Open an existing system file", "open", "Ctrl+O", "File"),
            ("Save", "Save the current system", "save", "Ctrl+S", "File"),
            ("Save As", "Save to a new file", "save_as", "", "File"),
            (
                "Import Edmund Catalog",
                "Import a local Edmund stock-lens catalog",
                "import_edmund_catalog",
                "",
                "File",
            ),
            (
                "Import Thorlabs Catalog",
                "Import a local Thorlabs stock-lens catalog",
                "import_thorlabs_catalog",
                "",
                "File",
            ),
        ]
        for name, desc, action_key, shortcut, cat in _file_cmds:
            action = am.get_action(action_key)
            if action:
                reg.register(
                    PaletteCommand(
                        name=name,
                        description=desc,
                        callback=action.trigger,
                        shortcut=shortcut,
                        category=cat,
                    )
                )

        # --- View / theme ---
        for theme in THEMES:
            action = am.get_action(f"theme_{theme.theme_id}")
            if action:
                reg.register(
                    PaletteCommand(
                        theme.label,
                        f"Switch to the {theme.label} theme",
                        action.trigger,
                        category="Settings",
                    )
                )

        fullscreen_action = am.get_action("toggle_fullscreen")
        if fullscreen_action:
            reg.register(
                PaletteCommand(
                    "Toggle Full Screen",
                    "Enter or exit full screen mode",
                    fullscreen_action.trigger,
                    shortcut="F11",
                    category="Settings",
                )
            )

        catalog_action = am.get_action("show_catalog_browser")
        if catalog_action:
            reg.register(
                PaletteCommand(
                    "Show Stock Lens Catalog",
                    "Open the stock-lens catalog browser",
                    catalog_action.trigger,
                    category="Panels",
                )
            )

        reset_action = am.get_action("reset_layout")
        if reset_action:
            reg.register(
                PaletteCommand(
                    "Reset Layout",
                    "Reset to default dock layout",
                    reset_action.trigger,
                    category="Settings",
                )
            )

        # --- Analysis types ---
        if hasattr(self, "panel_manager") and self.panel_manager.analysis_panel:
            ap = self.panel_manager.analysis_panel
            for analysis_name in ap._analysis_class_map:
                reg.register(
                    PaletteCommand(
                        name=f"Run {analysis_name}",
                        description=f"Open Analysis panel and run {analysis_name}",
                        callback=lambda n=analysis_name: (
                            self._run_analysis_from_palette(n)
                        ),
                        keywords=["analysis", analysis_name.lower()],
                        category="Analysis",
                    )
                )

    def _run_analysis_from_palette(self, analysis_name: str) -> None:
        """Show the analysis panel and run *analysis_name*."""
        pm = self.panel_manager
        if hasattr(pm, "analysis_dock") and pm.analysis_dock:
            self.focus_dock_widget(pm.analysis_dock)
        if hasattr(pm, "analysis_panel") and pm.analysis_panel:
            ap = pm.analysis_panel
            ap.analysisTypeCombo.setCurrentText(analysis_name)
            ap.run_analysis_slot()

    def resizeEvent(self, event: QResizeEvent) -> None:
        """Reposition toasts when the window resizes."""
        super().resizeEvent(event)
        self._capture_normal_window_geometry()
        if self.toast_manager:
            self.toast_manager.reposition()
        if self.command_palette and self.command_palette._visible:
            self.command_palette._reposition()

    def moveEvent(self, event: QMoveEvent) -> None:
        """Track the latest normal window position for session restore."""
        super().moveEvent(event)
        self._capture_normal_window_geometry()

    def _load_sample_action(self, optic_class: type[Optic]) -> None:
        """Instantiate and load the selected sample class.

        Args:
            optic_class: The sample :class:`~optiland.optic.Optic` subclass to load.
        """
        try:
            optic_instance = optic_class()
            self.connector.load_optic_from_object(optic_instance)
            print(f"Loaded sample: {optic_class.__name__}")

        except Exception as e:
            msg = f"Could not load sample '{optic_class.__name__}': {e}"
            if self.toast_manager:
                self.toast_manager.notify(msg, "error")
            else:
                QMessageBox.critical(self, "Sample Load Error", msg)
