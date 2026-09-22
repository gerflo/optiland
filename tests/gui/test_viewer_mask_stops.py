"""Mask stops show in red in the System Viewer's 2D and 3D layout.

They have their own switch, on by default, so they show even with the
aperture markers switched off (the 2D default).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from matplotlib.colors import same_color
from matplotlib.lines import Line2D
from PySide6.QtCore import QObject, Signal

import optiland.backend as be
from optiland.optic import Optic
from optiland.physical_apertures import DifferenceAperture, RadialAperture
from optiland.visualization.system.system import MASK_COLOR, STOP_COLOR
from optiland_gui.viewer_panel import ViewerPanel

MASK_ROW = 3


class _RecordingSettings:
    """QSettings stand-in backed by one dict shared by all instances."""

    store: dict[str, object] = {}

    def __init__(self, *_args, **_kwargs) -> None:
        pass

    def value(self, key: str, default=None, *, type=None):  # noqa: A002, ANN001
        value = self.store.get(key, default)
        if type is bool:
            return bool(value)
        if type is int:
            return int(value)
        return value

    def setValue(self, key: str, value) -> None:  # noqa: ANN001, N802
        self.store[key] = value


class _ConnectorStub(QObject):
    opticLoaded = Signal()
    opticChanged = Signal()

    def __init__(self, optic) -> None:  # noqa: ANN001
        super().__init__()
        self._optic = optic
        self.toast_manager = None

    def get_optic(self):  # noqa: ANN201
        return self._optic

    def get_effective_optic(self):  # noqa: ANN201
        return self._optic

    def get_surface_count(self) -> int:
        return self._optic.surfaces.num_surfaces

    def get_disabled_surface_indices(self) -> set[int]:
        return set()


@pytest.fixture()
def mask_optic() -> Optic:
    """A singlet with the stop in front and a circular mask stop behind it."""
    optic = Optic()
    optic.surfaces.add(index=0, radius=be.inf, thickness=be.inf)
    optic.surfaces.add(index=1, radius=50.0, thickness=5.0, material="N-BK7")
    optic.surfaces.add(index=2, radius=-50.0, thickness=20.0, is_stop=True)
    optic.surfaces.add(
        index=MASK_ROW,
        thickness=25.0,
        aperture=DifferenceAperture(RadialAperture(r_max=6.0), RadialAperture(2.0)),
    )
    optic.surfaces.add(index=4)
    optic.set_aperture(aperture_type="EPD", value=10.0)
    optic.fields.set_type("angle")
    optic.fields.add(y=0.0)
    optic.wavelengths.add(value=0.55, is_primary=True)
    optic.updater.update()
    return optic


@pytest.fixture()
def settings(monkeypatch) -> dict[str, object]:
    store: dict[str, object] = {}
    monkeypatch.setattr(_RecordingSettings, "store", store)
    monkeypatch.setattr("optiland_gui.viewer_panel.QSettings", _RecordingSettings)
    return store


def _layout_lines(viewer, color: str) -> list:  # noqa: ANN001
    return [
        (artist, surface)
        for artist, surface in viewer._layout_artists.items()
        if isinstance(artist, Line2D) and same_color(artist.get_color(), color)
    ]


def test_2d_masks_show_by_default_with_the_aperture_markers_off(
    qapp, mask_optic, settings
) -> None:
    viewer = ViewerPanel(_ConnectorStub(mask_optic)).viewer2D
    assert viewer.show_apertures_checkbox.isChecked() is False
    assert viewer.show_masks_checkbox.isChecked() is True

    viewer._plot_optic_sync()

    red = _layout_lines(viewer, MASK_COLOR)
    assert red
    assert {id(surface) for _, surface in red} == {
        id(mask_optic.surfaces.surfaces[MASK_ROW])
    }
    assert _layout_lines(viewer, STOP_COLOR) == []


def test_2d_show_masks_switch_hides_them_and_is_remembered(
    qapp, mask_optic, settings
) -> None:
    viewer = ViewerPanel(_ConnectorStub(mask_optic)).viewer2D

    viewer.show_masks_checkbox.setChecked(False)
    viewer._plot_optic_sync()

    assert _layout_lines(viewer, MASK_COLOR) == []
    assert settings["Viewer2D/ShowMasks"] is False
    reopened = ViewerPanel(_ConnectorStub(mask_optic)).viewer2D
    assert reopened.show_masks_checkbox.isChecked() is False


def test_2d_click_on_the_mask_bar_picks_the_mask_row(
    qapp, mask_optic, settings
) -> None:
    viewer = ViewerPanel(_ConnectorStub(mask_optic)).viewer2D
    viewer._plot_optic_sync()
    viewer.ax.get_xlim()  # settle the pending autoscale before mapping pixels
    z = float(be.to_numpy(mask_optic.surfaces.surfaces[MASK_ROW].geometry.cs.z))

    x_px, y_px = viewer.ax.transData.transform((z, 1.0))

    assert viewer.pick_surfaces_at(float(x_px), float(y_px)) == [MASK_ROW]


def test_3d_masks_checkbox_is_forwarded_to_the_3d_render(
    qapp, mask_optic, settings, monkeypatch
) -> None:
    panel = ViewerPanel(_ConnectorStub(mask_optic))
    if panel._viewer3d_tab_index < 0 or not panel._ensure_3d_viewer():
        pytest.skip("VTK is not available")
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        "optiland_gui.viewer_panel.VTKViewer.render_optic",
        lambda self, **kwargs: calls.append(kwargs),
    )
    monkeypatch.setattr(panel.viewer2D, "plot_optic", lambda *args, **kwargs: None)
    panel.tabWidget.setCurrentIndex(panel._viewer3d_tab_index)
    panel._activate_3d_view()

    assert panel._chk_3d_masks.isChecked() is True
    assert calls[-1]["show_masks"] is True

    calls.clear()
    panel._chk_3d_masks.setChecked(False)
    assert calls
    assert calls[-1]["show_masks"] is False


def test_vtk_viewer_forwards_show_masks_to_the_system_plotter(
    qapp, mask_optic, settings, monkeypatch
) -> None:
    panel = ViewerPanel(_ConnectorStub(mask_optic))
    if panel._viewer3d_tab_index < 0 or not panel._ensure_3d_viewer():
        pytest.skip("VTK is not available")
    viewer = panel.viewer3D
    captured: list[dict[str, object]] = []
    monkeypatch.setattr(
        "optiland_gui.viewer_panel.Rays3D.plot", lambda self, *args, **kwargs: None
    )
    monkeypatch.setattr(
        "optiland_gui.viewer_panel.OptilandOpticalSystemPlotter.plot",
        lambda self, *args, **kwargs: captured.append(kwargs),
    )
    # Render synchronously: no deferred timer, no OpenGL draw.
    monkeypatch.setattr(
        "optiland_gui.viewer_panel.QTimer",
        SimpleNamespace(singleShot=lambda *args, **kwargs: None),
    )
    monkeypatch.setattr(
        viewer.vtkWidget,
        "GetRenderWindow",
        lambda: SimpleNamespace(Render=lambda: None),
    )

    viewer.render_optic()
    viewer._render_optic_sync()
    assert captured[-1]["show_masks"] is True

    viewer.render_optic(show_masks=False)
    viewer._render_optic_sync()
    assert captured[-1]["show_masks"] is False

    # Omitting the flag keeps the last value.
    viewer.render_optic()
    viewer._render_optic_sync()
    assert captured[-1]["show_masks"] is False
