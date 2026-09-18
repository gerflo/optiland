"""Opening a non-sequential scene file through File -> Open.

A user opened a folded NSQ scene with the optical-system loader and got
``Load failed: 'aperture'`` -- and lost the system that was open, because
the loader resets to a blank system on any failure. The loader now
recognises a scene file and refuses it without resetting, and the main
window routes such a file to the Non-Sequential panel.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

from optiland.samples.nonsequential import beam_splitter_scene
from optiland_gui.main_window import MainWindow
from optiland_gui.optiland_connector import OptilandConnector
from optiland_gui.services.file_service import (
    is_nsq_scene_file,
    with_scene_extension,
)
from optiland_gui.services.nsq_service import NSQService


def _patch_connector_side_services(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(
        "optiland_gui.optiland_connector.CatalogService",
        lambda connector: MagicMock(),
    )
    monkeypatch.setattr(
        "optiland_gui.optiland_connector.MaterialCatalogService",
        lambda connector: MagicMock(),
    )


def _scene_file(tmp_path) -> str:  # noqa: ANN001
    path = tmp_path / "folded.nsq.json"
    beam_splitter_scene().to_json(path)
    return str(path)


def test_is_nsq_scene_file(tmp_path) -> None:
    scene = _scene_file(tmp_path)
    assert is_nsq_scene_file(scene)
    olsys = tmp_path / "folded.olsys"
    beam_splitter_scene().to_json(olsys)
    assert is_nsq_scene_file(str(olsys))
    optic = tmp_path / "optic.json"
    optic.write_text(json.dumps({"version": 1.0, "aperture": {}}), encoding="utf-8")
    assert not is_nsq_scene_file(str(optic))
    assert not is_nsq_scene_file(str(tmp_path / "missing.json"))
    assert not is_nsq_scene_file(str(tmp_path / "design.zmx"))


def test_scene_extension_defaults_to_olsys() -> None:
    assert with_scene_extension("C:/x/folded") == "C:/x/folded.olsys"
    assert with_scene_extension("C:/x/folded.olsys") == "C:/x/folded.olsys"
    assert with_scene_extension("C:/x/legacy.json") == "C:/x/legacy.json"
    assert with_scene_extension("C:/x/a.b") == "C:/x/a.b.olsys"


def test_loader_refuses_a_scene_without_resetting(qapp, monkeypatch, tmp_path):
    _patch_connector_side_services(monkeypatch)
    connector = OptilandConnector()
    connector.toast_manager = MagicMock()
    connector.add_surface()
    optic_before = connector.get_optic()
    surfaces_before = connector.get_surface_count()

    connector.load_optic_from_file(_scene_file(tmp_path))

    assert connector.get_optic() is optic_before
    assert connector.get_surface_count() == surfaces_before
    message, severity = connector.toast_manager.notify.call_args.args[:2]
    assert severity == "error"
    assert "System view" in message
    assert "aperture" not in message


def test_main_window_routes_a_scene_to_the_nsq_panel(qapp, tmp_path) -> None:
    service = NSQService()
    window = SimpleNamespace(
        panel_manager=SimpleNamespace(
            nsq_panel=SimpleNamespace(service=service), nsq_dock=object()
        ),
        connector=MagicMock(),
        toast_manager=MagicMock(),
        focus_dock_widget=MagicMock(),
        _remember_dialog_path=MagicMock(),
        _remember_recent_file=MagicMock(),
        _maybe_save_changes_before_destructive_action=MagicMock(return_value=True),
        _update_project_name_in_title_bar=MagicMock(),
    )
    window._open_nsq_scene_from_path = lambda p: MainWindow._open_nsq_scene_from_path(
        window, p
    )
    path = _scene_file(tmp_path)

    MainWindow._open_system_from_path(window, path)

    assert service.scene is not None
    assert service.scene_path == path
    assert set(service.scene.detector_names) == {"transmitted", "reflected"}
    window.connector.load_optic_from_file.assert_not_called()
    # The system is the document: replacing it asks about unsaved changes.
    window._maybe_save_changes_before_destructive_action.assert_called_once()
    window.focus_dock_widget.assert_called_once_with(window.panel_manager.nsq_dock)
    window._remember_recent_file.assert_called_once_with(path)
    message, severity = window.toast_manager.notify.call_args.args[:2]
    assert severity == "info" and "multi-axis system" in message


def test_main_window_still_loads_optical_systems(tmp_path) -> None:
    optic = tmp_path / "optic.json"
    optic.write_text(json.dumps({"version": 1.0}), encoding="utf-8")
    window = SimpleNamespace(
        panel_manager=MagicMock(),
        connector=MagicMock(),
        toast_manager=MagicMock(),
        focus_dock_widget=MagicMock(),
        _remember_dialog_path=MagicMock(),
        _remember_recent_file=MagicMock(),
        _maybe_save_changes_before_destructive_action=MagicMock(return_value=True),
        _update_project_name_in_title_bar=MagicMock(),
    )
    MainWindow._open_system_from_path(window, str(optic))
    window.connector.load_optic_from_file.assert_called_once_with(str(optic))
    window.focus_dock_widget.assert_not_called()
