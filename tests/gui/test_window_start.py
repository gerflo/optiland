"""Start-up of the main window: one menu bar, fullscreen, a file from the command line.

Three reports of 2026-09-28 (Optiland bugs O19 to O21):

* O19 -- Explorer's "Open with" started the GUI, but the file stayed closed:
  the entry point never looked at the command line.
* O20 -- the GUI starts in fullscreen by default (the frameless chrome with
  the menu in the title bar). Leaving fullscreen gives the maximized or
  normal window the last session had.
* O21 -- outside fullscreen the main menu showed twice. ``restoreState``
  brought the title-bar toolbar (with its own menu bar) back from a dock
  layout saved in fullscreen and put it under the native menu bar. In
  fullscreen, a layout saved windowed took the only menu bar away.

The tests drive the real ``MainWindow``. The catalog services are stubbed so
that no catalog import runs, and every module writes its settings to an ini
file in the test's temporary folder.
"""

from __future__ import annotations

import contextlib
import logging
import os
import sys
import uuid
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QDeadlineTimer, QEventLoop, QSettings, QTimer
from PySide6.QtWidgets import QDialog, QMessageBox

import optiland_gui.run_gui as run_gui
from optiland_gui.main_window import MainWindow
from optiland_gui.optiland_connector import OptilandConnector
from optiland_gui.utils.logging_handler import _bridge

SETTINGS_MODULES = (
    "optiland_gui.catalog_browser_panel",
    "optiland_gui.lens_editor",
    "optiland_gui.main_window",
    "optiland_gui.material_browser_panel",
    "optiland_gui.viewer_panel",
)


def _settle(qapp, ms: int = 150) -> None:
    deadline = QDeadlineTimer(ms)
    while not deadline.hasExpired():
        qapp.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 20)


@pytest.fixture()
def settings(monkeypatch, tmp_path) -> QSettings:
    """Settings of every GUI module go to one ini file of this test."""
    ini_path = str(tmp_path / f"optiland-{uuid.uuid4().hex[:8]}.ini")

    def _ini_settings(*_args, **_kwargs) -> QSettings:
        return QSettings(ini_path, QSettings.Format.IniFormat)

    for module in SETTINGS_MODULES:
        monkeypatch.setattr(f"{module}.QSettings", _ini_settings)
    # No catalog import at start-up.
    monkeypatch.setattr(
        "optiland_gui.optiland_connector.CatalogService",
        lambda connector: MagicMock(),
    )
    monkeypatch.setattr(
        "optiland_gui.optiland_connector.MaterialCatalogService",
        lambda connector: MagicMock(),
    )
    return _ini_settings()


@pytest.fixture()
def make_window(qapp, settings):
    """Factory for real main windows; closes them without saving anything.

    Nobody is at the keyboard: a modal dialog (a save prompt, a design
    correction) is rejected and fails the test instead of waiting for a
    click.
    """
    windows: list[MainWindow] = []
    dialogs: list[str] = []

    def _dismiss_modal() -> None:
        modal = qapp.activeModalWidget()
        if modal is None:
            return
        text = modal.text() if isinstance(modal, QMessageBox) else ""
        dialogs.append(f"{modal.windowTitle()!r}: {text}")
        if isinstance(modal, QDialog):
            modal.reject()
        else:
            modal.close()

    watchdog = QTimer()
    watchdog.setInterval(100)
    watchdog.timeout.connect(_dismiss_modal)
    watchdog.start()

    def _make() -> MainWindow:
        window = MainWindow()
        windows.append(window)
        return window

    yield _make

    watchdog.stop()
    for window in windows:
        window.connector.mark_current_state_clean()
        window.panel_manager.nsq_panel.service.mark_clean()
        window._save_window_placement = lambda: None
        window._save_current_layout_state = lambda: None
        window.close()
        handler = window._gui_log_handler
        logging.getLogger().removeHandler(handler)
        with contextlib.suppress(RuntimeError, TypeError):
            _bridge.record_received.disconnect(handler._on_record)
        window.deleteLater()
    _settle(qapp)
    assert dialogs == [], f"a modal dialog waited for a click: {dialogs}"


@pytest.fixture()
def window(make_window) -> MainWindow:
    return make_window()


def _assert_one_menu_bar(window: MainWindow) -> None:
    """Exactly the menu bar of the current chrome is visible."""
    fullscreen = window.isFullScreen()
    assert window.title_bar_as_toolbar.isHidden() is (not fullscreen)
    assert window._native_menu_bar_instance.isHidden() is fullscreen


class TestOneMenuBar:
    """O21: the title-bar toolbar follows the chrome, not the saved layout."""

    def test_layout_saved_in_fullscreen_restores_windowed_with_one_menu(
        self, qapp, window
    ) -> None:
        window.show()
        _settle(qapp)
        window._toggle_fullscreen()
        _settle(qapp)
        fullscreen_state = window.saveState()
        window._exit_fullscreen_to_previous_state()
        _settle(qapp)

        window.settings.setValue("Layouts/CurrentState", fullscreen_state)
        window._restore_current_layout_state()
        _settle(qapp)

        assert not window.isFullScreen()
        _assert_one_menu_bar(window)

    def test_layout_slot_saved_in_fullscreen_loads_windowed_with_one_menu(
        self, qapp, window
    ) -> None:
        window.show()
        _settle(qapp)
        window._toggle_fullscreen()
        _settle(qapp)
        fullscreen_state = window.saveState()
        window._exit_fullscreen_to_previous_state()
        _settle(qapp)

        window.settings.setValue("Layouts/Config1Geometry", window.saveGeometry())
        window.settings.setValue("Layouts/Config1State", fullscreen_state)
        window._load_layout_from_slot(1)
        _settle(qapp)

        assert not window.isFullScreen()
        _assert_one_menu_bar(window)

    def test_layout_saved_windowed_keeps_the_title_bar_menu_in_fullscreen(
        self, qapp, window
    ) -> None:
        window.show()
        _settle(qapp)
        windowed_state = window.saveState()
        window._toggle_fullscreen()
        _settle(qapp)

        window.settings.setValue("Layouts/CurrentState", windowed_state)
        window._restore_current_layout_state()
        _settle(qapp)

        assert window.isFullScreen()
        _assert_one_menu_bar(window)

    def test_title_bar_toolbar_is_not_offered_in_the_toolbar_menu(
        self, window
    ) -> None:
        menu = window.createPopupMenu()
        offered = [action.text() for action in menu.actions() if action.isVisible()]
        assert "CustomTitleBarToolbar" not in offered
        assert "QuickActionsToolbar" in offered


class TestStartFullscreen:
    """O20: fullscreen at start, windowed state of the last session behind it."""

    def test_starts_in_fullscreen_with_the_title_bar_menu(self, qapp, window) -> None:
        window.show_at_start()
        _settle(qapp, 300)

        assert window.isFullScreen()
        _assert_one_menu_bar(window)

    def test_leaving_fullscreen_gives_a_normal_window_by_default(
        self, qapp, window
    ) -> None:
        window.show_at_start()
        _settle(qapp, 300)
        window._exit_fullscreen_to_previous_state()
        _settle(qapp, 300)

        assert not window.isFullScreen()
        assert not window.isMaximized()
        _assert_one_menu_bar(window)

    def test_leaving_fullscreen_returns_to_the_maximized_window_of_the_last_session(
        self, qapp, settings, make_window
    ) -> None:
        settings.setValue("Window/WasMaximized", True)
        settings.sync()
        window = make_window()

        window.show_at_start()
        _settle(qapp, 300)
        assert window.isFullScreen()

        window._exit_fullscreen_to_previous_state()
        _settle(qapp, 300)
        assert not window.isFullScreen()
        assert window.isMaximized()
        _assert_one_menu_bar(window)

    def test_closing_in_fullscreen_remembers_the_maximized_state(
        self, qapp, settings, make_window
    ) -> None:
        settings.setValue("Window/WasMaximized", True)
        settings.sync()
        window = make_window()
        window.show_at_start()
        _settle(qapp, 300)

        window._save_window_placement()

        assert window.settings.value("Window/WasMaximized", False, type=bool) is True

    def test_starts_windowed_when_switched_off(
        self, qapp, settings, make_window
    ) -> None:
        settings.setValue("Window/StartFullScreen", False)
        settings.sync()
        window = make_window()

        window.show_at_start()
        _settle(qapp, 300)

        assert not window.isFullScreen()
        _assert_one_menu_bar(window)


class TestCommandLineFile:
    """O19: the file named on the command line is opened."""

    @pytest.mark.parametrize(
        ("argv", "expected"),
        [
            (["optiland"], None),
            (["optiland", "--verbose"], None),
            (["optiland", "designs/a.olsys"], os.path.abspath("designs/a.olsys")),
            (["optiland", "--verbose", "a.json"], os.path.abspath("a.json")),
        ],
    )
    def test_startup_file_from_argv(self, argv, expected) -> None:
        assert run_gui._startup_file(argv) == expected

    def test_startup_file_skips_the_value_of_an_option(self, tmp_path) -> None:
        design = tmp_path / "design.olsys"
        design.write_text("{}", encoding="utf-8")

        argv = ["optiland", "-style", "fusion", str(design)]

        assert run_gui._startup_file(argv) == str(design)

    def test_file_from_the_command_line_is_opened(self, qapp, window, tmp_path) -> None:
        design = tmp_path / "design.json"
        # A separate connector writes the file: saving from the window's own
        # connector commits the System Properties, and the debounced rebuild
        # then counts the document as changed and asks before opening.
        OptilandConnector().save_optic_to_file(str(design))
        window.show()
        _settle(qapp)

        window.open_file_from_command_line(str(design))
        _settle(qapp)

        assert window.panel_manager.nsq_panel.service.document_name == "design.olsys"
        recent = [os.path.normpath(path) for path in window._get_recent_files()]
        assert os.path.normpath(str(design)) in recent

    def test_missing_file_from_the_command_line_is_reported(
        self, qapp, window, tmp_path, caplog
    ) -> None:
        window.show()
        _settle(qapp)

        with caplog.at_level(logging.WARNING, logger="optiland_gui.main_window"):
            window.open_file_from_command_line(str(tmp_path / "gone.olsys"))
        _settle(qapp)

        assert window.panel_manager.nsq_panel.service.document_name == "Untitled.olsys"
        assert any("gone.olsys" in record.getMessage() for record in caplog.records)

    def test_main_starts_fullscreen_and_opens_the_file_from_the_command_line(
        self, qapp, monkeypatch, settings, make_window, tmp_path
    ) -> None:
        """End to end through the entry point (O19 and O20 wired up)."""
        design = tmp_path / "design.json"
        OptilandConnector().save_optic_to_file(str(design))
        created: list[MainWindow] = []

        def _window() -> MainWindow:
            window = make_window()
            created.append(window)
            return window

        class _App:
            def __init__(self, _argv) -> None:
                pass

            def setWindowIcon(self, _icon) -> None:  # noqa: N802
                pass

            def processEvents(self) -> None:  # noqa: N802
                qapp.processEvents()

            def exec(self) -> int:
                return 0

        monkeypatch.setattr(run_gui, "MainWindow", _window)
        monkeypatch.setattr(run_gui, "QApplication", _App)
        monkeypatch.setattr(run_gui, "QSplashScreen", lambda _pixmap: MagicMock())
        monkeypatch.setattr(run_gui._log_handler, "configure_logging", lambda: None)
        monkeypatch.setattr(run_gui._log_handler, "enable_crash_log", lambda: None)
        monkeypatch.setattr(sys, "argv", ["optiland", str(design)])

        with pytest.raises(SystemExit) as exit_info:
            run_gui.main()
        _settle(qapp, 300)

        assert exit_info.value.code == 0
        window = created[0]
        assert window.isFullScreen()
        _assert_one_menu_bar(window)
        assert window.panel_manager.nsq_panel.service.document_name == "design.olsys"
