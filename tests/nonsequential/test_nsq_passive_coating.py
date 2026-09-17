"""Passive constant-R/T coating model on NSQ interfaces.

Covers the construction-time checks (finite, non-negative, ``R + T <= 1``)
and the attached (differentiable) coating coefficients under Torch.

Kramer Harrison, 2026
"""

from __future__ import annotations

import math

import pytest

import optiland.backend as be
from optiland.coatings import SimpleCoating
from optiland.coordinate_system import CoordinateSystem
from optiland.nonsequential import VACUUM, ReflectiveComponent, RefractiveComponent
from optiland.nonsequential.components.coating_support import (
    validate_passive_coating,
    validate_reflectance,
)
from optiland.nonsequential.components.geometry.analytic.plane import (
    FinitePlaneGeometry,
)
from optiland.samples.nonsequential import SPLITTER_Z, beam_splitter_scene


def _plane() -> FinitePlaneGeometry:
    return FinitePlaneGeometry(aperture_radius=5.0)


class TestPassiveCoatingValidation:
    @pytest.mark.parametrize(
        ("reflectance", "transmittance"),
        [(0.0, 1.0), (1.0, 0.0), (0.5, 0.5), (0.4, 0.4), (0.0, 0.0)],
    )
    def test_valid_coefficients_are_accepted(self, reflectance, transmittance):
        coating = SimpleCoating(transmittance=transmittance, reflectance=reflectance)
        validate_passive_coating(coating, surface_name="s")
        RefractiveComponent(
            cs=CoordinateSystem(),
            geometry=_plane(),
            material_front=VACUUM,
            material_back=VACUUM,
            coating=coating,
        )

    @pytest.mark.parametrize(
        ("reflectance", "transmittance", "fragment"),
        [
            (0.6, 0.6, "passive coating needs"),
            (-0.1, 0.5, "non-negative"),
            (0.5, -0.1, "non-negative"),
            (math.nan, 0.5, "finite"),
            (0.5, math.inf, "finite"),
            (1.5, 0.0, "passive coating needs"),
        ],
    )
    def test_invalid_coefficients_raise_at_construction(
        self, reflectance, transmittance, fragment
    ):
        coating = SimpleCoating(transmittance=transmittance, reflectance=reflectance)
        with pytest.raises(ValueError, match=fragment):
            RefractiveComponent(
                cs=CoordinateSystem(),
                geometry=_plane(),
                material_front=VACUUM,
                material_back=VACUUM,
                coating=coating,
                name="splitter",
            )

    def test_error_names_the_surface(self):
        coating = SimpleCoating(transmittance=0.7, reflectance=0.7)
        with pytest.raises(ValueError, match="'splitter'"):
            validate_passive_coating(coating, surface_name="splitter")

    def test_rounding_slack_on_lossless_coating(self):
        reflectance = 0.1
        coating = SimpleCoating(
            transmittance=1.0 - reflectance, reflectance=reflectance
        )
        validate_passive_coating(coating, surface_name="s")

    def test_none_and_callables_are_left_alone(self):
        validate_passive_coating(None, surface_name="s")
        validate_reflectance(lambda wl: 0.5 * wl, surface_name="s")


class TestMirrorReflectanceValidation:
    @pytest.mark.parametrize("value", [0.0, 0.5, 1.0])
    def test_valid_constant(self, value):
        ReflectiveComponent(cs=CoordinateSystem(), geometry=_plane(), reflectance=value)

    @pytest.mark.parametrize("value", [-0.01, 1.01, math.nan, math.inf])
    def test_invalid_constant_raises(self, value):
        with pytest.raises(ValueError, match=r"\[0, 1\]"):
            ReflectiveComponent(
                cs=CoordinateSystem(), geometry=_plane(), reflectance=value
            )

    def test_coating_reflectance_is_checked_as_passive(self):
        with pytest.raises(ValueError, match="passive coating needs"):
            ReflectiveComponent(
                cs=CoordinateSystem(),
                geometry=_plane(),
                reflectance=SimpleCoating(transmittance=0.9, reflectance=0.9),
            )


@pytest.mark.skipif(
    "torch" not in be.list_available_backends(), reason="torch backend not available"
)
class TestAttachedCoatingCoefficients:
    def test_reflected_arm_flux_is_differentiable_in_reflectance(self):
        import torch

        be.set_backend("torch")
        be.set_device("cpu")
        be.set_precision("float64")
        be.grad_mode.enable()
        try:
            reflectance = torch.tensor(0.5, dtype=torch.float64, requires_grad=True)
            coating = SimpleCoating(
                transmittance=1.0 - reflectance, reflectance=reflectance
            )
            scene = beam_splitter_scene()
            scene.remove_component("splitter")
            scene.add_component(
                "splitter",
                RefractiveComponent(
                    cs=CoordinateSystem(z=SPLITTER_Z, ry=math.pi / 4),
                    geometry=_plane(),
                    material_front=VACUUM,
                    material_back=VACUUM,
                    coating=coating,
                    name="splitter",
                ),
            )
            num_rays = 256
            result = scene.trace(num_rays=num_rays, seed=3)
            reflected = result.detectors["reflected"]
            n_reflected = reflected.num_rays_hit
            assert 0 < n_reflected < num_rays

            reflected.total_flux.backward()

            # Single-branch roulette with detached p = R_det = 0.5: every ray
            # that took the reflect branch carries flux * R / p, so
            # d(P_reflected)/dR = n_reflected * (1 / num_rays) / p.
            expected = n_reflected / num_rays / 0.5
            assert reflectance.grad is not None
            assert float(reflectance.grad) == pytest.approx(expected, rel=1e-9)
        finally:
            be.grad_mode.disable()
            be.set_backend("numpy")
