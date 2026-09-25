"""Thickness edits keep the chain anchored where surface 1 lies (O13).

External exporters write the object at z = 0 and surface 1 at z = d > 0.
``OpticUpdater.set_thickness`` used to rebuild the chain from z = 0, which
moved every surface by -d and left the object in place: the object distance
dropped from d to 0 without a message.
"""

from __future__ import annotations

import optiland.backend as be
from optiland.optic import Optic
from tests.utils import assert_allclose

SHIFT = 0.237


def _shifted_optic() -> Optic:
    """Returns a singlet whose dict places the object at 0, surface 1 at SHIFT."""
    lens = Optic()
    lens.surfaces.add(index=0, thickness=SHIFT)
    lens.surfaces.add(index=1, radius=10.0, thickness=0.558, material="N-BK7")
    lens.surfaces.add(index=2, radius=-10.0, thickness=5.0, is_stop=True)
    lens.surfaces.add(index=3)
    lens.set_aperture(aperture_type="EPD", value=1.0)
    lens.fields.set_type(field_type="object_height")
    lens.fields.add(y=0.0)
    lens.wavelengths.add(value=0.55, is_primary=True)

    data = lens.to_dict()
    for surface_data in data["surface_group"]["surfaces"]:
        cs = surface_data["geometry"]["cs"]
        cs["z"] = float(cs["z"]) + SHIFT
    return Optic.from_dict(data)


def _z(optic: Optic) -> list[float]:
    return [float(be.to_numpy(s.geometry.cs.z)) for s in optic.surfaces]


def test_thickness_edit_keeps_object_distance(set_test_backend):
    """Re-entering a later thickness leaves every position unchanged (O13)."""
    optic = _shifted_optic()
    z_before = _z(optic)
    assert_allclose(z_before, [0.0, SHIFT, SHIFT + 0.558, SHIFT + 5.558])

    optic.updater.set_thickness(5.0, 2)

    assert_allclose(_z(optic), z_before)


def test_thickness_change_moves_only_downstream(set_test_backend):
    """A new thickness shifts the surfaces behind it, not the object gap (O13)."""
    optic = _shifted_optic()

    optic.updater.set_thickness(1.0, 1)

    assert_allclose(_z(optic), [0.0, SHIFT, SHIFT + 1.0, SHIFT + 6.0])


def test_object_thickness_measured_from_surface_1(set_test_backend):
    """The object distance is the gap to surface 1 wherever it lies (O13)."""
    optic = _shifted_optic()

    optic.updater.set_thickness(0.3, 0)

    z = _z(optic)
    assert_allclose(z[1] - z[0], 0.3)
    assert_allclose(z[1:], [SHIFT, SHIFT + 0.558, SHIFT + 5.558])
