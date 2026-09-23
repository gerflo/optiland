"""The multi-axis system is the GUI document.

A sequential design opened from a ``.json`` becomes path 1 of a new
system, or fills a path of a folded system (the first by default);
File -> Save writes every path and the scene to ``.olsys`` with the file
format and application versions; File -> Export -> Optiland JSON writes one
chosen path as a plain sequential design file.
"""

from __future__ import annotations

import json
from types import MethodType, SimpleNamespace
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QDialog

import optiland.backend as be
from optiland.nonsequential.system import OLSYS_FORMAT_VERSION, fold_system
from optiland.optic import Optic
from optiland.samples.objectives import CookeTriplet
from optiland_gui import __version__
from optiland_gui.main_window import MainWindow
from optiland_gui.nsq_panel import NSQPanel
from optiland_gui.optiland_connector import OptilandConnector
from optiland_gui.services.file_service import SpecialFloatEncoder, is_nsq_scene_file
from optiland_gui.services.nsq_service import NSQService, default_path_name
from optiland_gui.widgets.path_choice_dialog import PathChoiceDialog
from tests.nonsequential.test_nsq_fold_paths import (
    _FOLD_ILLUMINATION,
    _FOLD_IMAGING,
    illumination_optic,
    imaging_optic,
)

#: Main-window methods exercised on the stand-in window.
_BOUND = (
    "_open_system_from_path",
    "_open_nsq_scene_from_path",
    "_open_optic_into_path",
    "_document_has_unsaved_changes",
    "_update_project_name_in_title_bar",
    "save_system_action",
    "_save_document",
    "_export_path_json",
)


@pytest.fixture(autouse=True)
def _numpy_backend():
    be.set_backend("numpy")
    yield
    be.set_backend("numpy")


def _patch_connector_side_services(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(
        "optiland_gui.optiland_connector.CatalogService",
        lambda connector: MagicMock(),
    )
    monkeypatch.setattr(
        "optiland_gui.optiland_connector.MaterialCatalogService",
        lambda connector: MagicMock(),
    )


def _window(monkeypatch, choose=None):  # noqa: ANN001
    """A stand-in main window with a real connector and System view panel.

    ``choose`` replaces the path-choice dialog: ``(name, new_system)`` as
    :meth:`PathChoiceDialog.choose` returns it; the default fills the
    first path.
    """
    _patch_connector_side_services(monkeypatch)
    connector = OptilandConnector()
    connector.toast_manager = MagicMock()
    panel = NSQPanel(connector)
    window = SimpleNamespace(
        connector=connector,
        panel_manager=SimpleNamespace(
            nsq_panel=panel, show_system_panel=MagicMock()
        ),
        toast_manager=connector.toast_manager,
        focus_dock_widget=MagicMock(),
        _remember_dialog_path=MagicMock(),
        _remember_recent_file=MagicMock(),
        _handle_design_validation=lambda data, path: (data, False),
        _choose_open_target=choose or (lambda filepath, names: (names[0], False)),
        _maybe_save_changes_before_destructive_action=MagicMock(return_value=True),
        custom_title_bar_widget=None,
        isFullScreen=lambda: False,
        setWindowTitle=MagicMock(),
    )
    for name in _BOUND:
        setattr(window, name, MethodType(getattr(MainWindow, name), window))
    return window, connector, panel


def _title(window) -> str:  # noqa: ANN001
    window._update_project_name_in_title_bar()
    return window.setWindowTitle.call_args.args[0]


def _toasts(window) -> list[str]:  # noqa: ANN001
    return [c.args[0] for c in window.toast_manager.notify.call_args_list]


def _design_file(tmp_path, optic: Optic, name: str) -> str:  # noqa: ANN001
    path = tmp_path / name
    path.write_text(json.dumps(optic.to_dict(), cls=SpecialFloatEncoder), "utf-8")
    return str(path)


def _folded_file(tmp_path):  # noqa: ANN001
    imaging = imaging_optic()
    imaging.name = "Camera path"
    illumination = illumination_optic()
    illumination.name = "Ring illumination"
    system, _ = fold_system(imaging, illumination, _FOLD_IMAGING, _FOLD_ILLUMINATION)
    path = tmp_path / "folded.olsys"
    system.to_json(path)
    return str(path)


def _radius(data: dict, index: int) -> float:
    return data["surface_group"]["surfaces"][index]["geometry"]["radius"]


def test_default_path_name():
    assert default_path_name("Cooke Triplet", None) == "Cooke Triplet"
    assert default_path_name("New Untitled System", None) == "Path 1"
    assert default_path_name("Default System", None) == "Path 1"
    assert default_path_name("", None) == "Path 1"
    source = "C:/a/RCR-03 Beobachtung.json"
    assert default_path_name("x", source) == "RCR-03 Beobachtung"


class TestStartup:
    def test_the_connector_design_is_path_1_of_an_untitled_document(
        self, qapp, monkeypatch
    ):
        window, connector, panel = _window(monkeypatch)
        service = panel.service
        assert service.path_names == ["Path 1"]
        assert service.active_path == "Path 1"
        assert service.document_name == "Untitled.olsys"
        assert service.scene is not None and service.scene.component_names
        assert not service.is_dirty
        assert not window._document_has_unsaved_changes()
        assert _title(window) == "Optiland \u2014 Untitled.olsys"
        assert panel.path_combo.currentText() == "Path 1"

    def test_a_refresh_without_an_edit_does_not_dirty_the_document(
        self, qapp, monkeypatch
    ):
        window, connector, panel = _window(monkeypatch)
        changed = []
        panel.service.sceneChanged.connect(lambda: changed.append(True))
        # Panels re-emit opticChanged at start-up without editing anything.
        connector.opticChanged.emit()
        panel.flush_pending_rebuild()
        assert not panel.service.is_dirty
        assert changed == []
        assert not window._document_has_unsaved_changes()

    def test_an_edit_dirties_the_document_and_rebuilds(self, qapp, monkeypatch):
        window, connector, panel = _window(monkeypatch)
        connector.set_surface_data(1, connector.COL_RADIUS, "50.0")
        panel.flush_pending_rebuild()
        assert panel.service.is_dirty
        assert window._document_has_unsaved_changes()
        assert _title(window).endswith("Untitled.olsys*")
        assert _radius(panel.service.path("Path 1").optic, 1) == pytest.approx(50.0)


class TestOpenDesign:
    def test_a_design_file_becomes_path_1_of_a_new_document(
        self, qapp, monkeypatch, tmp_path
    ):
        window, connector, panel = _window(monkeypatch)
        design = _design_file(tmp_path, CookeTriplet(), "cooke.json")

        window._open_system_from_path(design)

        service = panel.service
        assert service.path_names == ["cooke"]
        assert service.active_path == "cooke"
        assert connector.get_surface_count() == 8  # object + 6 faces + image
        assert service.document_name == "cooke.olsys"
        assert service.scene_path is None
        assert {"S1", "S6", "S1.rim"} <= set(service.scene.component_names)
        assert service.scene.source_names == ["field_0", "field_1", "field_2"]
        assert service.scene.detector_names == ["image"]
        assert service.path("cooke").components[:2] == ["S1", "S2"]
        assert not window._document_has_unsaved_changes()
        assert _title(window) == "Optiland \u2014 cooke.olsys"
        window._remember_recent_file.assert_called_once_with(design)
        assert panel.path_combo.currentText() == "cooke"

    def test_new_system_starts_a_fresh_untitled_document(
        self, qapp, monkeypatch, tmp_path
    ):
        window, connector, panel = _window(monkeypatch)
        window._open_system_from_path(_design_file(tmp_path, CookeTriplet(), "c.json"))
        connector.new_system()
        assert panel.service.path_names == ["Path 1"]
        assert panel.service.document_name == "Untitled.olsys"
        assert connector.get_surface_count() == 3

    def test_a_sample_design_starts_a_document_named_after_it(self, qapp, monkeypatch):
        window, connector, panel = _window(monkeypatch)
        optic = CookeTriplet()
        optic.name = "Cooke Triplet"
        connector.load_optic_from_object(optic)
        assert panel.service.path_names == ["Cooke Triplet"]
        assert panel.service.active_path == "Cooke Triplet"

    def test_a_design_that_cannot_be_converted_still_opens(
        self, qapp, monkeypatch, tmp_path
    ):
        window, connector, panel = _window(monkeypatch)
        optic = CookeTriplet()
        optic.set_field_type(field_type="object_height")  # object at infinity
        window._open_system_from_path(_design_file(tmp_path, optic, "odd.json"))
        assert panel.service.path_names == ["odd"]
        assert connector.get_surface_count() == 8
        assert panel.service.scene.component_names == []
        assert any("not shown in the System view" in m for m in _toasts(window))


class TestOpenRebuildsTheScene:
    """O3: a ``.olsys`` keeps the scene of its last successful rebuild, so a
    file saved after a failed rebuild (or written by an older converter)
    showed a scene that does not belong to its design. Opening builds the
    scene again from the paths; when that fails the stored scene is shown
    with a warning."""

    @staticmethod
    def _stale_file(tmp_path, replacement: Optic, name: str) -> str:  # noqa: ANN001
        """A system whose stored scene is the Cooke triplet's while its path
        holds *replacement* -- the state after a rebuild that failed."""
        from optiland.nonsequential.system import MultiAxisSystem

        system = MultiAxisSystem.from_optic(CookeTriplet(), "Design")
        system.set_path_optic("Design", replacement)  # no rebuild: now stale
        path = tmp_path / name
        system.to_json(path)
        return str(path)

    @staticmethod
    def _unconvertible() -> Optic:
        optic = CookeTriplet()
        optic.set_field_type(field_type="object_height")  # object at infinity
        return optic

    def test_open_builds_the_scene_from_the_paths(self, qapp, tmp_path):
        from optiland.nonsequential.system import MultiAxisSystem

        service = NSQService()
        expected = MultiAxisSystem.from_optic(imaging_optic(), "Design")

        service.load_file(self._stale_file(tmp_path, imaging_optic(), "stale.olsys"))

        assert service.scene.component_names == expected.scene.component_names
        assert service.scene_outdated is None
        assert not service.is_dirty

    def test_a_path_that_cannot_be_converted_keeps_the_stored_scene(
        self, qapp, tmp_path
    ):
        service = NSQService()
        reported: list[str] = []
        service.sceneOutdated.connect(reported.append)

        service.load_file(self._stale_file(tmp_path, self._unconvertible(), "b.olsys"))

        assert {"S1", "S6", "S1.rim"} <= set(service.scene.component_names)
        assert service.scene_outdated is not None
        assert reported == [service.scene_outdated]

    def test_the_panel_warns_and_marks_the_stored_scene(
        self, qapp, monkeypatch, tmp_path
    ):
        window, _connector, panel = _window(monkeypatch)

        window._open_nsq_scene_from_path(
            self._stale_file(tmp_path, self._unconvertible(), "c.olsys")
        )

        assert any("could not be rebuilt" in message for message in _toasts(window))
        assert "stored scene" in panel._layout_title()


class TestOpenIntoFoldedSystem:
    def _folded_window(self, monkeypatch, tmp_path, choose=None):  # noqa: ANN001
        window, connector, panel = _window(monkeypatch, choose)
        window._open_nsq_scene_from_path(_folded_file(tmp_path))
        return window, connector, panel

    def test_opening_a_system_activates_its_first_path(
        self, qapp, monkeypatch, tmp_path
    ):
        window, connector, panel = self._folded_window(monkeypatch, tmp_path)
        service = panel.service
        assert service.path_names == ["Camera path", "Ring illumination"]
        assert service.active_path == "Camera path"
        assert connector.get_surface_count() == 7
        assert service.document_name == "folded.olsys"
        assert not window._document_has_unsaved_changes()
        assert _title(window) == "Optiland \u2014 folded.olsys"
        window.panel_manager.show_system_panel.assert_called_once_with()
        window._maybe_save_changes_before_destructive_action.assert_called_once()

    def test_a_design_fills_the_first_path_by_default(
        self, qapp, monkeypatch, tmp_path
    ):
        window, connector, panel = self._folded_window(monkeypatch, tmp_path)
        service = panel.service
        edited = imaging_optic()
        r_old = float(be.to_numpy(edited.surfaces.surfaces[4].geometry.radius))
        edited.surfaces.surfaces[4].geometry.radius = 2.0 * r_old
        design = _design_file(tmp_path, edited, "camera-v2.json")
        service.activate_path("Ring illumination", connector)

        window._open_system_from_path(design)

        assert service.path_names == ["Camera path", "Ring illumination"]
        assert service.system.fold is not None
        assert _radius(service.path("Camera path").optic, 4) == pytest.approx(2 * r_old)
        assert service.active_path == "Camera path"
        assert connector.get_surface_count() == 7
        assert service.is_dirty and window._document_has_unsaved_changes()
        assert _title(window) == "Optiland \u2014 folded.olsys*"
        assert any("into path 'Camera path'" in m for m in _toasts(window))
        window._remember_recent_file.assert_called_with(design)

    def test_the_dialog_can_pick_another_path(self, qapp, monkeypatch, tmp_path):
        asked = []

        def choose(filepath, names):
            asked.append((filepath, list(names)))
            return "Ring illumination", False

        window, connector, panel = self._folded_window(monkeypatch, tmp_path, choose)
        service = panel.service
        edited = illumination_optic()
        edited.surfaces.surfaces[2].geometry.radius = 33.0
        design = _design_file(tmp_path, edited, "ring-v2.json")

        window._open_system_from_path(design)

        assert asked == [(design, ["Camera path", "Ring illumination"])]
        assert _radius(service.path("Ring illumination").optic, 2) == 33.0
        assert service.active_path == "Ring illumination"
        assert connector.get_surface_count() == 8

    def test_new_system_replaces_the_folded_document(self, qapp, monkeypatch, tmp_path):
        window, connector, panel = self._folded_window(
            monkeypatch, tmp_path, lambda filepath, names: (None, True)
        )
        window._open_system_from_path(_design_file(tmp_path, CookeTriplet(), "c.json"))
        assert panel.service.path_names == ["c"]
        assert panel.service.system.fold is None
        assert connector.get_surface_count() == 8

    def test_cancelling_the_dialog_changes_nothing(self, qapp, monkeypatch, tmp_path):
        window, connector, panel = self._folded_window(
            monkeypatch, tmp_path, lambda filepath, names: (None, False)
        )
        window._open_system_from_path(_design_file(tmp_path, CookeTriplet(), "c.json"))
        assert panel.service.path_names == ["Camera path", "Ring illumination"]
        assert connector.get_surface_count() == 7
        assert not window._document_has_unsaved_changes()

    def test_a_design_that_breaks_the_fold_is_refused(
        self, qapp, monkeypatch, tmp_path
    ):
        window, connector, panel = self._folded_window(monkeypatch, tmp_path)
        service = panel.service
        before = service.path("Camera path").optic
        window._open_system_from_path(_design_file(tmp_path, CookeTriplet(), "c.json"))
        assert service.path("Camera path").optic is before
        assert service.active_path == "Camera path"
        assert not service.is_dirty
        assert any(m.startswith("Load failed") for m in _toasts(window))

    def test_a_system_file_replaces_the_document_without_a_dialog(
        self, qapp, monkeypatch, tmp_path
    ):
        asked = []
        window, connector, panel = self._folded_window(
            monkeypatch, tmp_path, lambda f, n: asked.append(f) or (n[0], False)
        )
        window._open_system_from_path(_folded_file(tmp_path))
        assert asked == []
        assert panel.service.path_names == ["Camera path", "Ring illumination"]


class TestSave:
    def test_save_writes_every_path_with_the_versions(
        self, qapp, monkeypatch, tmp_path
    ):
        window, connector, panel = _window(monkeypatch)
        window._open_nsq_scene_from_path(_folded_file(tmp_path))
        service = panel.service
        connector.set_surface_data(4, connector.COL_RADIUS, "45.0")
        panel.flush_pending_rebuild()
        service.rename_path("Ring illumination", "LED ring")
        assert window._document_has_unsaved_changes()
        out = tmp_path / "saved.olsys"

        assert window._save_document(str(out))

        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["olsys_format_version"] == OLSYS_FORMAT_VERSION
        assert data["application"] == {"name": "Optiland GUI", "version": __version__}
        assert data["optiland_version"]
        assert [p["name"] for p in data["paths"]] == ["Camera path", "LED ring"]
        assert _radius(data["paths"][0]["optic"], 4) == pytest.approx(45.0)
        assert data["fold"]["illumination"] == "LED ring"
        assert not window._document_has_unsaved_changes()
        assert service.scene_path == str(out)
        assert _title(window) == "Optiland \u2014 saved.olsys"
        window._remember_recent_file.assert_called_with(str(out))
        assert any(m.startswith("Saved") for m in _toasts(window))

    def test_save_action_writes_to_the_document_file(self, qapp, monkeypatch, tmp_path):
        window, connector, panel = _window(monkeypatch)
        window._open_nsq_scene_from_path(_folded_file(tmp_path))
        out = tmp_path / "doc.olsys"
        window._save_document(str(out))
        connector.set_surface_data(4, connector.COL_RADIUS, "40.0")
        # The debounced rebuild is still pending: saving must not wait for it.
        assert window._document_has_unsaved_changes()

        window.save_system_action()

        data = json.loads(out.read_text(encoding="utf-8"))
        assert _radius(data["paths"][0]["optic"], 4) == pytest.approx(40.0)
        assert not window._document_has_unsaved_changes()

    def test_an_undone_edit_is_saved_as_undone(self, qapp, monkeypatch, tmp_path):
        """Undo restores the design with opticLoaded only; the path must follow."""
        window, connector, panel = _window(monkeypatch)
        window._open_nsq_scene_from_path(_folded_file(tmp_path))
        original = _radius(panel.service.path("Camera path").optic, 4)
        connector.set_surface_data(4, connector.COL_RADIUS, "45.0")
        panel.flush_pending_rebuild()
        assert _radius(panel.service.path("Camera path").optic, 4) == 45.0

        connector.undo()
        out = tmp_path / "undone.olsys"
        window._save_document(str(out))

        data = json.loads(out.read_text(encoding="utf-8"))
        assert _radius(data["paths"][0]["optic"], 4) == pytest.approx(original)
        assert _radius(panel.service.path("Camera path").optic, 4) == original

    def test_a_new_document_is_saved_under_its_design_name(
        self, qapp, monkeypatch, tmp_path
    ):
        window, connector, panel = _window(monkeypatch)
        window._open_system_from_path(_design_file(tmp_path, CookeTriplet(), "c.json"))
        assert panel.service.document_name == "c.olsys"
        out = tmp_path / "c.olsys"
        window._save_document(str(out))
        data = json.loads(out.read_text(encoding="utf-8"))
        assert [p["name"] for p in data["paths"]] == ["c"]
        assert data["fold"] is None
        assert is_nsq_scene_file(str(out))


class TestExport:
    def test_export_writes_the_chosen_path_as_a_design_file(
        self, qapp, monkeypatch, tmp_path
    ):
        window, connector, panel = _window(monkeypatch)
        window._open_nsq_scene_from_path(_folded_file(tmp_path))
        out = tmp_path / "ring.json"

        assert window._export_path_json("Ring illumination", str(out))

        data = json.loads(out.read_text(encoding="utf-8"))
        assert not is_nsq_scene_file(str(out))
        assert len(Optic.from_dict(data).surfaces.surfaces) == 8
        assert any("path 'Ring illumination'" in m for m in _toasts(window))

    def test_the_active_path_is_exported_with_its_pending_edit(
        self, qapp, monkeypatch, tmp_path
    ):
        window, connector, panel = _window(monkeypatch)
        window._open_nsq_scene_from_path(_folded_file(tmp_path))
        connector.set_surface_data(4, connector.COL_RADIUS, "42.0")
        out = tmp_path / "camera.json"
        window._export_path_json("Camera path", str(out))
        data = json.loads(out.read_text(encoding="utf-8"))
        assert _radius(data, 4) == pytest.approx(42.0)
        assert "gui" in data  # the same content File -> Save wrote before
        connector.load_optic_from_file(str(out))
        assert connector.get_surface_count() == 7

    def test_the_dialog_preselects_and_offers_an_extra_choice(self, qapp):
        names = ["Camera path", "Ring illumination"]
        dialog = PathChoiceDialog(names, "Ring illumination")
        assert dialog.selected_name == "Ring illumination"
        assert dialog.extra_button is None
        dialog = PathChoiceDialog(names, "no such path", extra_text="New system")
        assert dialog.selected_name == "Camera path"
        dialog.extra_button.click()
        assert dialog.extra_chosen and dialog.result() == QDialog.DialogCode.Accepted
        with pytest.raises(ValueError):
            PathChoiceDialog([])
        QCoreApplication.processEvents()
