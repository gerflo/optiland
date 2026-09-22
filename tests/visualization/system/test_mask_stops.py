"""Mask stops are drawn in red in the 2D and 3D layout, with their blocked zone.

A mask stop is a clear circle minus a centred disk or ring
(``DifferenceAperture(RadialAperture, RadialAperture)``). The 2D layout used
to draw it like any other aperture, a purple edge marker at its clear radius,
so the disk that blocks the light was nowhere to be seen; the 3D layout drew
only a purple ring beyond the clear radius.
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pytest
import vtk
from matplotlib.colors import same_color, to_rgb

import optiland.backend as be
from optiland.optic import Optic
from optiland.physical_apertures import (
    DifferenceAperture,
    OffsetRadialAperture,
    RadialAperture,
    RectangularAperture,
)
from optiland.visualization.system.system import (
    MASK_COLOR,
    MASK_LINE_WIDTH,
    STOP_COLOR,
    OpticalSystem,
    mask_zone,
)

CLEAR_RADIUS = 6.0
MASK_RADIUS = 2.0


def _mask(r_max: float = MASK_RADIUS, r_min: float = 0.0, clear: float = CLEAR_RADIUS):
    return DifferenceAperture(
        RadialAperture(r_max=clear, r_min=0.0), RadialAperture(r_max=r_max, r_min=r_min)
    )


def _optic(apertures: dict) -> Optic:
    """Stop, a singlet (surfaces 2-3), a bare air surface 4 and the image.

    Args:
        apertures: Physical aperture per surface index.
    """
    optic = Optic()
    optic.surfaces.add(index=0, radius=be.inf, thickness=be.inf)
    optic.surfaces.add(index=1, thickness=10.0, is_stop=True, aperture=apertures.get(1))
    optic.surfaces.add(
        index=2,
        radius=40.0,
        thickness=5.0,
        material="N-BK7",
        aperture=apertures.get(2),
    )
    optic.surfaces.add(index=3, radius=-40.0, thickness=20.0, aperture=apertures.get(3))
    optic.surfaces.add(index=4, thickness=20.0, aperture=apertures.get(4))
    optic.surfaces.add(index=5)
    optic.set_aperture(aperture_type="EPD", value=10.0)
    optic.fields.set_type("angle")
    optic.fields.add(y=0.0)
    optic.wavelengths.add(value=0.55, is_primary=True)
    return optic


class _Extents:
    """Stand-in for the ray plotter: the system plotter only reads extents."""

    def __init__(self, optic: Optic) -> None:
        self.r_extent = [5.0] * optic.surfaces.num_surfaces


def _plot_2d(optic: Optic, projection: str = "YZ", **kwargs):
    fig, ax = plt.subplots()
    artists = OpticalSystem(optic, _Extents(optic), projection="2d").plot(
        ax, projection=projection, **kwargs
    )
    return fig, ax, artists


def _lines_of_color(artists: dict, color: str) -> list:
    return [
        artist
        for artist in artists
        if hasattr(artist, "get_color") and same_color(artist.get_color(), color)
    ]


def _vertex_z(optic: Optic, index: int) -> float:
    return float(be.to_numpy(optic.surfaces.surfaces[index].geometry.cs.z))


def _sag(optic: Optic, index: int, y: float) -> float:
    geometry = optic.surfaces.surfaces[index].geometry
    return float(be.to_numpy(geometry.sag(be.array(0.0), be.array(y))))


# ---------------------------------------------------------------------------
# Which apertures are masks
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("aperture", "expected"),
    [
        (_mask(), (0.0, MASK_RADIUS)),
        (_mask(r_max=3.0, r_min=1.0), (1.0, 3.0)),
        (None, None),
        (RadialAperture(r_max=5.0), None),
        (RadialAperture(r_max=5.0, r_min=1.0), None),
        (
            DifferenceAperture(
                RadialAperture(r_max=5.0),
                RectangularAperture(x_min=-1, x_max=1, y_min=-1, y_max=1),
            ),
            None,
        ),
        (
            DifferenceAperture(
                RadialAperture(r_max=5.0),
                OffsetRadialAperture(r_max=1.0, offset_y=2.0),
            ),
            None,
        ),
        (
            DifferenceAperture(
                RadialAperture(r_max=5.0), OffsetRadialAperture(r_max=1.0)
            ),
            (0.0, 1.0),
        ),
    ],
)
def test_mask_zone_is_the_blocked_zone_of_centred_radial_masks_only(
    set_test_backend, aperture, expected
) -> None:
    assert mask_zone(aperture) == expected


# ---------------------------------------------------------------------------
# 2D layout
# ---------------------------------------------------------------------------


def test_2d_circular_mask_is_a_red_edge_and_a_red_bar_across_the_axis(
    set_test_backend,
) -> None:
    optic = _optic({4: _mask()})
    mask_surface = optic.surfaces.surfaces[4]

    fig, _, artists = _plot_2d(optic)

    red = _lines_of_color(artists, MASK_COLOR)
    assert len(red) == 2
    assert all(artists[line] is mask_surface for line in red)
    edge, body = sorted(red, key=lambda line: line.get_linewidth())
    np.testing.assert_allclose(sorted(edge.get_ydata()), [-CLEAR_RADIUS, CLEAR_RADIUS])
    assert body.get_linewidth() == MASK_LINE_WIDTH
    y = np.asarray(body.get_ydata(), dtype=float)
    np.testing.assert_allclose([y.min(), y.max()], [-MASK_RADIUS, MASK_RADIUS])
    np.testing.assert_allclose(body.get_xdata(), _vertex_z(optic, 4))
    # The stop keeps its own purple marker.
    stop_lines = _lines_of_color(artists, STOP_COLOR)
    assert [artists[line] for line in stop_lines] == [optic.surfaces.surfaces[1]]
    plt.close(fig)


@pytest.mark.parametrize("projection", ["YZ", "XZ"])
def test_2d_annular_mask_is_a_red_bar_on_either_side_of_the_axis(
    set_test_backend, projection
) -> None:
    optic = _optic({4: _mask(r_max=3.0, r_min=1.0)})

    fig, _, artists = _plot_2d(optic, projection=projection)

    bars = [
        line
        for line in _lines_of_color(artists, MASK_COLOR)
        if line.get_linewidth() == MASK_LINE_WIDTH
    ]
    spans = sorted(
        (float(np.min(line.get_ydata())), float(np.max(line.get_ydata())))
        for line in bars
    )
    np.testing.assert_allclose(spans, [(-3.0, -1.0), (1.0, 3.0)])
    plt.close(fig)


def test_2d_mask_bar_follows_the_curved_surface_it_sits_on(set_test_backend) -> None:
    r_mask = 3.0
    optic = _optic({2: _mask(r_max=r_mask, clear=8.0)})

    fig, _, artists = _plot_2d(optic)

    (body,) = [
        line
        for line in _lines_of_color(artists, MASK_COLOR)
        if line.get_linewidth() == MASK_LINE_WIDTH
    ]
    z = np.asarray(body.get_xdata(), dtype=float)
    y = np.asarray(body.get_ydata(), dtype=float)
    expected = [_vertex_z(optic, 2) + _sag(optic, 2, float(v)) for v in y]
    np.testing.assert_allclose(z, expected, atol=1e-9)
    # A straight chord would sit at the rim's sag on the axis too.
    assert z[len(z) // 2] == pytest.approx(_vertex_z(optic, 2), abs=1e-9)
    assert z.max() - z.min() == pytest.approx(_sag(optic, 2, r_mask), rel=1e-9)
    plt.close(fig)


def test_2d_mask_on_the_stop_keeps_the_purple_stop_edge(set_test_backend) -> None:
    optic = _optic({1: _mask()})

    fig, _, artists = _plot_2d(optic)

    red = _lines_of_color(artists, MASK_COLOR)
    assert [line.get_linewidth() for line in red] == [MASK_LINE_WIDTH]
    assert len(_lines_of_color(artists, STOP_COLOR)) == 1
    plt.close(fig)


@pytest.mark.parametrize(
    ("kwargs", "red_lines", "purple_lines"),
    [
        ({}, 2, 1),
        ({"show_apertures": False}, 0, 0),  # masks follow the apertures by default
        ({"show_apertures": False, "show_masks": True}, 2, 0),
        ({"show_apertures": True, "show_masks": False}, 0, 1),
    ],
)
def test_2d_masks_have_their_own_switch(
    set_test_backend, kwargs, red_lines, purple_lines
) -> None:
    optic = _optic({4: _mask()})

    fig, _, artists = _plot_2d(optic, **kwargs)

    assert len(_lines_of_color(artists, MASK_COLOR)) == red_lines
    assert len(_lines_of_color(artists, STOP_COLOR)) == purple_lines
    plt.close(fig)


# ---------------------------------------------------------------------------
# 3D layout
# ---------------------------------------------------------------------------


def _plot_3d(optic: Optic, **kwargs) -> dict:
    renderer = vtk.vtkRenderer()
    return OpticalSystem(optic, _Extents(optic), projection="3d").plot(
        renderer, **kwargs
    )


def _actors_of_color(actors: dict, color: str) -> list:
    rgb = np.asarray(to_rgb(color))
    return [
        actor
        for actor in actors
        if hasattr(actor, "GetProperty")
        and np.allclose(actor.GetProperty().GetColor(), rgb, atol=1e-6)
    ]


def _radial_extent(actor) -> float:
    x0, x1, y0, y1, _, _ = actor.GetBounds()
    return max(abs(x0), abs(x1), abs(y0), abs(y1))


def test_3d_circular_mask_is_a_red_disk_and_a_red_ring_beyond_the_clear_edge(
    set_test_backend,
) -> None:
    optic = _optic({4: _mask()})
    mask_surface = optic.surfaces.surfaces[4]

    actors = _plot_3d(optic)

    red = _actors_of_color(actors, MASK_COLOR)
    assert len(red) == 2
    assert all(actors[actor] is mask_surface for actor in red)
    disk, ring = sorted(red, key=_radial_extent)
    assert _radial_extent(disk) == pytest.approx(MASK_RADIUS, rel=1e-6)
    assert disk.GetProperty().GetOpacity() > 0.8  # a blocker reads opaque
    assert _radial_extent(ring) == pytest.approx(1.5 * CLEAR_RADIUS, rel=1e-6)
    _, _, _, _, z0, z1 = disk.GetBounds()
    assert z0 == pytest.approx(_vertex_z(optic, 4), abs=1e-6)
    assert z1 == pytest.approx(_vertex_z(optic, 4), abs=1e-6)


def test_3d_mask_disk_lies_on_the_curved_surface(set_test_backend) -> None:
    r_mask = 3.0
    optic = _optic({2: _mask(r_max=r_mask, clear=8.0)})

    actors = _plot_3d(optic)

    disk = min(_actors_of_color(actors, MASK_COLOR), key=_radial_extent)
    _, _, _, _, z0, z1 = disk.GetBounds()
    vertex = _vertex_z(optic, 2)
    assert z0 == pytest.approx(vertex, abs=1e-6)
    assert z1 == pytest.approx(vertex + _sag(optic, 2, r_mask), abs=1e-6)


def test_3d_annular_mask_disk_is_a_ring(set_test_backend) -> None:
    optic = _optic({4: _mask(r_max=3.0, r_min=1.0)})

    actors = _plot_3d(optic)

    disk = min(_actors_of_color(actors, MASK_COLOR), key=_radial_extent)
    points = disk.GetMapper().GetInput().GetPoints()
    radii = np.hypot(
        *np.array([points.GetPoint(i)[:2] for i in range(points.GetNumberOfPoints())]).T
    )
    np.testing.assert_allclose([radii.min(), radii.max()], [1.0, 3.0], rtol=1e-6)


@pytest.mark.parametrize(
    ("kwargs", "red_actors", "purple_actors"),
    [
        ({}, 2, 1),
        ({"show_apertures": False}, 0, 0),
        ({"show_apertures": False, "show_masks": True}, 2, 0),
        ({"show_masks": False}, 0, 1),
        # The mask no longer counts as one of the "other apertures".
        ({"show_non_stop_apertures": False}, 2, 1),
    ],
)
def test_3d_masks_have_their_own_switch(
    set_test_backend, kwargs, red_actors, purple_actors
) -> None:
    optic = _optic({4: _mask()})

    actors = _plot_3d(optic, **kwargs)

    assert len(_actors_of_color(actors, MASK_COLOR)) == red_actors
    assert len(_actors_of_color(actors, STOP_COLOR)) == purple_actors
