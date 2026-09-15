"""OpticalSystem.plot reports every 3D actor it adds and what that actor shows."""

from __future__ import annotations

import pytest
import vtk

import optiland.backend as be
from optiland.optic import Optic
from optiland.visualization.system.lens import Lens3D
from optiland.visualization.system.surface import Surface3D
from optiland.visualization.system.system import OpticalSystem


def _singlet() -> Optic:
    optic = Optic()
    optic.surfaces.add(index=0, radius=be.inf, thickness=be.inf)
    optic.surfaces.add(index=1, radius=50.0, thickness=5.0, material="N-BK7")
    optic.surfaces.add(index=2, radius=-50.0, thickness=45.0, is_stop=True)
    optic.surfaces.add(index=3, radius=be.inf, thickness=0.0)
    optic.set_aperture(aperture_type="EPD", value=10.0)
    optic.fields.set_type("angle")
    optic.fields.add(y=0.0)
    optic.wavelengths.add(value=0.55, is_primary=True)
    return optic


class _Extents:
    """Stand-in for the ray plotter: the system plotter only reads extents."""

    def __init__(self, extents) -> None:  # noqa: ANN001
        self.r_extent = list(extents)


def _renderer_actors(renderer) -> list:  # noqa: ANN001
    actors = renderer.GetActors()
    actors.InitTraversal()
    found = []
    while (actor := actors.GetNextActor()) is not None:
        found.append(actor)
    return found


def test_3d_plot_maps_every_added_actor_to_what_it_shows() -> None:
    optic = _singlet()
    renderer = vtk.vtkRenderer()

    actors = OpticalSystem(optic, _Extents([5.0] * 4), projection="3d").plot(renderer)

    added = _renderer_actors(renderer)
    assert added
    assert set(actors) == set(added)
    stop, image = optic.surfaces.surfaces[2], optic.surfaces.surfaces[3]
    kinds: set[str] = set()
    for target in actors.values():
        if isinstance(target, Lens3D):
            kinds.add("lens")
        elif isinstance(target, Surface3D) and target.surf is image:
            kinds.add("image")
        elif target is stop:
            kinds.add("stop aperture")
        else:
            pytest.fail(f"unexpected actor target {target!r}")
    assert kinds == {"lens", "image", "stop aperture"}


@pytest.mark.parametrize(
    ("extents", "lens_actor_count"),
    [
        # Two surfaces and the edge band between them.
        ([5.0, 5.0, 5.0, 5.0], 3),
        # The smaller back surface also gets an annulus out to the lens edge.
        ([5.0, 5.0, 3.0, 5.0], 4),
    ],
)
def test_3d_lens_drawn_surface_by_surface_reports_its_actors(
    monkeypatch, extents, lens_actor_count
) -> None:
    # Tilted or decentred lenses are not revolved from one contour but drawn
    # from their surfaces plus edge bands; force that path on a plain singlet.
    monkeypatch.setattr(Lens3D, "is_symmetric", property(lambda self: False))
    optic = _singlet()
    renderer = vtk.vtkRenderer()

    actors = OpticalSystem(optic, _Extents(extents), projection="3d").plot(
        renderer, show_apertures=False
    )

    assert set(actors) == set(_renderer_actors(renderer))
    lens_actors = [actor for actor, t in actors.items() if isinstance(t, Lens3D)]
    assert len(lens_actors) == lens_actor_count
