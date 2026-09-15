"""Clicking an element or surface in the 2D or 3D layout selects it in the editor."""

from __future__ import annotations

import math
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QObject, Signal

import optiland.backend as be
import optiland_gui.viewer_panel as viewer_panel
from optiland.visualization.system.lens import Lens2D
from optiland.visualization.system.surface import Surface2D
from optiland_gui.viewer_panel import (
    PICK_RADIUS_PX,
    MatplotlibViewer,
    ViewerPanel,
    editor_surface_index,
    effective_surface_index,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _DefaultSettings:
    """QSettings stand-in that always answers with the default value."""

    def __init__(self, *_args, **_kwargs) -> None:
        pass

    def value(self, _key: str, default=None, *, type=None):  # noqa: A002, ANN001
        if type is bool:
            return bool(default)
        if type is int:
            return int(default)
        return default

    def setValue(self, _key: str, _value) -> None:  # noqa: ANN001
        return None


class _ConnectorStub(QObject):
    opticLoaded = Signal()
    opticChanged = Signal()

    def __init__(self, optic, *, editor_rows=None, disabled=()) -> None:
        super().__init__()
        self._optic = optic
        self.toast_manager = None
        self._editor_rows = editor_rows
        self._disabled = set(disabled)

    def get_optic(self):  # noqa: ANN201
        return self._optic

    def get_effective_optic(self):  # noqa: ANN201
        return self._optic

    def get_surface_count(self) -> int:
        if self._editor_rows is not None:
            return self._editor_rows
        return self._optic.surfaces.num_surfaces

    def get_disabled_surface_indices(self) -> set[int]:
        return set(self._disabled)


class _PickerHitting:
    """vtkCellPicker stand-in that always hits *actor*."""

    def __init__(self, actor) -> None:  # noqa: ANN001
        self._actor = actor

    def Pick(self, *_args) -> int:  # noqa: N802
        return 1

    def GetActor(self):  # noqa: ANN201, N802
        return self._actor


def _vertex_z(optic, surface_index: int) -> float:
    """Global z of a surface vertex of *optic*."""
    return float(be.to_numpy(optic.surfaces.surfaces[surface_index].geometry.cs.z))


def _make_2d_viewer(monkeypatch, connector) -> MatplotlibViewer:
    monkeypatch.setattr("optiland_gui.viewer_panel.QSettings", _DefaultSettings)
    viewer = MatplotlibViewer(connector)
    viewer._plot_optic_sync()
    viewer.ax.get_xlim()  # settle the pending autoscale before mapping pixels
    return viewer


def _pixel(viewer: MatplotlibViewer, z: float, y: float) -> tuple[float, float]:
    x_px, y_px = viewer.ax.transData.transform((z, y))
    return float(x_px), float(y_px)


def _press(viewer: MatplotlibViewer, x: float, y: float) -> None:
    viewer.on_mouse_button_press(
        SimpleNamespace(button=1, inaxes=viewer.ax, x=x, y=y, xdata=0.0, ydata=0.0)
    )


def _move(viewer: MatplotlibViewer, x: float, y: float) -> None:
    viewer.on_mouse_move_on_plot(
        SimpleNamespace(inaxes=viewer.ax, x=x, y=y, xdata=0.0, ydata=0.0, key=None)
    )


def _release(viewer: MatplotlibViewer, x: float, y: float) -> None:
    viewer.on_mouse_button_release(
        SimpleNamespace(button=1, inaxes=viewer.ax, x=x, y=y)
    )


def _make_panel(monkeypatch, optic) -> ViewerPanel:
    monkeypatch.setattr("optiland_gui.viewer_panel.QSettings", _DefaultSettings)
    monkeypatch.setattr(
        "optiland_gui.viewer_panel.VTKViewer.render_optic",
        lambda self, *args, **kwargs: None,
    )
    return ViewerPanel(_ConnectorStub(optic))


# ---------------------------------------------------------------------------
# Row mapping
# ---------------------------------------------------------------------------


def test_editor_surface_index_inverts_effective_surface_index() -> None:
    surface_count = 6
    # Object and image rows are never dropped from the drawn optic.
    for disabled in (set(), {1}, {2, 4}, {0, 5}):
        for row in range(surface_count):
            drawn = effective_surface_index(row, disabled, surface_count)
            if drawn is None:
                continue
            assert editor_surface_index(drawn, disabled, surface_count) == row
    # With one row disabled the drawn optic has one surface fewer.
    assert editor_surface_index(5, {1}, surface_count) is None


# ---------------------------------------------------------------------------
# 2D layout
# ---------------------------------------------------------------------------


def test_2d_click_inside_a_lens_picks_the_whole_element(
    qapp, minimal_optic, monkeypatch
) -> None:
    viewer = _make_2d_viewer(monkeypatch, _ConnectorStub(minimal_optic))
    front, back = _vertex_z(minimal_optic, 1), _vertex_z(minimal_optic, 2)
    inside = _pixel(viewer, 0.5 * (front + back), 0.0)
    # Far enough from both lens surfaces not to be a click on either of them.
    for z in (front, back):
        assert math.dist(inside, _pixel(viewer, z, 0.0)) > PICK_RADIUS_PX

    assert viewer.pick_surfaces_at(*inside) == [1, 2]


@pytest.mark.parametrize("surface_index", [1, 2, 3])
def test_2d_click_on_a_surface_picks_only_that_surface(
    qapp, minimal_optic, monkeypatch, surface_index
) -> None:
    viewer = _make_2d_viewer(monkeypatch, _ConnectorStub(minimal_optic))
    vertex = _pixel(viewer, _vertex_z(minimal_optic, surface_index), 0.0)

    assert viewer.pick_surfaces_at(*vertex) == [surface_index]


def test_2d_click_on_empty_space_picks_nothing(
    qapp, minimal_optic, monkeypatch
) -> None:
    viewer = _make_2d_viewer(monkeypatch, _ConnectorStub(minimal_optic))
    middle = 0.5 * (_vertex_z(minimal_optic, 2) + _vertex_z(minimal_optic, 3))
    top = max(viewer.ax.get_ylim())

    assert viewer.pick_surfaces_at(*_pixel(viewer, middle, 0.9 * top)) == []


def test_2d_picks_map_past_disabled_editor_rows(
    qapp, minimal_optic, monkeypatch
) -> None:
    # Editor rows: 0 object, 1 disabled, 2-3 the lens, 4 image. The drawn
    # optic omits the disabled row, so its surfaces sit one row further down.
    connector = _ConnectorStub(minimal_optic, editor_rows=5, disabled={1})
    viewer = _make_2d_viewer(monkeypatch, connector)
    front, back, image = (_vertex_z(minimal_optic, k) for k in (1, 2, 3))

    assert viewer.pick_surfaces_at(*_pixel(viewer, 0.5 * (front + back), 0.0)) == [
        2,
        3,
    ]
    assert viewer.pick_surfaces_at(*_pixel(viewer, image, 0.0)) == [4]


def test_2d_left_click_emits_the_picked_rows(qapp, minimal_optic, monkeypatch) -> None:
    viewer = _make_2d_viewer(monkeypatch, _ConnectorStub(minimal_optic))
    picked: list[list[int]] = []
    viewer.surfacesPicked.connect(picked.append)
    x, y = _pixel(viewer, _vertex_z(minimal_optic, 3), 0.0)

    _press(viewer, x, y)
    _move(viewer, x + 2, y)  # a hand never holds perfectly still
    _release(viewer, x + 2, y)

    assert picked == [[3]]


def test_2d_drag_pans_without_picking(qapp, minimal_optic, monkeypatch) -> None:
    viewer = _make_2d_viewer(monkeypatch, _ConnectorStub(minimal_optic))
    picked: list[list[int]] = []
    viewer.surfacesPicked.connect(picked.append)
    x, y = _pixel(viewer, _vertex_z(minimal_optic, 3), 0.0)

    _press(viewer, x, y)
    _move(viewer, x + 25, y)
    _move(viewer, x, y)  # back where it started: still a pan, not a click
    _release(viewer, x, y)

    assert picked == []


# ---------------------------------------------------------------------------
# 3D layout
# ---------------------------------------------------------------------------


@pytest.fixture()
def viewer3d(qapp, minimal_optic, monkeypatch):
    if not viewer_panel.VTK_AVAILABLE:
        pytest.skip("VTK is not available")
    viewer = viewer_panel.VTKViewer(_ConnectorStub(minimal_optic))
    render_window = viewer.vtkWidget.GetRenderWindow()
    # The widget is never shown: build the scene and pick without drawing.
    viewer.iren.SetEnableRender(False)
    monkeypatch.setattr(
        viewer.vtkWidget,
        "GetRenderWindow",
        lambda: SimpleNamespace(Render=lambda: None),
    )
    viewer._render_optic_sync()
    render_window.SetSize(400, 300)
    return viewer


def _display_pixel(viewer, x: float, y: float, z: float) -> tuple[int, int]:
    renderer = viewer.renderer
    renderer.SetWorldPoint(x, y, z, 1.0)
    renderer.WorldToDisplay()
    display_x, display_y, _ = renderer.GetDisplayPoint()
    return round(display_x), round(display_y)


def _left_click_3d(viewer, start, end=None) -> None:  # noqa: ANN001
    iren = viewer.iren
    iren.SetEventInformation(*start, 0, 0, chr(0), 0, None)
    iren.LeftButtonPressEvent()
    if end is not None:
        iren.SetEventInformation(*end, 0, 0, chr(0), 0, None)
        iren.MouseMoveEvent()
    iren.LeftButtonReleaseEvent()


def _lens_center_display(viewer, optic) -> tuple[int, int]:
    middle = 0.5 * (_vertex_z(optic, 1) + _vertex_z(optic, 2))
    return _display_pixel(viewer, 0.0, 2.0, middle)


def test_3d_click_on_a_lens_picks_the_whole_element(viewer3d, minimal_optic) -> None:
    inside = _lens_center_display(viewer3d, minimal_optic)

    assert viewer3d.pick_surfaces_at(*inside) == [1, 2]
    assert viewer3d.pick_surfaces_at(2, 2) == []


def test_3d_layout_actors_map_to_their_editor_rows(
    viewer3d, minimal_optic, monkeypatch
) -> None:
    import vtk

    stop = minimal_optic.surfaces.surfaces[2]
    image = minimal_optic.surfaces.surfaces[3]
    kinds: set[str] = set()
    for actor, target in viewer3d._layout_actors.items():
        if isinstance(target, Lens2D):
            kind, rows = "lens", [1, 2]
        elif isinstance(target, Surface2D) and target.surf is image:
            kind, rows = "image", [3]
        elif target is stop:
            kind, rows = "stop aperture", [2]
        else:
            pytest.fail(f"unexpected layout actor target {target!r}")
        monkeypatch.setattr(
            viewer3d, "_create_picker", lambda actor=actor: _PickerHitting(actor)
        )
        assert viewer3d.pick_surfaces_at(0, 0) == rows, kind
        kinds.add(kind)
    assert kinds == {"lens", "image", "stop aperture"}

    # An actor outside the layout, such as a ray, selects nothing.
    monkeypatch.setattr(
        viewer3d, "_create_picker", lambda: _PickerHitting(vtk.vtkActor())
    )
    assert viewer3d.pick_surfaces_at(0, 0) == []


def test_3d_only_layout_actors_answer_picks(viewer3d) -> None:
    actors = viewer3d.renderer.GetActors()
    actors.InitTraversal()
    others = 0
    while (actor := actors.GetNextActor()) is not None:
        in_layout = actor in viewer3d._layout_actors
        assert bool(actor.GetPickable()) is in_layout
        others += not in_layout
    assert others > 0  # the rays were drawn and are out of the way


def test_3d_click_emits_the_pick_but_a_camera_drag_does_not(
    viewer3d, minimal_optic
) -> None:
    picked: list[list[int]] = []
    viewer3d.surfacesPicked.connect(picked.append)
    inside = _lens_center_display(viewer3d, minimal_optic)

    _left_click_3d(viewer3d, inside)
    assert picked == [[1, 2]]

    picked.clear()
    _left_click_3d(viewer3d, inside, (inside[0] + 30, inside[1]))
    assert picked == []


# ---------------------------------------------------------------------------
# Viewer panel
# ---------------------------------------------------------------------------


def test_3d_layout_tab_has_a_gear_for_the_shared_settings_panel(
    qapp, minimal_optic, monkeypatch
) -> None:
    panel = _make_panel(monkeypatch, minimal_optic)
    if panel._viewer3d_tab_index < 0:
        pytest.skip("VTK is not available")
    gear_2d = panel.viewer2D.settings_toggle_btn
    gear_3d = panel._btn_3d_settings
    settings = panel.settings_area
    sag_tab_index = panel.tabWidget.indexOf(panel.sagViewer)
    # One panel, holding the 2D layout's controls, laid out beside the tabs.
    assert settings.parentWidget() is panel
    assert settings.isAncestorOf(panel.viewer2D.num_rays_spinbox)
    assert settings.isHidden()

    panel.tabWidget.setCurrentIndex(panel._viewer3d_tab_index)
    gear_3d.click()
    assert gear_3d.isChecked()
    assert gear_2d.isChecked()
    assert not settings.isHidden()

    panel.tabWidget.setCurrentIndex(panel._viewer2d_tab_index)
    assert not settings.isHidden()

    panel.tabWidget.setCurrentIndex(sag_tab_index)
    assert settings.isHidden()  # the Sag tab has settings of its own

    panel.tabWidget.setCurrentIndex(panel._viewer3d_tab_index)
    assert not settings.isHidden()

    gear_2d.click()
    assert not gear_3d.isChecked()
    assert settings.isHidden()


def test_viewer_panel_forwards_picks_from_both_layouts(
    qapp, minimal_optic, monkeypatch
) -> None:
    panel = _make_panel(monkeypatch, minimal_optic)
    picked: list[list[int]] = []
    panel.surfacesPicked.connect(picked.append)

    panel.viewer2D.surfacesPicked.emit([3])
    assert picked == [[3]]

    if panel._viewer3d_tab_index < 0 or not panel._ensure_3d_viewer():
        return
    panel.viewer3D.surfacesPicked.emit([1, 2])
    assert picked == [[3], [1, 2]]
