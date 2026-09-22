from __future__ import annotations

import json
from unittest.mock import MagicMock

from PySide6.QtCore import QByteArray

from optiland_gui.main_window import CURRENT_TABS_KEY, MainWindow

#: What PanelManager.save_tab_state returns for one detached viewer tab.
_TAB_STATE = {
    "SystemViewerTabs": {"current": "system", "detached": {"layout3d": "AAEC"}}
}


class _SettingsStub:
    def __init__(self) -> None:
        self._values: dict[str, object] = {}

    def value(self, key: str, default=None, *, type=None):  # noqa: A002, ANN001
        value = self._values.get(key, default)
        if type is str:
            return "" if value is None else str(value)
        return value

    def setValue(self, key: str, value) -> None:  # noqa: ANN001
        self._values[key] = value

    def contains(self, key: str) -> bool:
        return key in self._values


def _make_window_stub():
    class _WindowStub:
        MAX_LAYOUT_SLOTS = 4

        def __init__(self) -> None:
            self.settings = _SettingsStub()
            self.toast_manager = MagicMock()
            self.next_save_slot_index = 1
            self._actions = {
                f"load_layout_{slot}": MagicMock() for slot in range(1, 5)
            }
            self.action_manager = MagicMock()
            self.action_manager.get_action.side_effect = self._actions.get
            self.panel_manager = MagicMock()
            self.panel_manager.save_tab_state.return_value = _TAB_STATE
            self.restored_states: list[object] = []

        def saveGeometry(self):  # noqa: ANN201
            return b"geometry"

        def saveState(self):  # noqa: ANN201
            return b"state"

        def restoreGeometry(self, _geometry) -> bool:  # noqa: ANN001
            return True

        def restoreState(self, state) -> bool:  # noqa: ANN001
            self.restored_states.append(state)
            return True

        def _normalize_all_docks(self) -> None:
            return None

    stub = _WindowStub()
    stub._layout_slot_display_name = MainWindow._layout_slot_display_name.__get__(
        stub, _WindowStub
    )
    stub._update_layout_slot_actions = MainWindow._update_layout_slot_actions.__get__(
        stub, _WindowStub
    )
    for name in ("_tab_state_json", "_restore_tab_state"):
        setattr(stub, name, getattr(MainWindow, name).__get__(stub, _WindowStub))
    return stub


def test_save_layout_to_slot_persists_name_and_updates_actions() -> None:
    window = _make_window_stub()

    MainWindow._save_layout_to_slot(window, 2, "Bench Setup Alpha Beta")

    assert window.settings.value("Layouts/Config2Geometry") == b"geometry"
    assert window.settings.value("Layouts/Config2State") == b"state"
    assert window.settings.value("Layouts/Config2Name", type=str) == "Bench Setup Alpha Be"
    assert window.settings.value("Layouts/NextSaveSlot") == 2
    assert window.next_save_slot_index == 2
    window.toast_manager.notify.assert_called_with(
        "Layout saved to 2: Bench Setup Alpha Be", "success"
    )

    load_action = window._actions["load_layout_2"]
    load_action.setEnabled.assert_called_with(True)
    load_action.setText.assert_called_with("2: Bench Setup Alpha Be")


def test_update_layout_slot_actions_uses_saved_names_and_fallback_slot_numbers() -> None:
    window = _make_window_stub()
    window.settings.setValue("Layouts/Config1Geometry", b"geometry")
    window.settings.setValue("Layouts/Config1Name", "Optik Lab")

    MainWindow._update_layout_slot_actions(window)

    slot_one = window._actions["load_layout_1"]
    slot_one.setEnabled.assert_called_with(True)
    slot_one.setText.assert_called_with("1: Optik Lab")
    slot_one.setToolTip.assert_called_with("Load Layout 1: Optik Lab (Alt+1)")

    slot_three = window._actions["load_layout_3"]
    slot_three.setEnabled.assert_called_with(False)
    slot_three.setText.assert_called_with("3")
    slot_three.setToolTip.assert_called_with("Load Layout 3 (Alt+3)")


# ---------------------------------------------------------------------------
# Detached viewer tabs are part of a layout
# ---------------------------------------------------------------------------


def test_a_saved_layout_stores_the_detached_tabs() -> None:
    window = _make_window_stub()

    MainWindow._save_layout_to_slot(window, 3, "Two screens")

    window.panel_manager.save_tab_state.assert_called_once_with(False)
    assert json.loads(window.settings.value("Layouts/Config3Tabs")) == _TAB_STATE


def test_loading_a_layout_restores_the_detached_tabs() -> None:
    window = _make_window_stub()
    window.settings.setValue("Layouts/Config2Geometry", QByteArray(b"geometry"))
    window.settings.setValue("Layouts/Config2State", QByteArray(b"state"))
    window.settings.setValue("Layouts/Config2Tabs", json.dumps(_TAB_STATE))

    MainWindow._load_layout_from_slot(window, 2)

    window.panel_manager.restore_tab_state.assert_called_once_with(_TAB_STATE)


def test_a_layout_saved_before_detachable_tabs_docks_every_tab() -> None:
    window = _make_window_stub()
    window.settings.setValue("Layouts/Config1Geometry", QByteArray(b"geometry"))
    window.settings.setValue("Layouts/Config1State", QByteArray(b"state"))

    MainWindow._load_layout_from_slot(window, 1)

    window.panel_manager.restore_tab_state.assert_called_once_with({})


def test_the_session_keeps_the_detached_tabs_and_their_positions() -> None:
    window = _make_window_stub()

    MainWindow._save_current_layout_state(window)

    # The session also remembers where the windows of docked tabs were.
    window.panel_manager.save_tab_state.assert_called_once_with(True)
    saved = window.settings.value(CURRENT_TABS_KEY)
    assert json.loads(saved) == _TAB_STATE

    window.settings.setValue("Layouts/CurrentState", QByteArray(b"state"))
    MainWindow._restore_current_layout_state(window)

    window.panel_manager.restore_tab_state.assert_called_once_with(_TAB_STATE)
    assert window.restored_states == [QByteArray(b"state")]


def test_unreadable_tab_data_docks_every_tab() -> None:
    window = _make_window_stub()
    window.settings.setValue(CURRENT_TABS_KEY, "{not json")

    MainWindow._restore_current_layout_state(window)

    window.panel_manager.restore_tab_state.assert_called_once_with({})


def test_closing_the_main_window_hides_the_detached_windows() -> None:
    window = MagicMock()
    window._maybe_save_changes_before_destructive_action.return_value = True
    event = MagicMock()

    MainWindow.closeEvent(window, event)

    window._save_current_layout_state.assert_called_once_with()
    window.panel_manager.hide_detached_windows.assert_called_once_with()
    event.accept.assert_called_once_with()
