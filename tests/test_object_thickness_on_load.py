"""A loaded system keeps its object distance as the object thickness (O15).

``ObjectSurface`` does not serialize its thickness, so every system loaded
from a dict came back with ``surfaces[0].thickness == 0`` while the object
itself sat at the right z. Writers and reports that read the attribute
(CODE V ``SO``, OSLO ``TH``, the prescription) put the object on surface 1.
"""

from __future__ import annotations

import optiland.backend as be
from optiland.fileio import save_codev_file
from optiland.optic import Optic
from optiland.samples.objectives import CookeTriplet
from tests.utils import assert_allclose


def _finite_singlet(object_distance: float = 100.0) -> Optic:
    lens = Optic()
    lens.surfaces.add(index=0, thickness=object_distance)
    lens.surfaces.add(index=1, radius=50.0, thickness=5.0, material="N-BK7")
    lens.surfaces.add(index=2, radius=-50.0, thickness=45.0, is_stop=True)
    lens.surfaces.add(index=3)
    lens.set_aperture(aperture_type="EPD", value=10.0)
    lens.fields.set_type(field_type="object_height")
    lens.fields.add(y=0.0)
    lens.wavelengths.add(value=0.55, is_primary=True)
    return lens


def test_finite_object_thickness_survives_round_trip(set_test_backend):
    """The object thickness is the gap to surface 1 after loading (O15)."""
    loaded = Optic.from_dict(_finite_singlet().to_dict())

    assert_allclose(loaded.surfaces[0].thickness, 100.0)


def test_infinite_object_thickness_survives_round_trip(set_test_backend):
    """An object at infinity keeps an infinite thickness after loading (O15)."""
    loaded = Optic.from_dict(CookeTriplet().to_dict())

    assert be.isinf(be.array(loaded.surfaces[0].thickness))


def test_object_thickness_of_shifted_chain(set_test_backend):
    """Object at z = 0, surface 1 at z = 0.237: the thickness is 0.237 (O15)."""
    data = _finite_singlet(object_distance=0.237).to_dict()
    for surface_data in data["surface_group"]["surfaces"]:
        cs = surface_data["geometry"]["cs"]
        cs["z"] = float(cs["z"]) + 0.237

    loaded = Optic.from_dict(data)

    assert_allclose(loaded.surfaces[0].thickness, 0.237)


def test_codev_export_of_loaded_system_writes_object_distance(tmp_path):
    """CODE V gets the real object distance from a loaded system (O15)."""
    loaded = Optic.from_dict(_finite_singlet().to_dict())
    path = tmp_path / "loaded.seq"

    save_codev_file(loaded, str(path))

    so_lines = [
        line.split()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.startswith("SO")
    ]
    assert len(so_lines) == 1
    assert_allclose(float(so_lines[0][2]), 100.0)
