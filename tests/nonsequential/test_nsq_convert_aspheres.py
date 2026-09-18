"""The grouped converter carries even-asphere coefficients into the scene.

Before this, ``sequential_to_nonsequential`` read only radius and conic of
an ``EvenAsphere`` surface and silently traced the base conic.

Kramer Harrison, 2026
"""

from __future__ import annotations

import numpy as np
import pytest

import optiland.backend as be
from optiland.nonsequential import EvenAsphereGeometry
from optiland.nonsequential.convert import ConversionError, sequential_to_nonsequential
from optiland.optic import Optic

_COEFFICIENTS = [0.0, -2e-5, 3e-8]


@pytest.fixture(autouse=True)
def _numpy_backend():
    be.set_backend("numpy")
    yield
    be.set_backend("numpy")


def _aspheric_singlet(coefficients) -> Optic:
    optic = Optic()
    optic.add_surface(index=0, thickness=float("inf"))
    optic.add_surface(
        index=1,
        radius=20.0,
        thickness=5.0,
        material="N-BK7",
        is_stop=True,
        surface_type="even_asphere",
        conic=-0.8,
        coefficients=coefficients,
    )
    optic.add_surface(index=2, radius=-40.0, thickness=30.0)
    optic.add_surface(index=3)
    optic.set_aperture(aperture_type="EPD", value=10.0)
    optic.set_field_type(field_type="angle")
    optic.add_field(y=0.0)
    optic.add_wavelength(value=0.55, is_primary=True)
    return optic


def test_singlet_front_face_becomes_an_asphere():
    with pytest.warns(UserWarning):
        scene = sequential_to_nonsequential(_aspheric_singlet(_COEFFICIENTS))
    lens = scene.component_registry.get("L1")
    front = lens.surfaces[0]
    assert isinstance(front.geometry, EvenAsphereGeometry)
    got = [float(np.ravel(be.to_numpy(c))[0]) for c in front.geometry.coefficients]
    assert got == pytest.approx(_COEFFICIENTS)
    assert float(be.to_numpy(front.geometry.conic)) == pytest.approx(-0.8)
    assert list(lens._config.coefficients1) == pytest.approx(_COEFFICIENTS)


def test_all_zero_coefficients_stay_a_conic():
    with pytest.warns(UserWarning):
        scene = sequential_to_nonsequential(_aspheric_singlet([0.0, 0.0]))
    front = scene.component_registry.get("L1").surfaces[0]
    assert not isinstance(front.geometry, EvenAsphereGeometry)


def test_coefficients_change_the_converted_trace():
    with pytest.warns(UserWarning):
        aspheric = sequential_to_nonsequential(_aspheric_singlet(_COEFFICIENTS))
        conic = sequential_to_nonsequential(_aspheric_singlet([]))
    a = aspheric.trace(num_rays=2000, seed=1).detectors["D1"]
    b = conic.trace(num_rays=2000, seed=1).detectors["D1"]
    assert a.num_rays_hit != b.num_rays_hit


def test_aspheric_doublet_face_is_rejected_not_dropped():
    optic = Optic()
    optic.add_surface(index=0, thickness=float("inf"))
    optic.add_surface(
        index=1,
        radius=60.0,
        thickness=6.0,
        material="N-BK7",
        is_stop=True,
        surface_type="even_asphere",
        coefficients=[0.0, 1e-6],
    )
    optic.add_surface(index=2, radius=-30.0, thickness=2.0, material="N-F2")
    optic.add_surface(index=3, radius=-80.0, thickness=50.0)
    optic.add_surface(index=4)
    optic.set_aperture(aperture_type="EPD", value=10.0)
    optic.set_field_type(field_type="angle")
    optic.add_field(y=0.0)
    optic.add_wavelength(value=0.55, is_primary=True)
    with pytest.raises(ConversionError, match="aspheric face"):
        sequential_to_nonsequential(optic)
