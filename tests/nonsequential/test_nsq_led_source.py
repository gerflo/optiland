"""LED emitters: radiation patterns and the ring of discrete chips.

An LED ring illuminates through N separate chips, each emitting with the
radiation pattern of its datasheet. The fold builds either one
:class:`LEDRingSource` (discrete chips) or an annular
:class:`ExtendedSource`; both take an optional
:class:`~optiland.illumination.RadiationPattern`.

Kramer Harrison, 2026
"""

from __future__ import annotations

import math

import numpy as np
import pytest

import optiland.backend as be
from optiland.coordinate_system import CoordinateSystem
from optiland.illumination import RadiationPattern
from optiland.nonsequential import (
    ExtendedSourceConfig,
    LEDRingSource,
    LEDRingSourceConfig,
    NSQScene,
    Spectrum,
)
from optiland.nonsequential.ir.lower import lower
from optiland.nonsequential.rng import NSQRng
from optiland.nonsequential.serialization import scene_from_dict, scene_to_dict
from optiland.nonsequential.sources.extended import ExtendedSource

_COUNT = 12
_RADIUS = 3.25
_W = 1.2
_H = 1.0


@pytest.fixture(autouse=True)
def _numpy_backend():
    be.set_backend("numpy")
    yield
    be.set_backend("numpy")


def _ring_source(**kwargs) -> LEDRingSource:
    params = {
        "cs": CoordinateSystem(),
        "spectrum": Spectrum.monochromatic(0.53),
        "total_flux": 3.0,
        "count": _COUNT,
        "pitch_radius": _RADIUS,
        "chip_width": _W,
        "chip_height": _H,
    }
    params.update(kwargs)
    return LEDRingSource(**params)


def _cosine_table() -> RadiationPattern:
    angles = np.linspace(0.0, 90.0, 91)
    return RadiationPattern(
        "table", angles_deg=angles, intensities=np.cos(np.radians(angles))
    )


class TestExtendedSourcePattern:
    def test_cosine_table_gives_the_lambertian_rays(self):
        ids = np.arange(5000)
        common = {
            "cs": CoordinateSystem(),
            "spectrum": Spectrum.monochromatic(0.53),
            "aperture_radius": 2.0,
            "half_angle_deg": 25.0,
        }
        lambert = ExtendedSource(radiation=RadiationPattern(), **common)
        table = ExtendedSource(radiation=_cosine_table(), **common)
        a = lambert.generate(ids, NSQRng(seed=5))
        b = table.generate(ids, NSQRng(seed=5))
        assert np.allclose(a.x, b.x) and np.allclose(a.y, b.y)
        # Same random numbers, same directions up to the table's
        # interpolation error (see tests/test_illumination.py).
        assert np.allclose(a.N, b.N, atol=1e-4)

    def test_lambertian_pattern_matches_the_lambertian_cone(self):
        source = ExtendedSource(
            cs=CoordinateSystem(),
            spectrum=Spectrum.monochromatic(0.53),
            aperture_radius=2.0,
            half_angle_deg=25.0,
            radiation=RadiationPattern(),
        )
        bundle = source.generate(np.arange(40_000), NSQRng(seed=11))
        # Malley: sin^2(theta) uniform on [0, sin^2(theta_max)], as for
        # lambertian_cone (tests/nonsequential/test_nsq_annular_source.py).
        sin2 = 1.0 - bundle.N**2
        sin2_max = math.sin(math.radians(25.0)) ** 2
        assert sin2.max() <= sin2_max + 1e-12
        assert sin2.mean() == pytest.approx(0.5 * sin2_max, rel=0.02)
        hist, _ = np.histogram(sin2, bins=10, range=(0.0, sin2_max))
        assert hist.min() > 0.85 * hist.mean()

    def test_narrow_pattern_follows_its_cosine_power(self):
        pattern = RadiationPattern("half_angle", half_angle_deg=30.0)
        source = ExtendedSource(
            cs=CoordinateSystem(),
            spectrum=Spectrum.monochromatic(0.53),
            aperture_radius=1.0,
            radiation=pattern,
        )
        bundle = source.generate(np.arange(100_000), NSQRng(seed=2))
        m = pattern.cos_power
        assert bundle.N.mean() == pytest.approx((m + 1.0) / (m + 2.0), abs=3e-3)

    def test_no_pattern_keeps_the_old_rays(self):
        ids = np.arange(256)
        common = {
            "cs": CoordinateSystem(),
            "spectrum": Spectrum.monochromatic(0.53),
            "width": 2.0,
            "height": 1.0,
        }
        a = ExtendedSource(**common).generate(ids, NSQRng(seed=9))
        # Lambertian hemisphere: cos(theta) = sqrt(u) with u from SOURCE_U3.
        assert np.all(a.N > 0.0)
        assert a.N.mean() == pytest.approx(2.0 / 3.0, abs=0.03)


class TestLEDRingSource:
    def test_every_ray_leaves_its_chip(self):
        source = _ring_source(first_angle_deg=7.0)
        ids = np.arange(24_000)
        bundle = source.generate(ids, NSQRng(seed=4))
        phi = source.chip_azimuths(ids)
        radial = bundle.x * np.cos(phi) + bundle.y * np.sin(phi)
        tangential = -bundle.x * np.sin(phi) + bundle.y * np.cos(phi)
        assert np.all(np.abs(radial - _RADIUS) <= 0.5 * _H + 1e-12)
        assert np.all(np.abs(tangential) <= 0.5 * _W + 1e-12)
        assert np.all(bundle.z == 0.0)
        # The chips fill their rectangles uniformly.
        assert radial.mean() == pytest.approx(_RADIUS, abs=0.01)
        assert np.abs(tangential).mean() == pytest.approx(0.25 * _W, abs=0.01)

    def test_chips_share_the_flux_exactly(self):
        source = _ring_source()
        ids = np.arange(1200) + 17
        bundle = source.generate(ids, NSQRng(seed=1))
        counts = np.bincount(ids % _COUNT, minlength=_COUNT)
        assert np.all(counts == counts[0])
        assert bundle.flux.sum() == pytest.approx(3.0)

    def test_first_chip_sits_at_the_first_angle(self):
        source = _ring_source(first_angle_deg=30.0)
        bundle = source.generate(np.arange(0, 12_000, _COUNT), NSQRng(seed=3))
        azimuth = np.degrees(np.arctan2(bundle.y, bundle.x))
        assert np.median(azimuth) == pytest.approx(30.0, abs=0.5)

    def test_lambertian_inside_the_cone(self):
        source = _ring_source(half_angle_deg=20.0)
        bundle = source.generate(np.arange(60_000), NSQRng(seed=8))
        assert bundle.N.min() >= math.cos(math.radians(20.0)) - 1e-12
        sin2 = 1.0 - bundle.N**2
        sin2_max = math.sin(math.radians(20.0)) ** 2
        assert sin2.mean() == pytest.approx(0.5 * sin2_max, rel=0.02)

    def test_pattern_replaces_lambert(self):
        pattern = RadiationPattern("half_angle", half_angle_deg=25.0)
        source = _ring_source(radiation=pattern)
        bundle = source.generate(np.arange(100_000), NSQRng(seed=6))
        m = pattern.cos_power
        assert bundle.N.mean() == pytest.approx((m + 1.0) / (m + 2.0), abs=3e-3)

    def test_invalid_rings_are_refused(self):
        with pytest.raises(ValueError, match="count"):
            _ring_source(count=0)
        with pytest.raises(ValueError, match="chip sizes"):
            _ring_source(chip_width=0.0)


class TestSceneIntegration:
    def _scene(self):
        scene = NSQScene()
        scene.add_source(
            "ring",
            CoordinateSystem(z=2.0),
            LEDRingSourceConfig(
                spectrum=Spectrum(np.array([0.52, 0.53]), np.array([1.0, 2.0])),
                total_flux=2.0,
                count=_COUNT,
                pitch_radius=_RADIUS,
                chip_width=_W,
                chip_height=_H,
                first_angle_deg=5.0,
                half_angle_deg=40.0,
                radiation=RadiationPattern("half_angle", half_angle_deg=45.0),
            ),
        )
        scene.add_source(
            "annulus",
            CoordinateSystem(),
            ExtendedSourceConfig(
                spectrum=Spectrum.monochromatic(0.53),
                aperture_radius=3.75,
                inner_radius=2.75,
                half_angle_deg=40.0,
                radiation=_cosine_table(),
            ),
        )
        return scene

    def test_config_builds_the_sources(self):
        scene = self._scene()
        ring = scene.source_registry.get("ring")
        assert isinstance(ring, LEDRingSource)
        assert ring.count == _COUNT
        assert scene.source_registry.get("annulus").radiation == _cosine_table()

    def test_json_round_trip_emits_the_same_rays(self):
        scene = self._scene()
        restored = scene_from_dict(scene_to_dict(scene))
        for name in ("ring", "annulus"):
            original = scene.source_registry.get(name)
            copy = restored.source_registry.get(name)
            assert copy.radiation == original.radiation
            a = original.generate(np.arange(128), NSQRng(2))
            b = copy.generate(np.arange(128), NSQRng(2))
            assert np.allclose(a.x, b.x) and np.allclose(a.y, b.y)
            assert np.allclose(a.N, b.N)
            assert np.allclose(a.wavelength, b.wavelength)

    def test_lowering_names_the_ring_kind(self):
        emitters = {e.name: e for e in lower(self._scene()).emitters}
        assert emitters["ring"].kind == "led_ring"
        assert emitters["ring"].params["count"] == _COUNT
        assert emitters["ring"].params["radiation"]["kind"] == "half_angle"
        assert emitters["annulus"].params["radiation"]["kind"] == "table"
