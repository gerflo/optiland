"""The printed 2D layout: no selection marker, numbered elements, a legend.

User request (2026-09-25): the arrow of the element selected in the Lens
Data Editor must not be printed, and the printed layout numbers its
elements and names them in a legend under the plot.
"""

from __future__ import annotations

import numpy as np
import pytest
from matplotlib.text import Annotation

import optiland.backend as be
from optiland.optic import Optic
from optiland_gui.layout_print import (
    CALLOUT_MIN_FONT_PT,
    ROW_SPAN_DASH,
    collect_layout_elements,
    element_label,
    place_callouts,
)
from optiland_gui.viewer_panel import HIGHLIGHT_MARKER_LABEL, MatplotlibViewer
from tests.gui.test_layout_selection_highlight import _ConnectorStub, _make_viewer

GROUP = "LENS-01"


def _grouped_optic() -> Optic:
    """Target, a grouped catalog lens, a field stop, an ungrouped lens, a sensor."""
    optic = Optic()
    optic.surfaces.add(index=0, radius=be.inf, thickness=20.0, comment="Target")
    optic.surfaces.add(
        index=1,
        radius=50.0,
        thickness=4.0,
        material="N-BK7",
        comment=f"{GROUP} S1",
        group_id="g1",
        group_name=GROUP,
    )
    optic.surfaces.add(
        index=2,
        radius=-50.0,
        thickness=10.0,
        comment=f"{GROUP} S2",
        group_id="g1",
        group_name=GROUP,
    )
    optic.surfaces.add(
        index=3, radius=be.inf, thickness=10.0, is_stop=True, comment="Field stop"
    )
    optic.surfaces.add(index=4, radius=30.0, thickness=3.0, material="N-BK7")
    optic.surfaces.add(index=5, radius=-30.0, thickness=30.0)
    optic.surfaces.add(index=6, radius=be.inf, thickness=0.0, comment="Sensor")
    optic.set_aperture(aperture_type="EPD", value=5.0)
    optic.fields.set_type("object_height")
    optic.fields.add(y=0.0)
    optic.fields.add(y=1.0)
    optic.wavelengths.add(value=0.55, is_primary=True)
    optic.updater.update()
    return optic


EXPECTED_LEGEND = [
    (1, "Target (S0)"),
    (2, f"{GROUP} (S1{ROW_SPAN_DASH}S2)"),
    (3, "Field stop (S3)"),
    (4, f"Lens (S4{ROW_SPAN_DASH}S5)"),
    (5, "Sensor (S6)"),
]


def _viewer_with_apertures(monkeypatch, optic: Optic) -> MatplotlibViewer:
    """A layout viewer that draws aperture markers, so the stop is an element."""
    viewer = _make_viewer(monkeypatch, _ConnectorStub(optic))
    viewer.resize(900, 500)
    viewer.show_apertures_checkbox.setChecked(True)
    viewer._plot_optic_sync()
    return viewer


@pytest.fixture()
def viewer(qapp, monkeypatch) -> MatplotlibViewer:
    return _viewer_with_apertures(monkeypatch, _grouped_optic())


def _markers(viewer: MatplotlibViewer) -> list:
    return [p for p in viewer.ax.patches if p.get_label() == HIGHLIGHT_MARKER_LABEL]


def _callouts(viewer: MatplotlibViewer) -> list[Annotation]:
    return [
        text
        for text in viewer.ax.texts
        if isinstance(text, Annotation) and text.get_bbox_patch() is not None
    ]


def _lens_face(viewer: MatplotlibViewer):
    """Fill colour of the grouped lens polygon."""
    for artist, component in viewer._layout_artists.items():
        pair = getattr(component, "polygon_surfaces", {}).get(artist)
        if pair and getattr(pair[0], "group_id", None) == "g1":
            return tuple(artist.get_facecolor())
    raise AssertionError("grouped lens polygon not found")


@pytest.fixture()
def printed(viewer, monkeypatch):
    """Render the print page and record what the figure showed while saving."""
    seen: dict = {}
    original = viewer.figure.savefig

    def savefig(*args, **kwargs):
        seen["markers"] = len(_markers(viewer))
        seen["lens_face"] = _lens_face(viewer)
        seen["callouts"] = [
            (text.get_text(), text.get_fontsize()) for text in _callouts(viewer)
        ]
        return original(*args, **kwargs)

    monkeypatch.setattr(viewer.figure, "savefig", savefig)
    return viewer, seen


class TestSelectionIsNotPrinted:
    def test_selected_element_prints_without_arrow_or_emphasis(self, printed):
        viewer, seen = printed
        plain_face = _lens_face(viewer)
        viewer.set_highlighted_surfaces([1, 2], True)
        assert len(_markers(viewer)) == 1
        assert _lens_face(viewer) != plain_face

        page = viewer._render_layout_page()

        assert not page.image.isNull()
        assert seen["markers"] == 0
        assert seen["lens_face"] == plain_face

    def test_selection_is_shown_again_after_printing(self, printed):
        viewer, _ = printed
        viewer.set_highlighted_surfaces([1, 2], True)
        emphasized = _lens_face(viewer)

        viewer._render_layout_page()

        assert len(_markers(viewer)) == 1
        assert _lens_face(viewer) == emphasized


class TestElementNumbers:
    def test_every_element_is_numbered_and_named_in_the_legend(self, printed):
        viewer, seen = printed

        page = viewer._render_layout_page()

        assert [(e.number, e.label) for e in page.legend] == EXPECTED_LEGEND
        assert [text for text, _ in seen["callouts"]] == ["1", "2", "3", "4", "5"]

    def test_numbers_are_removed_after_printing(self, printed):
        viewer, _ = printed

        viewer._render_layout_page()

        assert _callouts(viewer) == []

    def test_numbers_are_as_large_as_the_tick_labels(self, printed):
        viewer, seen = printed
        tick_size = viewer.ax.get_xticklabels()[0].get_fontsize()

        viewer._render_layout_page()

        expected = max(tick_size, CALLOUT_MIN_FONT_PT)
        assert {size for _, size in seen["callouts"]} == {expected}

    def test_numbers_sit_over_their_elements_inside_the_axes(self, viewer):
        elements = collect_layout_elements(viewer._layout_artists, viewer._layout_optic)
        placed = place_callouts(viewer.ax, elements)

        assert [callout.number for _, callout in placed] == [1, 2, 3, 4, 5]
        for element, callout in placed:
            z = element.points[:, 0]
            z = z[np.isfinite(z)]
            assert z.min() <= callout.x <= z.max()
            # Above the element's top, but inside the axes.
            y_top = float(np.nanmax(element.points[:, 1]))
            top_frac = viewer.ax.transLimits.transform((0.0, y_top))[1]
            assert top_frac < callout.y < 1.0

    def test_numbers_do_not_overlap(self, viewer):
        from optiland_gui.layout_print import draw_callouts

        elements = collect_layout_elements(viewer._layout_artists, viewer._layout_optic)
        # Zoom far out: all five elements within a few pixels of each other.
        viewer.ax.set_xlim(-2000.0, 2000.0)
        placed = place_callouts(viewer.ax, elements)
        artists = draw_callouts(viewer.ax, [callout for _, callout in placed])
        renderer = viewer.canvas.get_renderer()
        viewer.canvas.draw()
        boxes = [a.get_bbox_patch().get_window_extent(renderer) for a in artists]
        axes_box = viewer.ax.bbox

        assert len(placed) == 5
        assert len({round(callout.y, 6) for _, callout in placed}) > 1
        for index, first in enumerate(boxes):
            assert axes_box.y0 <= first.y0 and first.y1 <= axes_box.y1 + 0.5
            for second in boxes[index + 1 :]:
                assert not first.overlaps(second)

    def test_numbers_stay_inside_a_view_tight_around_the_optic(self, viewer):
        from optiland_gui.layout_print import draw_callouts

        elements = collect_layout_elements(viewer._layout_artists, viewer._layout_optic)
        top = max(float(np.nanmax(e.points[:, 1])) for e in elements)
        # No room above the tallest element: the circles must move down.
        viewer.ax.set_ylim(-1.01 * top, 1.01 * top)
        placed = place_callouts(viewer.ax, elements)
        artists = draw_callouts(viewer.ax, [callout for _, callout in placed])
        renderer = viewer.canvas.get_renderer()
        viewer.canvas.draw()

        axes_box = viewer.ax.bbox
        for artist in artists:
            box = artist.get_bbox_patch().get_window_extent(renderer)
            assert axes_box.y0 <= box.y0 and box.y1 <= axes_box.y1 + 0.5

    def test_elements_that_are_not_drawn_get_no_number(self, qapp, monkeypatch):
        viewer = _make_viewer(monkeypatch, _ConnectorStub(_grouped_optic()))
        viewer.show_apertures_checkbox.setChecked(False)
        viewer._plot_optic_sync()

        page = viewer._render_layout_page()

        assert [e.label for e in page.legend] == [
            "Target (S0)",
            f"{GROUP} (S1{ROW_SPAN_DASH}S2)",
            f"Lens (S4{ROW_SPAN_DASH}S5)",
            "Sensor (S6)",
        ]
        assert [e.number for e in page.legend] == [1, 2, 3, 4]

    def test_only_visible_elements_are_numbered(self, viewer):
        elements = collect_layout_elements(viewer._layout_artists, viewer._layout_optic)
        stop_z = float(viewer._layout_optic.surfaces.surfaces[3].geometry.cs.z)
        viewer.ax.set_xlim(stop_z - 1.0, stop_z + 20.0)

        placed = place_callouts(viewer.ax, elements)

        labels = [element_label(e, viewer._layout_optic) for e, _ in placed]
        assert labels == ["Field stop", "Lens"]
        assert [callout.number for _, callout in placed] == [1, 2]


class TestElements:
    def test_group_is_one_element_named_after_the_group(self, viewer):
        optic = viewer._layout_optic
        elements = collect_layout_elements(viewer._layout_artists, optic)
        surfaces = optic.surfaces.surfaces

        assert [e.kind for e in elements] == [
            "surface",
            "group",
            "surface",
            "lens",
            "surface",
        ]
        assert elements[1].surfaces == [surfaces[1], surfaces[2]]
        assert elements[3].surfaces == [surfaces[4], surfaces[5]]
        assert [element_label(e, optic) for e in elements] == [
            "Target",
            GROUP,
            "Field stop",
            "Lens",
            "Sensor",
        ]

    def test_unnamed_surfaces_are_named_by_what_they_are(self, qapp, monkeypatch):
        optic = _grouped_optic()
        for surface in optic.surfaces.surfaces:
            surface.comment = ""
        viewer = _viewer_with_apertures(monkeypatch, optic)

        elements = collect_layout_elements(viewer._layout_artists, optic)

        assert [element_label(e, optic) for e in elements] == [
            "Object",
            GROUP,
            "Aperture stop",
            "Lens",
            "Image",
        ]
