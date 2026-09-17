"""Rendering of raw surfaces and sources in the NSQ viewers.

A beam-splitter plate added via ``NSQScene.add_component`` used to be
invisible in ``NSQViewer2D``/``NSQViewer3D`` (only Lens, Mirror and Doublet
had renderers), and sources were never drawn at all.

Kramer Harrison, 2026
"""

from __future__ import annotations

import math

import numpy as np
import pytest

matplotlib = pytest.importorskip("matplotlib")
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

import optiland.backend as be  # noqa: E402
from optiland.coordinate_system import CoordinateSystem  # noqa: E402
from optiland.nonsequential import (  # noqa: E402
    ConicGeometry,
    ReflectiveComponent,
)
from optiland.nonsequential.visualization import NSQViewer2D  # noqa: E402
from optiland.samples.nonsequential import (  # noqa: E402
    SPLITTER_Z,
    beam_splitter_scene,
    side_illumination_transmission_scene,
)


@pytest.fixture(autouse=True)
def _numpy_backend():
    be.set_backend("numpy")
    yield
    plt.close("all")
    be.set_backend("numpy")


def _labelled_lines(ax) -> dict[str, list]:
    lines: dict[str, list] = {}
    for line in ax.get_lines():
        label = line.get_label()
        if label and not label.startswith("_"):
            lines.setdefault(label, []).append(line)
    return lines


class TestSurfaceRenderer2D:
    def test_splitter_plate_is_drawn_where_it_sits(self):
        scene = beam_splitter_scene(splitter_radius=5.0)
        fig, ax = NSQViewer2D(scene).view(num_rays=0, projection="XZ")

        (line,) = _labelled_lines(ax)["splitter"]
        h, v = line.get_xdata(), line.get_ydata()  # (z, x) in the XZ projection
        # Edge-on: the plate is the segment x = 10 - z, |x| <= 5 sin 45.
        np.testing.assert_allclose(np.asarray(h) + np.asarray(v), SPLITTER_Z, atol=1e-9)
        assert np.max(np.abs(v)) == pytest.approx(5.0 * math.sin(math.pi / 4), rel=1e-6)

    def test_yz_projection_shows_the_tilted_disk_as_an_ellipse(self):
        scene = beam_splitter_scene(splitter_radius=5.0)
        fig, ax = NSQViewer2D(scene).view(num_rays=0, projection="YZ")
        (line,) = _labelled_lines(ax)["splitter"]
        h, v = np.asarray(line.get_xdata()), np.asarray(line.get_ydata())
        assert np.max(np.abs(v)) == pytest.approx(5.0, rel=1e-6)
        assert np.max(np.abs(h - SPLITTER_Z)) == pytest.approx(
            5.0 * math.sin(math.pi / 4), rel=1e-6
        )

    def test_conic_surface_is_drawn_as_its_sag_profile(self):
        scene = beam_splitter_scene()
        scene.add_component(
            "concave",
            ReflectiveComponent(
                cs=CoordinateSystem(z=40.0),
                geometry=ConicGeometry(radius=-50.0, conic=0.0, aperture_radius=6.0),
                reflectance=1.0,
            ),
        )
        fig, ax = NSQViewer2D(scene).view(num_rays=0)
        (line,) = _labelled_lines(ax)["concave"]
        h, v = np.asarray(line.get_xdata()), np.asarray(line.get_ydata())
        assert np.max(np.abs(v)) == pytest.approx(6.0)
        # Concave towards -z: the edge lies in front of the vertex, the
        # profile touches the vertex plane at the axis.
        assert h[0] < 40.0
        assert np.max(h) == pytest.approx(40.0, abs=1e-3)
        assert np.min(h) == pytest.approx(40.0 - 6.0**2 / (2 * 50.0), rel=1e-2)

    def test_every_source_and_detector_appears(self):
        scene = side_illumination_transmission_scene()
        fig, ax = NSQViewer2D(scene).view(num_rays=0, projection="XZ")
        labels = _labelled_lines(ax)
        assert {"illumination", "object", "splitter"} <= set(labels)
        # Two detectors are drawn as dashed rectangles; count the dashed lines.
        dashed = [ln for ln in ax.get_lines() if ln.get_linestyle() == "--"]
        assert len(dashed) == len(scene.detectors)

    def test_rays_overlay_still_works_with_the_new_renderers(self):
        scene = beam_splitter_scene()
        result = scene.trace(num_rays=100, seed=1, record_paths=True)
        fig, ax = NSQViewer2D(scene).view(result, num_rays=20, projection="XZ")
        assert len(ax.get_lines()) > 20


@pytest.mark.skipif(
    pytest.importorskip("importlib.util").find_spec("vtk") is None,
    reason="vtk not installed",
)
class TestSurfaceRenderer3D:
    def test_actors_are_added_for_surfaces_and_sources(self):
        import vtk

        from optiland.nonsequential.components import SingleSurfaceCompound
        from optiland.nonsequential.visualization.renderers.source import (
            SourceRenderer3D,
        )
        from optiland.nonsequential.visualization.renderers.surface import (
            SurfaceRenderer3D,
        )

        scene = side_illumination_transmission_scene()
        renderer = vtk.vtkRenderer()
        for compound in scene.component_registry.compounds:
            if isinstance(compound, SingleSurfaceCompound):
                SurfaceRenderer3D().render(compound, renderer)
        for source in scene.sources:
            SourceRenderer3D().render(source, renderer, scene=scene)
        assert renderer.GetActors().GetNumberOfItems() == 1 + len(scene.sources)
