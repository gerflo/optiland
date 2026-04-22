from __future__ import annotations

from unittest.mock import MagicMock

from optiland_gui.main_window import MainWindow


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

        def saveGeometry(self):  # noqa: ANN201
            return b"geometry"

        def saveState(self):  # noqa: ANN201
            return b"state"

    stub = _WindowStub()
    stub._layout_slot_display_name = MainWindow._layout_slot_display_name.__get__(
        stub, _WindowStub
    )
    stub._update_layout_slot_actions = MainWindow._update_layout_slot_actions.__get__(
        stub, _WindowStub
    )
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
