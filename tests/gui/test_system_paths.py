"""Optical paths in the System view: activate, edit, rebuild, rename, click.

Activating a path hands its sequential design to the connector, so the
lens data editor and the sequential analyses work on it; an edit there
folds the system again; a click on a drawn element selects its path.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QCoreApplication

import optiland.backend as be
from optiland.nonsequential.fold import MIRROR
from optiland.nonsequential.system import fold_system
from optiland_gui.nsq_panel import NO_PATH, NSQPanel
from optiland_gui.optiland_connector import OptilandConnector
from optiland_gui.services.nsq_service import NSQService
from tests.nonsequential.test_nsq_fold_paths import (
    _FOLD_ILLUMINATION,
    _FOLD_IMAGING,
    illumination_optic,
    imaging_optic,
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


def _system_file(tmp_path):  # noqa: ANN001
    imaging = imaging_optic()
    imaging.name = "Camera path"
    illumination = illumination_optic()
    illumination.name = "Ring illumination"
    system, _ = fold_system(imaging, illumination, _FOLD_IMAGING, _FOLD_ILLUMINATION)
    path = tmp_path / "folded.olsys"
    system.to_json(path)
    return str(path)


def _loaded_panel(monkeypatch, tmp_path):  # noqa: ANN001
    _patch_connector_side_services(monkeypatch)
    connector = OptilandConnector()
    connector.toast_manager = MagicMock()
    service = NSQService()
    panel = NSQPanel(connector, service=service)
    service.load_file(_system_file(tmp_path))
    QCoreApplication.processEvents()
    return panel, connector, service


class TestService:
    def test_activate_loads_the_path_into_the_connector(
        self, qapp, monkeypatch, tmp_path
    ):
        panel, connector, service = _loaded_panel(monkeypatch, tmp_path)
        assert service.path_names == ["Camera path", "Ring illumination"]
        assert service.active_path is None
        before = connector.get_surface_count()
        activated = []
        service.activePathChanged.connect(activated.append)

        service.activate_path("Ring illumination", connector)

        assert service.active_path == "Ring illumination"
        assert activated == ["Ring illumination"]
        assert connector.get_surface_count() == 8  # the illumination design
        assert connector.get_surface_count() != before
        assert not service.is_activating

        service.activate_path("Camera path", connector)
        assert connector.get_surface_count() == 7
        service.activate_path(None, connector)
        assert service.active_path is None
        assert connector.get_surface_count() == 7  # deactivating leaves it alone

    def test_edit_in_the_sequential_tools_rebuilds_the_system(
        self, qapp, monkeypatch, tmp_path
    ):
        panel, connector, service = _loaded_panel(monkeypatch, tmp_path)
        service.activate_path("Camera path", connector)
        old_component = service.scene.component_registry.get("img.S4").component
        r_old = float(be.to_numpy(old_component.geometry.radius))
        changed = []
        service.sceneChanged.connect(lambda: changed.append(True))

        # Surface 4 of the imaging design is the first camera-lens face.
        connector.set_surface_data(4, connector.COL_RADIUS, str(2.0 * r_old))
        panel.flush_pending_rebuild()

        new_component = service.scene.component_registry.get("img.S4").component
        assert float(be.to_numpy(new_component.geometry.radius)) == pytest.approx(
            2.0 * r_old
        )
        assert changed == [True]
        assert service.result is None
        assert service.active_path == "Camera path"
        assert service.system.path("Camera path").optic["surface_group"]["surfaces"][4][
            "geometry"
        ]["radius"] == pytest.approx(2.0 * r_old)

    def test_a_failed_rebuild_keeps_the_previous_scene(
        self, qapp, monkeypatch, tmp_path
    ):
        panel, connector, service = _loaded_panel(monkeypatch, tmp_path)
        service.activate_path("Camera path", connector)
        names_before = service.scene.component_names
        # Removing the fold surface makes the imaging design unfoldable.
        connector.remove_surface(3)
        panel.flush_pending_rebuild()
        assert service.scene.component_names == names_before
        message, severity = connector.toast_manager.notify.call_args.args[:2]
        assert severity == "error" and "not rebuilt" in message
        # The edit itself is kept, so saving never loses it.
        surfaces = service.system.path("Camera path").optic["surface_group"]
        assert len(surfaces["surfaces"]) == 6
        assert service.is_dirty

    def test_rename_keeps_the_active_path(self, qapp, monkeypatch, tmp_path):
        panel, connector, service = _loaded_panel(monkeypatch, tmp_path)
        service.activate_path("Camera path", connector)
        service.rename_path("Camera path", "Beobachtung")
        assert service.active_path == "Beobachtung"
        assert service.path_names == ["Beobachtung", "Ring illumination"]
        assert [
            panel.path_combo.itemText(i) for i in range(panel.path_combo.count())
        ] == [
            NO_PATH,
            "Beobachtung",
            "Ring illumination",
        ]
        assert panel.path_combo.currentText() == "Beobachtung"

    def test_saving_keeps_the_names_and_edits(self, qapp, monkeypatch, tmp_path):
        panel, connector, service = _loaded_panel(monkeypatch, tmp_path)
        service.rename_path("Ring illumination", "LED-Ring")
        out = tmp_path / "renamed.olsys"
        service.save_file(str(out))
        other = NSQService()
        other.load_file(str(out))
        assert other.path_names == ["Camera path", "LED-Ring"]

    def test_sample_scenes_have_no_paths(self, qapp):
        service = NSQService()
        service.load_sample("beam_splitter")
        assert service.path_names == []
        assert service.paths_for_component("splitter") == []
        with pytest.raises(RuntimeError):
            service.sync_active_path(MagicMock())


class TestPanel:
    def test_combo_lists_paths_and_activates(self, qapp, monkeypatch, tmp_path):
        panel, connector, service = _loaded_panel(monkeypatch, tmp_path)
        combo = panel.path_combo
        assert [combo.itemText(i) for i in range(combo.count())] == [
            NO_PATH,
            "Camera path",
            "Ring illumination",
        ]
        assert combo.isEnabled() and panel.rename_path_button.isEnabled()
        panel._on_path_selected(2)
        assert service.active_path == "Ring illumination"
        assert combo.currentText() == "Ring illumination"
        assert "Ring illumination" in panel.layout_figure.axes[0].get_title()
        panel._on_path_selected(0)
        assert service.active_path is None

    def test_layout_click_activates_and_cycles_shared_elements(
        self, qapp, monkeypatch, tmp_path
    ):
        panel, connector, service = _loaded_panel(monkeypatch, tmp_path)

        def click(label):
            artist = SimpleNamespace(get_label=lambda: label)
            mouse = SimpleNamespace(button=1, dblclick=False)
            panel._on_layout_pick(SimpleNamespace(artist=artist, mouseevent=mouse))

        click("ill.S2")
        assert service.active_path == "Ring illumination"
        click("img.S4")
        assert service.active_path == "Camera path"
        click(MIRROR)  # shared: cycles to the other path
        assert service.active_path == "Ring illumination"
        click(MIRROR)
        assert service.active_path == "Camera path"
        click("no-such-element")
        assert service.active_path == "Camera path"

    def test_drawn_elements_are_pickable_and_the_active_path_is_highlighted(
        self, qapp, monkeypatch, tmp_path
    ):
        panel, connector, service = _loaded_panel(monkeypatch, tmp_path)
        ax = panel.layout_figure.axes[0]
        labelled = [a for a in ax.lines if not a.get_label().startswith("_")]
        assert labelled and all(a.pickable() for a in labelled)
        service.activate_path("Ring illumination", connector)
        ax = panel.layout_figure.axes[0]
        widths = {a.get_label(): a.get_linewidth() for a in ax.lines}
        assert widths["ill.S2"] == pytest.approx(3.0)
        assert widths["img.S4"] < 3.0
        alphas = {a.get_label(): a.get_alpha() for a in ax.lines}
        assert alphas["img.S4"] == pytest.approx(0.35)
        assert alphas["ill.S2"] is None

    def test_zoom_survives_a_rebuild_but_not_a_new_system(
        self, qapp, monkeypatch, tmp_path
    ):
        panel, connector, service = _loaded_panel(monkeypatch, tmp_path)
        ax = panel.layout_figure.axes[0]
        ax.set_xlim(10.0, 20.0)
        ax.set_ylim(-3.0, 3.0)
        panel.navigation.remember_view(ax)
        service.activate_path("Camera path", connector)
        connector.set_surface_data(4, connector.COL_RADIUS, "45.0")
        panel.flush_pending_rebuild()
        ax = panel.layout_figure.axes[0]
        assert ax.get_xlim() == pytest.approx((10.0, 20.0))
        service.load_sample("beam_splitter")
        ax = panel.layout_figure.axes[0]
        assert ax.get_xlim() != pytest.approx((10.0, 20.0))
        assert panel.path_combo.count() == 1 and not panel.path_combo.isEnabled()
