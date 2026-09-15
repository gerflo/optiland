"""Analyses of a chosen surface use the rays recorded there and name it."""

from __future__ import annotations

import logging

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pytest

import optiland.backend as be
from optiland import analysis
from optiland.analysis.base import surface_label
from optiland.samples.objectives import CookeTriplet


def _stop_index(optic) -> int:  # noqa: ANN001
    return next(i for i, s in enumerate(optic.surfaces.surfaces) if s.is_stop)


def test_surface_label_shows_the_resolved_number_and_the_comment() -> None:
    optic = CookeTriplet()
    stop = _stop_index(optic)
    last = optic.surfaces.num_surfaces - 1
    optic.surfaces[stop].comment = "Aperture stop"
    optic.surfaces[last].comment = ""

    assert surface_label(optic, stop) == f"Surface {stop}: Aperture stop"
    assert surface_label(optic, -1) == f"Surface {last}"
    with pytest.raises(IndexError):
        surface_label(optic, last + 1)


def test_footprint_shows_where_the_rays_cross_the_chosen_surface(
    set_test_backend,
) -> None:
    optic = CookeTriplet()
    stop = _stop_index(optic)
    settings = {
        "num_rays": 6,
        "fields": [(0.0, 0.0)],
        "wavelengths": "primary",
        "distribution": "hexapolar",
    }

    at_stop = analysis.FootprintDiagram(optic, surface_idx=stop, **settings)
    at_image = analysis.FootprintDiagram(optic, **settings)

    stop_x, stop_y, _ = at_stop.data[0][0]
    image_x, image_y, _ = at_image.data[0][0]
    # On axis the beam fills the stop and converges to a small spot on the image.
    stop_radius = np.hypot(stop_x, stop_y).max()
    assert stop_radius > 1.0
    assert stop_radius > 20 * np.hypot(image_x, image_y).max()


def test_footprint_plot_zooms_without_aspect_warnings(caplog) -> None:
    footprint = analysis.FootprintDiagram(CookeTriplet(), num_rays=50)
    figure = plt.figure(figsize=(10, 4))
    try:
        footprint.view(fig_to_plot_on=figure)
        figure.tight_layout()
        figure.canvas.draw()
        ax = figure.axes[0]

        with caplog.at_level(logging.WARNING, logger="matplotlib"):
            # What a toolbar zoom rectangle does: fix both limits.
            ax.set_xlim(-2.0, 2.0)
            ax.set_ylim(-1.0, 1.0)
            figure.canvas.draw()

        assert not [r for r in caplog.records if "fixed" in r.getMessage()]
    finally:
        plt.close(figure)


def _assert_axes_fill_their_box_at_equal_scale(figure) -> None:  # noqa: ANN001
    for ax in figure.axes:
        given = ax.get_position(original=True)
        drawn = ax.get_position()
        assert (drawn.width, drawn.height) == pytest.approx((given.width, given.height))
        x0, x1 = ax.get_xlim()
        y0, y1 = ax.get_ylim()
        assert (x1 - x0) / ax.bbox.width == pytest.approx(
            (y1 - y0) / ax.bbox.height, rel=0.01
        )


def test_footprint_axes_fill_their_space_at_equal_scale() -> None:
    # The image footprint of the triplet is far narrower than it is tall.
    footprint = analysis.FootprintDiagram(CookeTriplet(), num_rays=50)
    figure = plt.figure(figsize=(8, 6))
    try:
        footprint.view(fig_to_plot_on=figure)
        figure.tight_layout()
        figure.canvas.draw()
        _assert_axes_fill_their_box_at_equal_scale(figure)

        # A toolbar zoom rectangle fixes both limits.
        figure.axes[0].set_xlim(-2.0, 2.0)
        figure.axes[0].set_ylim(-1.0, 1.0)
        figure.canvas.draw()
        _assert_axes_fill_their_box_at_equal_scale(figure)
    finally:
        plt.close(figure)


def test_spot_diagram_on_a_surface_takes_the_spots_there(set_test_backend) -> None:
    optic = CookeTriplet()
    stop = _stop_index(optic)

    at_stop = analysis.SpotDiagram(
        optic, wavelengths="primary", num_rings=4, surface_idx=stop
    )
    at_image = analysis.SpotDiagram(optic, wavelengths="primary", num_rings=4)

    # Field 0 is on axis: its chief ray crosses the stop centre.
    stop_rms = float(be.to_numpy(at_stop.rms_spot_radius()[0][0]))
    image_rms = float(be.to_numpy(at_image.rms_spot_radius()[0][0]))
    assert stop_rms > 1.0
    assert stop_rms > 20 * image_rms


def test_irradiance_on_an_intermediate_surface_bins_the_rays_recorded_there() -> None:
    optic = CookeTriplet()
    stop = _stop_index(optic)

    irradiance = analysis.IncoherentIrradiance(
        optic,
        num_rays=2000,
        res=(16, 16),
        detector_surface=stop,
        fields=[(0.0, 0.0)],
        wavelengths="primary",
    )

    irr_map, x_edges, _ = irradiance.data[0][0]
    irr_map = be.to_numpy(irr_map)
    # The on-axis beam fills the stop instead of piling up in the image spot.
    assert x_edges[-1] - x_edges[0] > 2.0
    assert irr_map[7:9, 7:9].sum() / irr_map.sum() < 0.5


_SURFACE_ANALYSES = {
    "footprint": lambda optic, surface: analysis.FootprintDiagram(
        optic, num_rays=20, surface_idx=surface
    ),
    "spot": lambda optic, surface: analysis.SpotDiagram(
        optic, num_rings=3, surface_idx=surface
    ),
    "irradiance": lambda optic, surface: analysis.IncoherentIrradiance(
        optic, num_rays=200, res=(8, 8), detector_surface=surface
    ),
    "pupil angle": lambda optic, surface: analysis.PupilIncidentAngleVsHeight(
        optic, surface_idx=surface, num_points=16
    ),
    "field angle": lambda optic, surface: analysis.FieldIncidentAngleVsHeight(
        optic, surface_idx=surface, num_points=16
    ),
}


@pytest.mark.parametrize(
    "make_analysis", _SURFACE_ANALYSES.values(), ids=_SURFACE_ANALYSES.keys()
)
def test_surface_analyses_name_their_surface_in_the_plot_title(make_analysis) -> None:
    optic = CookeTriplet()
    stop = _stop_index(optic)
    optic.surfaces[stop].comment = "Aperture stop"
    result = make_analysis(optic, stop)

    figure = plt.figure()
    try:
        result.view(fig_to_plot_on=figure)
        assert f"Surface {stop}: Aperture stop" in figure.get_suptitle()
    finally:
        plt.close(figure)
