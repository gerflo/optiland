"""Inserting or removing surface 1 keeps the chain where it lies (O16).

``SurfaceGroup._update_coordinate_systems`` put the new surface 1 at z = 0.
On a chain whose surface 1 lies elsewhere (the object at z = 0 and surface 1
at z = 0.237, as external exporters write it) every surface moved while the
object stayed, so the object distance dropped to 0.
"""

from __future__ import annotations

from optiland.optic import Optic
from tests.test_set_thickness_anchor import SHIFT, _shifted_optic, _z
from tests.utils import assert_allclose


def test_insert_at_surface_1_keeps_object_distance(set_test_backend):
    """A surface inserted ahead of surface 1 takes its place (O16)."""
    optic = _shifted_optic()

    optic.surfaces.add(index=1, radius=100.0, thickness=0.1)

    assert_allclose(_z(optic), [0.0, SHIFT, SHIFT + 0.1, SHIFT + 0.658, SHIFT + 5.658])


def test_remove_surface_1_keeps_object_distance(set_test_backend):
    """The surface behind a removed surface 1 moves into its place (O16)."""
    optic = _shifted_optic()

    optic.surfaces.remove(1)

    assert_allclose(_z(optic), [0.0, SHIFT, SHIFT + 5.0])


def test_insert_at_surface_1_of_native_chain(set_test_backend):
    """A chain built with thicknesses keeps surface 1 at z = 0 (O16)."""
    optic = Optic()
    optic.surfaces.add(index=0, thickness=SHIFT)
    optic.surfaces.add(index=1, radius=10.0, thickness=0.558, material="N-BK7")
    optic.surfaces.add(index=2, radius=-10.0, thickness=5.0)
    optic.surfaces.add(index=3)

    optic.surfaces.add(index=1, radius=100.0, thickness=0.1)

    assert_allclose(_z(optic), [-SHIFT, 0.0, 0.1, 0.658, 5.658])
