"""Media seen by a ``SurfaceView`` in both traversal directions and on
repeated visits, and the physics of a polarized coating on a reflected step.

Regression background: a reflected view collapses ``material_post`` to
``material_pre`` (the reflected ray keeps travelling in the incident
medium). ``FresnelCoating``/``ThinFilmCoating`` used to be rebound to that
collapsed pair, i.e. to identical media on both sides, so a Fresnel
reflection inside a glass plate carried zero intensity.

Kramer Harrison, 2026
"""

from __future__ import annotations

import numpy as np
import pytest

import optiland.backend as be
from optiland.coatings import FresnelCoating
from optiland.coordinate_system import CoordinateSystem
from optiland.geometries.plane import Plane
from optiland.materials.ideal import IdealMaterial
from optiland.rays.polarization_state import PolarizationState
from optiland.rays.polarized_rays import PolarizedRays
from optiland.sequences.resolver import resolve_sequence
from optiland.surfaces.standard_surface import Surface

AIR = IdealMaterial(n=1.0)
GLASS = IdealMaterial(n=1.5)

# Normal-incidence Fresnel reflectance of an n=1.0 / n=1.5 interface.
R_NORMAL = ((1.5 - 1.0) / (1.5 + 1.0)) ** 2


def _plane_surface(previous, material_post, z):
    return Surface(
        previous_surface=previous,
        material_post=material_post,
        geometry=Plane(CoordinateSystem(z=z)),
    )


def _plate():
    """Object-side air, a glass plate between z=1 and z=2, air behind."""
    s0 = _plane_surface(None, AIR, 0.0)
    s1 = _plane_surface(s0, GLASS, 1.0)
    s2 = _plane_surface(s1, AIR, 2.0)
    return [s0, s1, s2]


def _normal_rays(n: int = 3) -> PolarizedRays:
    zeros = be.zeros(n)
    return PolarizedRays(
        x=be.array(np.linspace(-0.5, 0.5, n)),
        y=zeros,
        z=zeros,
        L=zeros,
        M=zeros,
        N=be.ones(n),
        intensity=be.ones(n),
        wavelength=0.55,
    )


class TestMediaPerVisit:
    def test_forward_and_reverse_visits_of_the_same_surface(self, set_test_backend):
        views = resolve_sequence(_plate(), [1, (2, "reflect"), (1, "reflect"), 2])

        first_face, back_face, first_face_again, back_face_again = views

        # Forward through the front face: air -> glass.
        assert first_face.reverse is False
        assert first_face.material_pre is AIR
        assert first_face.material_post is GLASS
        assert first_face.interface_materials == (AIR, GLASS)

        # Reflected at the back face from inside: arrives in glass, stays
        # in glass, but the interface it reflects off is glass/air.
        assert back_face.reverse is False
        assert back_face.material_pre is GLASS
        assert back_face.material_post is GLASS
        assert back_face.interface_materials == (GLASS, AIR)

        # Second visit of the front face, now travelling backwards inside
        # the glass and reflecting: the interface seen is glass/air again.
        assert first_face_again.reverse is True
        assert first_face_again.material_pre is GLASS
        assert first_face_again.material_post is GLASS
        assert first_face_again.interface_materials == (GLASS, AIR)

        # Forward exit through the back face: glass -> air.
        assert back_face_again.reverse is False
        assert back_face_again.material_pre is GLASS
        assert back_face_again.material_post is AIR
        assert back_face_again.interface_materials == (GLASS, AIR)

    def test_repeated_visits_keep_separate_records(self, set_test_backend):
        surfaces = _plate()
        views = resolve_sequence(surfaces, [1, (2, "reflect"), (1, "reflect"), 2])
        rays = _normal_rays()
        for view in views:
            rays = view.trace(rays)

        z_per_visit = [float(be.to_numpy(view.z)[0]) for view in views]
        assert z_per_visit == pytest.approx([1.0, 2.0, 1.0, 2.0])
        assert views[0] is not views[2]
        assert views[0].base_surface is views[2].base_surface
        # The base surface's own record is untouched by the views.
        assert be.size(surfaces[1].z) == 0


class TestFresnelCoatingOnReflectedStep:
    def test_internal_reflection_carries_the_fresnel_reflectance(
        self, set_test_backend
    ):
        surfaces = _plate()
        surfaces[2].interaction_model.coating = FresnelCoating(GLASS, AIR)
        views = resolve_sequence(surfaces, [1, (2, "reflect")])

        rays = _normal_rays()
        for view in views:
            rays = view.trace(rays)
        rays.update_intensity(PolarizationState(is_polarized=False))

        np.testing.assert_allclose(be.to_numpy(rays.N), -1.0, atol=1e-12)
        np.testing.assert_allclose(be.to_numpy(rays.i), R_NORMAL, rtol=1e-9)

    def test_forward_view_transmits_like_the_base_surface(self, set_test_backend):
        surfaces = _plate()
        surfaces[1].interaction_model.coating = FresnelCoating(AIR, GLASS)
        views = resolve_sequence(surfaces, [1])

        view_rays = views[0].trace(_normal_rays())
        view_rays.update_intensity(PolarizationState(is_polarized=False))
        nominal_rays = surfaces[1].trace(_normal_rays())
        nominal_rays.update_intensity(PolarizationState(is_polarized=False))

        np.testing.assert_allclose(
            be.to_numpy(view_rays.i), be.to_numpy(nominal_rays.i), rtol=1e-12
        )
        assert float(be.to_numpy(view_rays.i)[0]) < 1.0

    def test_ghost_round_trip_intensity(self, set_test_backend):
        """Front face transmit, back face reflect, front face reflect, back
        face transmit: T * R * R * T at normal incidence."""
        surfaces = _plate()
        surfaces[1].interaction_model.coating = FresnelCoating(AIR, GLASS)
        surfaces[2].interaction_model.coating = FresnelCoating(GLASS, AIR)
        views = resolve_sequence(surfaces, [1, (2, "reflect"), (1, "reflect"), 2])

        rays = _normal_rays()
        for view in views:
            rays = view.trace(rays)
        rays.update_intensity(PolarizationState(is_polarized=False))

        expected = (1.0 - R_NORMAL) ** 2 * R_NORMAL**2
        np.testing.assert_allclose(be.to_numpy(rays.i), expected, rtol=1e-9)
        np.testing.assert_allclose(be.to_numpy(rays.N), 1.0, atol=1e-12)
