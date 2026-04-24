from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from PySide6.QtWidgets import QMessageBox

from optiland_gui.main_window import MainWindow
from optiland_gui.optiland_connector import OptilandConnector


def _patch_connector_side_services(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(
        "optiland_gui.optiland_connector.CatalogService",
        lambda connector: MagicMock(),
    )
    monkeypatch.setattr(
        "optiland_gui.optiland_connector.MaterialCatalogService",
        lambda connector: MagicMock(),
    )


def test_connector_returns_to_clean_state_after_reverting_new_system_change(monkeypatch) -> None:
    _patch_connector_side_services(monkeypatch)
    connector = OptilandConnector()

    assert connector.has_unsaved_changes() is False

    connector.add_surface()
    assert connector.has_unsaved_changes() is True

    connector.remove_surface(2)
    assert connector.has_unsaved_changes() is False
    assert connector.is_modified() is False


def test_connector_imported_state_requires_save_even_without_further_edits(
    minimal_optic,
    monkeypatch,
) -> None:
    _patch_connector_side_services(monkeypatch)
    connector = OptilandConnector()

    connector.load_optic_from_object(minimal_optic)

    assert connector.has_unsaved_changes() is True
    assert connector.is_modified() is True


def test_main_window_save_prompt_uses_save_discard_cancel(monkeypatch) -> None:
    window = SimpleNamespace()
    window.connector = MagicMock()
    window.connector.has_unsaved_changes.side_effect = [True, False]
    window.connector.get_current_filepath.return_value = r"C:\temp\demo.json"
    window.save_system_action = MagicMock()

    monkeypatch.setattr(
        "optiland_gui.main_window.QMessageBox.warning",
        lambda *args, **kwargs: QMessageBox.StandardButton.Save,
    )

    allowed = MainWindow._maybe_save_changes_before_destructive_action(
        window, "opening 'demo.json'"
    )

    assert allowed is True
    window.save_system_action.assert_called_once()


def test_main_window_save_prompt_cancels_when_save_did_not_clear_unsaved_changes(
    monkeypatch,
) -> None:
    window = SimpleNamespace()
    window.connector = MagicMock()
    window.connector.has_unsaved_changes.side_effect = [True, True]
    window.connector.get_current_filepath.return_value = None
    window.save_system_action = MagicMock()

    monkeypatch.setattr(
        "optiland_gui.main_window.QMessageBox.warning",
        lambda *args, **kwargs: QMessageBox.StandardButton.Save,
    )

    allowed = MainWindow._maybe_save_changes_before_destructive_action(
        window, "closing the application"
    )

    assert allowed is False
    window.save_system_action.assert_called_once()


def test_main_window_discard_prompt_allows_replacing_current_system(monkeypatch) -> None:
    window = SimpleNamespace()
    window.connector = MagicMock()
    window.connector.has_unsaved_changes.return_value = True
    window.connector.get_current_filepath.return_value = None
    window.save_system_action = MagicMock()

    monkeypatch.setattr(
        "optiland_gui.main_window.QMessageBox.warning",
        lambda *args, **kwargs: QMessageBox.StandardButton.Discard,
    )

    allowed = MainWindow._maybe_save_changes_before_destructive_action(
        window, "creating a new system"
    )

    assert allowed is True
    window.save_system_action.assert_not_called()
