"""O23: inserting in front of surface 1 keeps every surface where it lies.

Since O16 a surface added at index 1 takes the place of surface 1 and the
chain behind it moves by the new surface's thickness; since O15 a loaded
system knows its object distance. "Insert after" on the object row and
"Insert before" on surface 1 split the object gap, but the lens moved by
the part the new surface received (by the whole object distance with a gap
of 0), the object thickness no longer matched the positions, and with an
object at infinity "Insert after" raised ``ValueError: Coordinate system
update failed due to infinite thickness at surface 0``. Found by Optomal
(B255) in its parity fixtures of ``surfaces.insert``.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import optiland.backend as be
from optiland.optic import Optic
from optiland_gui.services.surface_service import SurfaceService


def _singlet(object_distance: float) -> Optic:
    optic = Optic()
    optic.surfaces.add(index=0, radius=be.inf, thickness=object_distance)
    optic.surfaces.add(index=1, radius=50.0, thickness=5.0, material="N-BK7")
    optic.surfaces.add(index=2, radius=-50.0, thickness=45.0, is_stop=True)
    optic.surfaces.add(index=3, radius=be.inf, thickness=0.0)
    optic.set_aperture(aperture_type="EPD", value=10.0)
    optic.fields.set_type("angle" if object_distance == be.inf else "object_height")
    optic.fields.add(y=0.0)
    optic.wavelengths.add(value=0.55, is_primary=True)
    optic.updater.update()
    return optic


def _system(object_distance: float, loaded: bool) -> Optic:
    optic = _singlet(object_distance)
    return Optic.from_dict(optic.to_dict()) if loaded else optic


def _service(optic: Optic) -> SurfaceService:
    connector = MagicMock()
    connector._optic = optic
    connector._capture_optic_state.return_value = {}
    return SurfaceService(connector)


def _z(optic: Optic) -> list[float]:
    return [
        float(be.atleast_1d(surface.geometry.cs.z).ravel()[0])
        for surface in optic.surfaces.surfaces
    ]


@pytest.mark.parametrize("loaded", [False, True], ids=["built", "loaded"])
class TestInsertInFrontOfSurfaceOne:
    @pytest.mark.parametrize("gap", [10.0, 0.0])
    def test_after_the_object_keeps_the_chain(self, loaded: bool, gap: float):
        optic = _system(60.0, loaded)
        z_before = _z(optic)

        _service(optic).insert_surface_after(0, "Air", gap)

        z_after = _z(optic)
        assert len(z_after) == len(z_before) + 1
        # The object and every old surface keep their z.
        assert z_after[0] == pytest.approx(z_before[0])
        assert z_after[2:] == pytest.approx(z_before[1:])
        # The new surface lies `gap` behind the object ...
        assert z_after[1] == pytest.approx(z_before[0] + gap)
        # ... and the thicknesses are the gaps between the positions.
        surfaces = optic.surfaces.surfaces
        assert float(surfaces[0].thickness) == pytest.approx(gap)
        assert float(surfaces[1].thickness) == pytest.approx(60.0 - gap)

    def test_after_an_object_at_infinity_inserts(self, loaded: bool):
        optic = _system(be.inf, loaded)
        z_before = _z(optic)

        _service(optic).insert_surface_after(0, "Air", 10.0)

        z_after = _z(optic)
        assert len(z_after) == len(z_before) + 1
        assert z_after[2:] == pytest.approx(z_before[1:])
        # The object stays at infinity; the new surface lies in front of
        # surface 1, where it was.
        surfaces = optic.surfaces.surfaces
        assert be.isinf(be.array(surfaces[0].thickness))
        assert z_after[1] == pytest.approx(z_before[1])
        assert float(surfaces[1].thickness) == pytest.approx(0.0)

    @pytest.mark.parametrize(
        "object_distance", [60.0, be.inf], ids=["finite", "infinite"]
    )
    def test_before_surface_one_keeps_the_chain(
        self, loaded: bool, object_distance: float
    ):
        optic = _system(object_distance, loaded)
        z_before = _z(optic)

        _service(optic).insert_surface_before(1, None, 10.0)

        z_after = _z(optic)
        assert len(z_after) == len(z_before) + 1
        assert z_after[2:] == pytest.approx(z_before[1:])
        # The new surface lies 10 mm in front of the old surface 1.
        assert z_after[1] == pytest.approx(z_before[1] - 10.0)
        surfaces = optic.surfaces.surfaces
        assert float(surfaces[1].thickness) == pytest.approx(10.0)
        if object_distance == be.inf:
            assert be.isinf(be.array(surfaces[0].thickness))
        else:
            assert z_after[0] == pytest.approx(z_before[0])
            assert float(surfaces[0].thickness) == pytest.approx(50.0)
