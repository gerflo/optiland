"""The Lens Data Editor selection is mirrored as a highlight in the 2D layout."""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pytest
from matplotlib.patches import Polygon
from PySide6.QtCore import QObject, Signal

from optiland_gui.viewer_panel import (
    HIGHLIGHT_ARROW_TOP_PAD_PX,
    HIGHLIGHT_LINE_WIDTH_PT,
    HIGHLIGHT_MARKER_LABEL,
    HIGHLIGHT_MARKER_MIN_WIDTH_PX,
    MatplotlibViewer,
    _luminance,
    effective_surface_index,
    emphasize_color,
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


def _make_viewer(monkeypatch, connector) -> MatplotlibViewer:
    monkeypatch.setattr("optiland_gui.viewer_panel.QSettings", _DefaultSettings)
    viewer = MatplotlibViewer(connector)
    viewer._plot_optic_sync()
    return viewer


@pytest.fixture()
def viewer(qapp, minimal_optic, monkeypatch) -> MatplotlibViewer:
    return _make_viewer(monkeypatch, _ConnectorStub(minimal_optic))


def _lens_polygons(viewer: MatplotlibViewer) -> list[Polygon]:
    return [
        patch
        for patch in viewer.ax.patches
        if isinstance(patch, Polygon) and patch.get_label() != HIGHLIGHT_MARKER_LABEL
    ]


def _markers(viewer: MatplotlibViewer) -> list[Polygon]:
    return [p for p in viewer.ax.patches if p.get_label() == HIGHLIGHT_MARKER_LABEL]


def _marker_vertices(marker: Polygon) -> np.ndarray:
    xy = np.asarray(marker.get_xy(), dtype=float)
    if len(xy) > 1 and np.allclose(xy[0], xy[-1]):
        xy = xy[:-1]  # closed polygons repeat the first vertex
    return xy


def _give_headroom(viewer: MatplotlibViewer) -> None:
    """Widen the view so the nominal marker height is inside the axes."""
    viewer.ax.set_ylim(-25.0, 25.0)


def _marker_tip(marker: Polygon) -> tuple[float, float]:
    xy = _marker_vertices(marker)
    tip = xy[np.argmin(xy[:, 1])]
    return float(tip[0]), float(tip[1])


def _marker_head_width(marker: Polygon) -> float:
    xy = np.asarray(marker.get_xy(), dtype=float)
    return float(xy[:, 0].max() - xy[:, 0].min())


def _px_per_unit_x(viewer: MatplotlibViewer) -> float:
    x0, x1 = viewer.ax.get_xlim()
    return viewer.ax.bbox.width / (x1 - x0)


def _px_per_unit_y(viewer: MatplotlibViewer) -> float:
    y0, y1 = viewer.ax.get_ylim()
    return viewer.ax.bbox.height / (y1 - y0)


def _marker_width_px(viewer: MatplotlibViewer, marker: Polygon) -> float:
    return _marker_head_width(marker) * _px_per_unit_x(viewer)


def _component_extents(viewer: MatplotlibViewer) -> list[tuple[float, float]]:
    """(top, bottom) of every drawn lens polygon and standalone surface line."""
    extents = []
    for polygon in _lens_polygons(viewer):
        y = np.asarray(polygon.get_xy(), dtype=float)[:, 1]
        extents.append((float(np.nanmax(y)), float(np.nanmin(y))))
    for artist, component in viewer._layout_artists.items():
        if hasattr(component, "surf") and hasattr(artist, "get_ydata"):
            y = np.asarray(artist.get_ydata(), dtype=float)
            if np.isfinite(y).any():
                extents.append((float(np.nanmax(y)), float(np.nanmin(y))))
    return extents


def _expected_marker_y(viewer: MatplotlibViewer) -> float:
    """Marker tip height computed independently of the viewer."""
    extents = _component_extents(viewer)
    top = max(t for t, _ in extents)
    height = max(t - b for t, b in extents)
    return max(1.10 * height, top + 0.10 * height)


def _image_line(viewer: MatplotlibViewer):
    image_surface = viewer._layout_optic.surfaces.surfaces[-1]
    for artist, component in viewer._layout_artists.items():
        if getattr(component, "surf", None) is image_surface:
            return artist
    raise AssertionError("image surface line not found")


@pytest.fixture()
def mock_connector(minimal_optic, qapp):
    conn = MagicMock()
    conn._optic = minimal_optic
    conn.toast_manager = MagicMock()
    conn.COL_TYPE = 0
    conn.COL_COMMENT = 1
    conn.COL_RADIUS = 2
    conn.COL_THICKNESS = 3
    conn.COL_MATERIAL = 4
    conn.COL_CONIC = 5
    conn.COL_SEMI_DIAMETER = 6
    conn.get_column_headers.return_value = [
        "Type",
        "Comment",
        "Radius",
        "Thickness",
        "Material",
        "Conic",
        "Semi-Diameter",
    ]
    conn.get_surface_count.return_value = 4
    conn.get_optimization_variables.return_value = []
    conn.get_surface_type_info.return_value = {
        "display_text": "Standard",
        "is_changeable": True,
        "has_extra_params": False,
    }
    conn.get_surface_geometry_params.return_value = {}
    conn.get_surface_aperture_config.return_value = {"type": "none"}
    conn.get_surface_data.return_value = ""
    conn.get_available_surface_types.return_value = ["standard", "aspheric"]
    conn.get_surface_group_metadata.return_value = {
        "group_id": None,
        "group_name": None,
        "group_role": None,
    }
    conn.get_group_rows.return_value = []
    return conn


def _group_rows_1_2(mock_connector) -> None:
    mock_connector.get_group_rows.side_effect = lambda row: [1, 2] if row in (1, 2) else []
    mock_connector.get_surface_group_metadata.side_effect = lambda row: (
        {"group_id": "grp1", "group_name": "L1", "group_role": "lens"}
        if row in (1, 2)
        else {"group_id": None, "group_name": None, "group_role": None}
    )


def _record_selection(editor) -> list[tuple[list[int], bool]]:
    received: list[tuple[list[int], bool]] = []
    editor.surfaceSelectionChanged.connect(
        lambda surfaces, is_element: received.append((list(surfaces), bool(is_element)))
    )
    return received


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_emphasize_color_brightens_on_dark_and_darkens_on_light() -> None:
    on_dark = emphasize_color("#5E5E5E", "#1B1B1B")
    on_light = emphasize_color("#E0E0E0", "#FFFFFF")

    assert _luminance(on_dark) > _luminance("#5E5E5E")
    assert _luminance(on_light) < _luminance("#E0E0E0")
    assert emphasize_color("#5E5E5E", "#1B1B1B", alpha=1.0)[3] == 1.0


def test_effective_surface_index_skips_disabled_rows() -> None:
    disabled = {2}
    assert effective_surface_index(1, disabled, 6) == 1
    assert effective_surface_index(2, disabled, 6) is None
    assert effective_surface_index(3, disabled, 6) == 2
    assert effective_surface_index(5, disabled, 6) == 4
    # Object and image rows are never removed from the drawn optic.
    assert effective_surface_index(3, {0, 5}, 6) == 3


# ---------------------------------------------------------------------------
# 2D viewer
# ---------------------------------------------------------------------------


def test_element_highlight_brightens_lens_and_marks_its_width(viewer) -> None:
    (polygon,) = _lens_polygons(viewer)
    original = polygon.get_facecolor()
    _give_headroom(viewer)

    viewer.set_highlighted_surfaces([1, 2], True)

    assert _luminance(polygon.get_facecolor()) > _luminance(original) + 0.2
    (marker,) = _markers(viewer)
    vertices = np.asarray(polygon.get_xy(), dtype=float)
    z_min, z_max = vertices[:, 0].min(), vertices[:, 0].max()
    tip_x, tip_y = _marker_tip(marker)
    assert tip_x == pytest.approx(0.5 * (z_min + z_max))
    assert tip_y == pytest.approx(_expected_marker_y(viewer))
    assert _marker_width_px(viewer, marker) > HIGHLIGHT_MARKER_MIN_WIDTH_PX
    assert _marker_head_width(marker) == pytest.approx(1.10 * (z_max - z_min))


def test_surface_highlight_traces_lens_surface_bold_with_marker(viewer) -> None:
    (polygon,) = _lens_polygons(viewer)
    original = polygon.get_facecolor()
    _give_headroom(viewer)

    viewer.set_highlighted_surfaces([1], False)

    assert polygon.get_facecolor() == pytest.approx(original)
    lines = [a for a in viewer._highlight_artists if not isinstance(a, Polygon)]
    (line,) = lines
    assert line.get_linewidth() == HIGHLIGHT_LINE_WIDTH_PT
    assert _luminance(line.get_color()) > _luminance(viewer.ax.get_facecolor()) + 0.5
    z = np.asarray(line.get_xdata(), dtype=float)
    # Surface 1 has R = 50 and a 10 mm aperture: a shallow curve at z ~ 0.
    assert np.nanmin(z) == pytest.approx(0.0, abs=1e-3)
    assert 0.2 < np.nanmax(z) < 0.3
    (marker,) = _markers(viewer)
    tip_x, tip_y = _marker_tip(marker)
    assert tip_x == pytest.approx(0.5 * (np.nanmin(z) + np.nanmax(z)))
    assert tip_y == pytest.approx(_expected_marker_y(viewer))
    # The surface is far narrower than 20 px, so the head is widened to it.
    assert _marker_width_px(viewer, marker) == pytest.approx(HIGHLIGHT_MARKER_MIN_WIDTH_PX)


def test_marker_is_an_arrow_pointing_down(viewer) -> None:
    viewer.set_highlighted_surfaces([1, 2], True)
    (marker,) = _markers(viewer)

    xy = _marker_vertices(marker)
    tip_x, tip_y = _marker_tip(marker)
    # Exactly one vertex is lowest (the tip); the head corners are above it
    # at the full width; the shaft is narrower and above the head.
    assert np.sum(np.isclose(xy[:, 1], tip_y)) == 1
    head_level = np.sort(np.unique(np.round(xy[:, 1], 9)))[1]
    head_corners = xy[np.isclose(xy[:, 1], head_level)]
    assert head_corners[:, 0].min() < tip_x < head_corners[:, 0].max()
    assert head_corners[:, 0].max() - head_corners[:, 0].min() == pytest.approx(
        _marker_head_width(marker)
    )
    shaft_top = xy[np.isclose(xy[:, 1], xy[:, 1].max())]
    assert shaft_top[:, 0].max() - shaft_top[:, 0].min() < _marker_head_width(marker)
    assert xy[:, 1].max() > head_level > tip_y


def test_standalone_surface_highlight_emphasizes_its_own_line(viewer) -> None:
    line = _image_line(viewer)
    original_width = line.get_linewidth()
    original_color = line.get_color()

    viewer.set_highlighted_surfaces([3], False)

    assert line.get_linewidth() >= max(HIGHLIGHT_LINE_WIDTH_PT, 2 * original_width)
    assert _luminance(line.get_color()) > _luminance(original_color)
    assert len(_markers(viewer)) == 1

    viewer.set_highlighted_surfaces([], False)

    assert line.get_linewidth() == original_width
    assert line.get_color() == original_color
    assert _markers(viewer) == []


def test_every_marker_sits_on_the_same_height(viewer) -> None:
    expected = _expected_marker_y(viewer)
    extents = _component_extents(viewer)
    tallest = max(t - b for t, b in extents)
    assert expected == pytest.approx(1.10 * tallest)
    assert expected > max(t for t, _ in extents)  # clearly above the layout
    _give_headroom(viewer)

    for selection in ([1, 2], True), ([1], False), ([2], False), ([3], False):
        viewer.set_highlighted_surfaces(*selection)
        (marker,) = _markers(viewer)
        assert _marker_tip(marker)[1] == pytest.approx(expected), selection


def test_marker_minimum_width_follows_the_zoom(viewer) -> None:
    viewer.set_highlighted_surfaces([1], False)
    (marker,) = _markers(viewer)
    assert _marker_width_px(viewer, marker) == pytest.approx(HIGHLIGHT_MARKER_MIN_WIDTH_PX)
    _, z_lo, z_hi = viewer._highlight_markers[0]  # the surface width + 10 %

    # Zooming far in: the surface itself is wider than 20 px on screen, so
    # the head is exactly its width plus 10 %.
    viewer.ax.set_xlim(-0.5, 1.0)
    assert _marker_head_width(marker) == pytest.approx(z_hi - z_lo)
    assert _marker_width_px(viewer, marker) > HIGHLIGHT_MARKER_MIN_WIDTH_PX

    # Zooming out again: back to the pixel minimum at the new scale.
    viewer.ax.set_xlim(-100, 200)
    assert _marker_width_px(viewer, marker) == pytest.approx(HIGHLIGHT_MARKER_MIN_WIDTH_PX)

    # A full redraw reconnects the axes callbacks that ax.clear() dropped.
    viewer._plot_optic_sync()
    (marker,) = _markers(viewer)
    viewer.ax.set_xlim(-100, 200)
    assert _marker_width_px(viewer, marker) == pytest.approx(HIGHLIGHT_MARKER_MIN_WIDTH_PX)


def test_marker_is_pulled_down_when_the_view_has_no_headroom(viewer) -> None:
    # The autoscaled view of the minimal optic ends just above the lens, far
    # below the nominal marker height: the arrow must still be visible.
    viewer.set_highlighted_surfaces([1, 2], True)
    (marker,) = _markers(viewer)
    expected = _expected_marker_y(viewer)
    _, view_top = viewer.ax.get_ylim()
    assert view_top < expected

    xy = _marker_vertices(marker)
    assert _marker_tip(marker)[1] < expected
    pad = HIGHLIGHT_ARROW_TOP_PAD_PX / _px_per_unit_y(viewer)
    assert xy[:, 1].max() == pytest.approx(view_top - pad)

    _give_headroom(viewer)
    assert _marker_tip(marker)[1] == pytest.approx(expected)


def test_clearing_highlight_restores_the_lens_fill(viewer) -> None:
    (polygon,) = _lens_polygons(viewer)
    original = polygon.get_facecolor()
    viewer.set_highlighted_surfaces([1, 2], True)

    viewer.set_highlighted_surfaces([], True)

    assert polygon.get_facecolor() == pytest.approx(original)
    assert _markers(viewer) == []
    assert viewer._highlight_artists == []
    assert viewer._highlight_restores == []
    assert viewer._highlight_markers == []


def test_highlight_is_reapplied_after_a_redraw(viewer) -> None:
    viewer.set_highlighted_surfaces([1, 2], True)
    (old_polygon,) = _lens_polygons(viewer)

    viewer._plot_optic_sync()

    (polygon,) = _lens_polygons(viewer)
    assert polygon is not old_polygon
    assert len(_markers(viewer)) == 1
    assert _luminance(polygon.get_facecolor()) > _luminance("#5E5E5E") + 0.2


def test_highlight_leaves_the_view_untouched(viewer) -> None:
    xlim, ylim = viewer.ax.get_xlim(), viewer.ax.get_ylim()

    viewer.set_highlighted_surfaces([1, 2], True)
    viewer.canvas.draw()
    viewer.set_highlighted_surfaces([3], False)
    viewer.canvas.draw()

    assert viewer.ax.get_xlim() == xlim
    assert viewer.ax.get_ylim() == ylim
    assert viewer._user_initiated_view_change is False


def test_highlight_maps_editor_rows_past_disabled_surfaces(
    qapp, minimal_optic, monkeypatch
) -> None:
    # The editor shows five rows of which row 1 is disabled, so the drawn
    # optic (four surfaces) has its lens at rows 2 and 3 of the editor.
    connector = _ConnectorStub(minimal_optic, editor_rows=5, disabled={1})
    viewer = _make_viewer(monkeypatch, connector)
    (polygon,) = _lens_polygons(viewer)
    original = polygon.get_facecolor()

    viewer.set_highlighted_surfaces([1], False)
    assert viewer._highlight_artists == []  # a disabled row is not drawn

    viewer.set_highlighted_surfaces([2, 3], True)
    assert _luminance(polygon.get_facecolor()) > _luminance(original) + 0.2
    assert len(_markers(viewer)) == 1


def test_setting_the_highlight_while_a_redraw_is_pending_defers_it(viewer) -> None:
    viewer._is_plotting = True

    viewer.set_highlighted_surfaces([1, 2], True)

    assert _markers(viewer) == []
    viewer._plot_optic_sync()
    assert len(_markers(viewer)) == 1


# ---------------------------------------------------------------------------
# Lens Data Editor
# ---------------------------------------------------------------------------


def test_lens_editor_reports_a_plain_row_as_one_surface(qapp, mock_connector) -> None:
    from optiland_gui.lens_editor import LensEditor

    editor = LensEditor(mock_connector)
    received = _record_selection(editor)

    editor.tableWidget.setCurrentCell(2, mock_connector.COL_RADIUS)

    assert received[-1] == ([2], False)


def test_lens_editor_reports_a_collapsed_element_row_as_the_element(
    qapp, mock_connector
) -> None:
    from optiland_gui.lens_editor import LensEditor

    _group_rows_1_2(mock_connector)
    editor = LensEditor(mock_connector)
    received = _record_selection(editor)

    editor.tableWidget.setCurrentCell(1, mock_connector.COL_RADIUS)

    assert received[-1] == ([1, 2], True)


def test_lens_editor_reports_an_expanded_member_row_as_one_surface(
    qapp, mock_connector
) -> None:
    from optiland_gui.lens_editor import LensEditor

    _group_rows_1_2(mock_connector)
    editor = LensEditor(mock_connector)
    editor._toggle_group_expanded(1)
    received = _record_selection(editor)

    editor.tableWidget.setCurrentCell(2, mock_connector.COL_RADIUS)

    assert received[-1] == ([2], False)


def test_lens_editor_reports_a_whole_selected_element_as_the_element(
    qapp, mock_connector
) -> None:
    from optiland_gui.lens_editor import LensEditor

    _group_rows_1_2(mock_connector)
    editor = LensEditor(mock_connector)
    received = _record_selection(editor)

    editor._select_entire_element(1)

    assert received[-1] == ([1, 2], True)


def test_lens_editor_reports_an_empty_selection_after_clearing(
    qapp, mock_connector
) -> None:
    from optiland_gui.lens_editor import LensEditor

    editor = LensEditor(mock_connector)
    received = _record_selection(editor)
    editor.tableWidget.setCurrentCell(2, mock_connector.COL_RADIUS)

    editor.tableWidget.clearSelection()
    editor.tableWidget.setCurrentCell(-1, -1)

    assert received[-1] == ([], False)


def test_lens_editor_reports_the_selection_again_after_a_rebuild(
    qapp, mock_connector
) -> None:
    from optiland_gui.lens_editor import LensEditor

    editor = LensEditor(mock_connector)
    received = _record_selection(editor)
    editor.tableWidget.setCurrentCell(2, mock_connector.COL_RADIUS)
    received.clear()

    editor.full_refresh_from_optic()

    assert editor.tableWidget.currentRow() == 2
    assert received, "a rebuild must republish the selection state"
    assert received[-1] == ([2], False)


# ---------------------------------------------------------------------------
# Editor and viewer wired together
# ---------------------------------------------------------------------------


def test_editor_selection_drives_the_viewer_highlight(
    qapp, minimal_optic, monkeypatch, mock_connector
) -> None:
    from optiland_gui.lens_editor import LensEditor

    viewer = _make_viewer(monkeypatch, _ConnectorStub(minimal_optic))
    _group_rows_1_2(mock_connector)
    editor = LensEditor(mock_connector)
    editor.surfaceSelectionChanged.connect(viewer.set_highlighted_surfaces)
    (polygon,) = _lens_polygons(viewer)
    original = polygon.get_facecolor()

    editor.tableWidget.setCurrentCell(1, mock_connector.COL_RADIUS)
    assert _luminance(polygon.get_facecolor()) > _luminance(original) + 0.2
    assert len(_markers(viewer)) == 1

    editor.tableWidget.setCurrentCell(3, mock_connector.COL_RADIUS)
    assert polygon.get_facecolor() == pytest.approx(original)
    assert _image_line(viewer).get_linewidth() >= HIGHLIGHT_LINE_WIDTH_PT
    assert len(_markers(viewer)) == 1
