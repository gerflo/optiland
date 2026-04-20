"""Manages the creation and handling of QActions for the Optiland GUI.

This module provides :class:`ActionManager`, which is responsible for
instantiating and configuring all the :class:`~PySide6.QtGui.QAction` objects
used in the application's menus and toolbars.  Separating action definitions
from the main window keeps :class:`~optiland_gui.main_window.MainWindow` lean
and focused on layout / orchestration."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtGui import QAction, QActionGroup, QKeySequence

from .theme_manager import THEMES

if TYPE_CHECKING:
    from PySide6.QtWidgets import QMainWindow

    from .optiland_connector import OptilandConnector


class ActionManager:
    """Creates and manages all :class:`QAction` objects for the application.

    Args:
        main_window: The application's main window.
        connector: Central :class:`~optiland_gui.optiland_connector.OptilandConnector`
            instance, used to wire undo/redo signal connections.
    """

    def __init__(self, main_window: QMainWindow, connector: OptilandConnector) -> None:
        self.main_window = main_window
        self.connector = connector
        self.actions: dict[str, QAction | QActionGroup] = {}

    def create_all_actions(self) -> None:
        """Create all actions and store them in the :attr:`actions` dictionary."""
        self._create_file_actions()
        self._create_edit_actions()
        self._create_view_actions()
        self._create_layout_actions()
        self._create_theme_actions()
        self._create_help_actions()

    def _create_action(
        self,
        name: str,
        text: str,
        shortcut: QKeySequence | str | None = None,
        triggered: object | None = None,
        tooltip: str | None = None,
        checkable: bool = False,
    ) -> QAction:
        """Factory method for creating and registering a single :class:`QAction`.

        Args:
            name: Registry key used to retrieve the action later.
            text: Display text (used in menus and tooltips).
            shortcut: Optional keyboard shortcut.
            triggered: Optional callable to connect to the ``triggered`` signal.
            tooltip: Optional tooltip text.
            checkable: Whether the action should be checkable.

        Returns:
            The newly created :class:`QAction`.
        """
        action = QAction(text, self.main_window, checkable=checkable)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        if triggered:
            action.triggered.connect(triggered)
        if tooltip:
            action.setToolTip(tooltip)
        self.actions[name] = action
        return action

    def _create_file_actions(self) -> None:
        """Create all File-menu actions."""
        self._create_action(
            "new", "&New System", QKeySequence.New, self.main_window.new_system_action
        )
        self._create_action(
            "open",
            "&Open System...",
            QKeySequence.Open,
            self.main_window.open_system_action,
        )
        self._create_action(
            "save",
            "&Save System",
            QKeySequence.Save,
            self.main_window.save_system_action,
        )
        self._create_action(
            "save_as",
            "Save System &As...",
            QKeySequence.SaveAs,
            self.main_window.save_system_as_action,
        )
        self._create_action(
            "import_zemax",
            "From &Zemax (.zmx)...",
            triggered=self.main_window.import_zemax_action,
        )
        self._create_action(
            "import_codev",
            "From &CODE V (.seq)...",
            triggered=self.main_window.import_codev_action,
        )
        self._create_action(
            "export_zemax",
            "To &Zemax (.zmx)...",
            triggered=self.main_window.export_zemax_action,
        )
        self._create_action(
            "export_codev",
            "To &CODE V (.seq)...",
            triggered=self.main_window.export_codev_action,
        )
        self._create_action("exit", "E&xit", "Ctrl+Q", self.main_window.close)

    def _create_edit_actions(self) -> None:
        """Create Undo and Redo actions and wire their enabled
        state to the connector."""
        undo = self._create_action(
            "undo", "&Undo", QKeySequence.Undo, self.connector.undo
        )
        redo = self._create_action(
            "redo", "&Redo", QKeySequence.Redo, self.connector.redo
        )
        undo.setEnabled(False)
        redo.setEnabled(False)
        self.connector.undoStackAvailabilityChanged.connect(undo.setEnabled)
        self.connector.redoStackAvailabilityChanged.connect(redo.setEnabled)

    def _create_view_actions(self) -> None:
        """Create View-menu actions for docking and layout reset."""
        self._create_action(
            "dock_all",
            "Dock All Windows",
            triggered=self.main_window.reset_windows_action,
        )
        self._create_action(
            "reset_layout",
            "Reset Window Layout",
            triggered=self.main_window.reset_windows_action,
        )
        self._create_action(
            "toggle_fullscreen",
            "Toggle Full Screen",
            "F11",
            self.main_window.toggle_fullscreen_action,
        )

    def _create_layout_actions(self) -> None:
        """Create Layout-slot load and save actions."""
        settings = self.main_window.settings
        load_actions = []
        for slot in range(1, self.main_window.MAX_LAYOUT_SLOTS + 1):
            load_actions.append(
                self._create_action(
                    f"load_layout_{slot}",
                    str(slot),
                    shortcut=f"Alt+{slot}",
                    triggered=getattr(self.main_window, f"load_layout_{slot}_slot"),
                    tooltip=f"Load Layout from Slot {slot} (Alt+{slot})",
                )
            )
        self._create_action(
            "save_layout",
            "Save Current Layout",
            triggered=self.main_window.save_layout_slot,
            tooltip="Save current window layout to a chosen slot (1 to 4)",
        )
        for slot, action in enumerate(load_actions, start=1):
            action.setEnabled(settings.contains(f"Layouts/Config{slot}Geometry"))

    def _create_theme_actions(self) -> None:
        """Create mutually exclusive theme actions."""
        group = QActionGroup(self.main_window)
        group.setExclusive(True)
        for theme in THEMES:
            action = self._create_action(
                f"theme_{theme.theme_id}",
                theme.label,
                checkable=True,
                triggered=lambda checked=False, theme_id=theme.theme_id: self.main_window.switch_theme(
                    theme_id
                ),
            )
            group.addAction(action)
        self.actions["theme_group"] = group

    def get_theme_actions(self, mode: str | None = None) -> list[QAction]:
        """Return theme actions, optionally filtered by mode."""
        actions: list[QAction] = []
        for theme in THEMES:
            if mode is not None and theme.mode != mode:
                continue
            action = self.get_action(f"theme_{theme.theme_id}")
            if action:
                actions.append(action)
        return actions

    def _create_help_actions(self) -> None:
        """Create Help-menu actions."""
        self._create_action(
            "about", "&About Optiland GUI", triggered=self.main_window.about_action
        )

    def get_action(self, name: str) -> QAction | None:
        """Return the registered action for *name*, or ``None``.

        Args:
            name: The registry key used when the action was created.

        Returns:
            The :class:`QAction` if found, or ``None``.
        """
        return self.actions.get(name)

    def get_actions(self, *names: str) -> list[QAction | None]:
        """Return multiple actions by their registry keys.

        Args:
            *names: Registry keys to look up.

        Returns:
            A list of :class:`QAction` objects (``None`` for unknown keys).
        """
        return [self.actions.get(name) for name in names]
