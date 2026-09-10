"""Regression tests: disabled-surface state and system metadata persistence.

Found via a real user file pair: a design saved "without pinhole mirror"
was byte-identical to the original except for its name, because
(1) disabled-surface state was session-only and never saved,
(2) it leaked into subsequently loaded files instead of being reset, and
(3) a description typed in System Properties was lost unless the user
    explicitly clicked "Apply Metadata" before saving.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

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


def test_disabled_surfaces_survive_save_and_load(qapp, monkeypatch, tmp_path) -> None:
    _patch_connector_side_services(monkeypatch)
    connector = OptilandConnector()
    connector.set_surface_disabled(1, True)

    filepath = str(tmp_path / "with_disabled.json")
    connector.save_optic_to_file(filepath)

    payload = json.loads((tmp_path / "with_disabled.json").read_text(encoding="utf-8"))
    assert payload["gui"]["disabled_surfaces"] == [1]

    fresh = OptilandConnector()
    assert fresh.get_disabled_surface_indices() == set()
    fresh.load_optic_from_file(filepath)
    assert fresh.get_disabled_surface_indices() == {1}


def test_loading_file_without_gui_state_clears_stale_disabled_state(
    qapp, monkeypatch, tmp_path
) -> None:
    """The user-visible bug: session state leaked into the next loaded file."""
    _patch_connector_side_services(monkeypatch)
    connector = OptilandConnector()

    # A plain file without any GUI state (as written by older versions).
    filepath = str(tmp_path / "plain.json")
    data = connector._capture_optic_state()
    data.pop("gui", None)
    (tmp_path / "plain.json").write_text(json.dumps(data), encoding="utf-8")

    connector.set_surface_disabled(1, True)
    connector.load_optic_from_file(filepath)

    assert connector.get_disabled_surface_indices() == set()


def test_new_system_clears_disabled_state(qapp, monkeypatch) -> None:
    _patch_connector_side_services(monkeypatch)
    connector = OptilandConnector()
    connector.set_surface_disabled(1, True)

    connector.new_system()

    assert connector.get_disabled_surface_indices() == set()


def test_disable_surface_marks_modified_and_is_undoable(qapp, monkeypatch) -> None:
    _patch_connector_side_services(monkeypatch)
    connector = OptilandConnector()
    assert connector.has_unsaved_changes() is False

    connector.set_surface_disabled(1, True)
    assert connector.has_unsaved_changes() is True
    assert connector.get_disabled_surface_indices() == {1}

    connector.undo()
    assert connector.get_disabled_surface_indices() == set()
    assert connector.has_unsaved_changes() is False


def test_element_disable_toggles_all_rows_in_one_undo_step(qapp, monkeypatch) -> None:
    _patch_connector_side_services(monkeypatch)
    connector = OptilandConnector()
    connector.add_surface()  # ensure at least rows 1 and 2 exist

    connector.set_surfaces_disabled([1, 2], True)
    assert connector.get_disabled_surface_indices() == {1, 2}

    connector.undo()
    assert connector.get_disabled_surface_indices() == set()


def test_pending_metadata_is_committed_on_save(qapp, monkeypatch, tmp_path) -> None:
    """Typing a description without clicking 'Apply Metadata' must still save."""
    from optiland_gui.system_properties_panel import MetadataEditor

    _patch_connector_side_services(monkeypatch)
    connector = OptilandConnector()
    editor = MetadataEditor(connector)

    editor.txtName.setText("Variante ohne Lochspiegelblende")
    editor.txtDescription.setPlainText("Lochspiegel deaktiviert.")
    # No btnApply click here — saving alone must commit the pending edits.

    filepath = str(tmp_path / "metadata.json")
    connector.save_optic_to_file(filepath)

    payload = json.loads((tmp_path / "metadata.json").read_text(encoding="utf-8"))
    assert payload["name"] == "Variante ohne Lochspiegelblende"
    assert payload["description"] == "Lochspiegel deaktiviert."


def test_set_metadata_is_noop_for_unchanged_values(qapp, monkeypatch) -> None:
    _patch_connector_side_services(monkeypatch)
    connector = OptilandConnector()
    connector.set_metadata("Name", "Beschreibung")
    connector.mark_current_state_clean()

    emissions: list[bool] = []
    connector.opticChanged.connect(lambda: emissions.append(True))
    connector.set_metadata("Name", "Beschreibung")

    assert emissions == []
    assert connector.has_unsaved_changes() is False
