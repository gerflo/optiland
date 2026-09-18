"""Annular and cone-limited Lambertian extended sources.

An LED ring behind a diffuser is a ring-shaped Lambertian emitter; a
non-sequential trace of a relay that accepts only a narrow cone of it
wastes almost every ray unless the emitter can be restricted to that cone
without changing its angular distribution inside it.

Kramer Harrison, 2026
"""

from __future__ import annotations

import math

import numpy as np
import pytest

import optiland.backend as be
from optiland.coordinate_system import CoordinateSystem
from optiland.nonsequential import ExtendedSourceConfig, NSQScene, Spectrum
from optiland.nonsequential.rng import NSQRng
from optiland.nonsequential.serialization import scene_from_dict, scene_to_dict
from optiland.nonsequential.sources.extended import ExtendedSource


@pytest.fixture(autouse=True)
def _numpy_backend():
    be.set_backend("numpy")
    yield
    be.set_backend("numpy")


def _generate(**kwargs):
    source = ExtendedSource(
        cs=CoordinateSystem(), spectrum=Spectrum.monochromatic(0.53), **kwargs
    )
    return source.generate(np.arange(40_000), NSQRng(seed=11))


class TestAnnulus:
    def test_positions_fill_the_ring_uniformly_in_area(self):
        bundle = _generate(aperture_radius=3.0, inner_radius=2.0)
        r = np.hypot(bundle.x, bundle.y)
        assert r.min() >= 2.0 and r.max() <= 3.0
        # Uniform in area: r^2 is uniform on [4, 9], mean 6.5.
        assert (r**2).mean() == pytest.approx(6.5, abs=0.05)

    def test_inner_radius_needs_a_circular_aperture(self):
        with pytest.raises(ValueError, match="aperture_radius"):
            _generate(width=2.0, height=2.0, inner_radius=0.5)
        with pytest.raises(ValueError, match="inner_radius"):
            _generate(aperture_radius=1.0, inner_radius=1.0)


class TestLambertianCone:
    def test_directions_stay_inside_the_cone(self):
        bundle = _generate(
            aperture_radius=1.0, half_angle_deg=20.0, lambertian_cone=True
        )
        assert bundle.N.min() >= math.cos(math.radians(20.0)) - 1e-12

    def test_distribution_is_cosine_weighted_inside_the_cone(self):
        bundle = _generate(
            aperture_radius=1.0, half_angle_deg=20.0, lambertian_cone=True
        )
        # Malley: sin^2(theta) is uniform on [0, sin^2(theta_max)].
        sin2 = 1.0 - bundle.N**2
        sin2_max = math.sin(math.radians(20.0)) ** 2
        assert sin2.mean() == pytest.approx(0.5 * sin2_max, rel=0.02)
        hist, _ = np.histogram(sin2, bins=10, range=(0.0, sin2_max))
        assert hist.min() > 0.85 * hist.mean()

    def test_uniform_cone_is_unchanged_by_default(self):
        bundle = _generate(aperture_radius=1.0, half_angle_deg=20.0)
        # Uniform in solid angle: cos(theta) uniform on [cos(20 deg), 1].
        cos_max = math.cos(math.radians(20.0))
        assert bundle.N.mean() == pytest.approx(0.5 * (1.0 + cos_max), rel=0.01)


class TestSceneIntegration:
    def _scene(self):
        scene = NSQScene()
        scene.add_source(
            "ring",
            CoordinateSystem(),
            ExtendedSourceConfig(
                spectrum=Spectrum.monochromatic(0.53),
                total_flux=2.0,
                aperture_radius=3.0,
                inner_radius=2.0,
                half_angle_deg=15.0,
                lambertian_cone=True,
            ),
        )
        return scene

    def test_config_builds_the_source(self):
        source = self._scene().source_registry.get("ring")
        assert float(source.inner_radius) == pytest.approx(2.0)
        assert source.lambertian_cone is True

    def test_json_round_trip_keeps_ring_and_cone(self):
        restored = scene_from_dict(scene_to_dict(self._scene()))
        source = restored.source_registry.get("ring")
        assert float(source.aperture_radius) == pytest.approx(3.0)
        assert float(source.inner_radius) == pytest.approx(2.0)
        assert source.lambertian_cone is True
        assert float(source.half_angle_deg) == pytest.approx(15.0)
        a = self._scene().source_registry.get("ring").generate(np.arange(64), NSQRng(1))
        b = source.generate(np.arange(64), NSQRng(1))
        assert np.allclose(a.x, b.x) and np.allclose(a.N, b.N)
