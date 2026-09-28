"""LED ring light source of an illumination path (optiland.illumination).

The ring is described once -- LED type and arrangement -- and the
sequential path's fields and wavelengths are derived from it. These tests
pin the geometry (emitting area, field points), the radiation pattern and
the spectrum forms, including the cases where a datasheet gives only a
central wavelength and no radiation curve.

Kramer Harrison, 2026
"""

from __future__ import annotations

import math

import numpy as np
import pytest

import optiland.backend as be
from optiland.illumination import (
    LEDRing,
    LEDSpectrum,
    LEDType,
    RadiationPattern,
    apply_led_ring,
    light_source_from_dict,
)
from optiland.optic import Optic

from .utils import assert_allclose

_W = 1.2  # chip width (tangential) [mm]
_H = 1.0  # chip height (radial) [mm]
_PITCH = 6.5  # pitch diameter [mm]


def _led(**kwargs) -> LEDType:
    return LEDType(name="test LED", chip_width=_W, chip_height=_H, **kwargs)


def _ring(**kwargs) -> LEDRing:
    params = {"led": _led(), "count": 12, "pitch_diameter": _PITCH}
    params.update(kwargs)
    return LEDRing(**params)


def _illumination_optic() -> Optic:
    optic = Optic()
    optic.surfaces.add(index=0, thickness=10.0)
    optic.surfaces.add(index=1, thickness=20.0, is_stop=True)
    optic.surfaces.add(index=2)
    optic.set_aperture("EPD", 4.0)
    optic.fields.set_type("object_height")
    optic.fields.add(y=0.0)
    optic.wavelengths.add(value=0.8, is_primary=True)
    return optic


def _integrate(f, x):
    return float(np.sum(0.5 * np.diff(x) * (f[:-1] + f[1:])))


class TestRadiationPattern:
    def test_nothing_known_is_lambertian(self):
        pattern = RadiationPattern()
        assert pattern.kind == "lambertian"
        assert pattern.cos_power == 1.0
        assert pattern.flux_fraction(30.0) == pytest.approx(0.25)

    def test_half_angle_halves_the_intensity_there(self):
        pattern = RadiationPattern("half_angle", half_angle_deg=40.0)
        assert float(pattern.intensity(40.0)) == pytest.approx(0.5)
        assert float(pattern.intensity(0.0)) == pytest.approx(1.0)

    def test_sixty_degree_half_angle_is_lambertian(self):
        pattern = RadiationPattern("half_angle", half_angle_deg=60.0)
        assert pattern.cos_power == pytest.approx(1.0)

    def test_cosine_power_flux_fraction(self):
        pattern = RadiationPattern("half_angle", half_angle_deg=30.0)
        m = pattern.cos_power
        cone = 25.0
        expected = 1.0 - math.cos(math.radians(cone)) ** (m + 1.0)
        assert pattern.flux_fraction(cone) == pytest.approx(expected)
        assert pattern.flux_fraction(90.0) == pytest.approx(1.0)

    @pytest.mark.parametrize("cone", [90.0, 30.0])
    def test_cosine_table_reproduces_lambert(self, cone):
        angles = np.linspace(0.0, 90.0, 91)
        table = RadiationPattern(
            "table", angles_deg=angles, intensities=np.cos(np.radians(angles))
        )
        u = np.linspace(0.0, 0.999, 200)
        # Linear interpolation of cos over 1 deg steps errs by at most
        # (pi/180)^2 / 8 = 3.8e-5 in intensity.
        assert np.allclose(
            table.sample_cos_theta(u, cone),
            RadiationPattern().sample_cos_theta(u, cone),
            atol=1e-4,
        )
        assert table.flux_fraction(cone) == pytest.approx(
            RadiationPattern().flux_fraction(cone), abs=1e-4
        )

    def test_samples_follow_the_pattern_density(self):
        pattern = RadiationPattern("half_angle", half_angle_deg=35.0)
        m = pattern.cos_power
        cos_t = pattern.sample_cos_theta(np.random.default_rng(3).random(200_000), 90)
        # The density of cos(theta) is (m + 1) cos^m, so its mean is
        # (m + 1) / (m + 2).
        assert cos_t.mean() == pytest.approx((m + 1.0) / (m + 2.0), abs=2e-3)

    def test_table_emits_nothing_beyond_its_last_angle(self):
        pattern = RadiationPattern(
            "table", angles_deg=(0.0, 20.0, 40.0), intensities=(1.0, 0.8, 0.3)
        )
        cos_t = pattern.sample_cos_theta(np.linspace(0.0, 0.999, 500), 90.0)
        assert cos_t.min() >= math.cos(math.radians(40.0)) - 1e-12
        assert float(pattern.intensity(50.0)) == 0.0

    def test_round_trip(self):
        for pattern in (
            RadiationPattern(),
            RadiationPattern("half_angle", half_angle_deg=45.0),
            RadiationPattern("table", angles_deg=(0, 30, 60), intensities=(1, 1, 0)),
        ):
            assert RadiationPattern.from_dict(pattern.to_dict()) == pattern

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"kind": "spot"},
            {"kind": "half_angle"},
            {"kind": "half_angle", "half_angle_deg": 90.0},
            {"kind": "table", "angles_deg": (0.0,), "intensities": (1.0,)},
            {"kind": "table", "angles_deg": (0, 30, 20), "intensities": (1, 1, 1)},
            {"kind": "table", "angles_deg": (0, 95), "intensities": (1, 1)},
            {"kind": "table", "angles_deg": (0, 30), "intensities": (1, -1)},
            {"kind": "table", "angles_deg": (0, 30), "intensities": (0, 0)},
        ],
    )
    def test_invalid_patterns_are_refused(self, kwargs):
        with pytest.raises(ValueError):
            RadiationPattern(**kwargs)


class TestLEDSpectrum:
    def test_only_a_central_wavelength_is_known(self):
        spectrum = LEDSpectrum(center_um=0.63)
        assert spectrum.kind == "line"
        waves, weights = spectrum.density()
        assert list(waves) == [0.63] and list(weights) == [1.0]
        assert spectrum.representative_wavelengths(5) == ([0.63], 0)

    def test_gaussian_nodes_are_symmetric_about_the_centre(self):
        spectrum = LEDSpectrum("gaussian", center_um=0.53, fwhm_um=0.03)
        values, primary = spectrum.representative_wavelengths(5)
        assert primary == 2
        assert values[2] == pytest.approx(0.53, abs=1e-9)
        assert values[0] + values[4] == pytest.approx(2 * 0.53, abs=1e-9)
        assert values[0] > 0.53 - 0.03 * 2

    def test_gaussian_single_node_is_its_centre(self):
        spectrum = LEDSpectrum("gaussian", center_um=0.53, fwhm_um=0.03)
        values, primary = spectrum.representative_wavelengths(1)
        assert primary == 0
        assert values[0] == pytest.approx(0.53, abs=1e-9)

    def test_table_peak_and_equal_power_bands(self):
        waves = (0.50, 0.52, 0.54, 0.56)
        spectrum = LEDSpectrum("table", wavelengths_um=waves, powers=(0, 2, 1, 0))
        assert spectrum.peak_um == 0.52
        # Equal-power halves of a triangle-like curve: nodes inside the
        # curve, primary closest to the peak.
        values, primary = spectrum.representative_wavelengths(2)
        assert 0.50 < values[0] < values[1] < 0.56
        assert primary == int(np.argmin(np.abs(np.array(values) - 0.52)))

    def test_density_holds_the_table_shape(self):
        spectrum = LEDSpectrum(
            "table", wavelengths_um=(0.50, 0.55, 0.60), powers=(0.0, 1.0, 0.0)
        )
        waves, power = spectrum.density()
        assert waves[0] == 0.50 and waves[-1] == 0.60
        assert power[np.argmin(np.abs(waves - 0.55))] == pytest.approx(1.0)

    def test_round_trip(self):
        for spectrum in (
            LEDSpectrum(center_um=0.47),
            LEDSpectrum("gaussian", center_um=0.47, fwhm_um=0.02),
            LEDSpectrum("table", wavelengths_um=(0.4, 0.5), powers=(1.0, 0.5)),
        ):
            assert LEDSpectrum.from_dict(spectrum.to_dict()) == spectrum

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"kind": "led"},
            {"center_um": 0.05},
            {"kind": "gaussian", "center_um": 0.5},
            {"kind": "gaussian", "center_um": 0.5, "fwhm_um": 0.0},
            {"kind": "table", "wavelengths_um": (0.5, 0.4), "powers": (1, 1)},
            {"kind": "table", "wavelengths_um": (0.4, 0.5), "powers": (0, 0)},
        ],
    )
    def test_invalid_spectra_are_refused(self, kwargs):
        with pytest.raises(ValueError):
            LEDSpectrum(**kwargs)


class TestRingGeometry:
    def test_discrete_chips_cover_their_area(self):
        ring = _ring()
        r = np.linspace(ring.inner_radius, ring.outer_radius, 200_001)
        area = _integrate(ring.emitting_length(r), r)
        assert area == pytest.approx(12 * _W * _H, rel=1e-6)

    def test_annulus_covers_the_ring_area(self):
        ring = _ring(emitter_model="annulus")
        r = np.linspace(ring.inner_radius, ring.outer_radius, 200_001)
        area = _integrate(ring.emitting_length(r), r)
        assert area == pytest.approx(2.0 * math.pi * 0.5 * _PITCH * _H, rel=1e-6)

    def test_emitting_zone(self):
        radius = 0.5 * _PITCH
        ring = _ring()
        assert ring.inner_radius == pytest.approx(radius - 0.5 * _H)
        # The outer chip corners reach beyond the outer chip edge.
        assert ring.outer_radius == pytest.approx(
            math.hypot(radius + 0.5 * _H, 0.5 * _W)
        )
        assert _ring(emitter_model="annulus").outer_radius == pytest.approx(
            radius + 0.5 * _H
        )

    def test_azimuths_start_at_the_first_led(self):
        ring = _ring(count=4, first_angle_deg=10.0)
        assert ring.led_azimuths_deg() == [10.0, 100.0, 190.0, 280.0]

    @pytest.mark.parametrize(
        "kwargs, match",
        [
            ({"count": 0}, "at least one LED"),
            ({"pitch_diameter": 0.8}, "reach the axis"),
            ({"led": LEDType(chip_width=2.0, chip_height=_H)}, "overlap"),
            ({"emitter_model": "diffuse"}, "emitter model"),
            ({"field_count": 0}, "counts"),
        ],
    )
    def test_invalid_rings_are_refused(self, kwargs, match):
        with pytest.raises(ValueError, match=match):
            _ring(**kwargs)

    def test_invalid_led_types_are_refused(self):
        with pytest.raises(ValueError, match="width and height"):
            LEDType(chip_width=0.0)
        with pytest.raises(ValueError, match="flux"):
            LEDType(flux=-1.0)


class TestFieldPoints:
    def test_edges_and_nodes(self):
        ring = _ring(field_count=4)
        points = ring.field_points()
        assert len(points) == 6
        assert points[0] == (pytest.approx(ring.inner_radius, abs=5e-5), 0.0)
        assert points[-1] == (pytest.approx(ring.outer_radius, abs=5e-5), 0.0)
        # Heights are rounded to 0.1 um, so a tool that rounds them the same
        # way never normalizes a field to slightly more than 1.
        heights = [y for y, _ in points]
        assert heights == [round(y, 4) for y in heights]
        assert round(max(heights), 4) / max(heights) <= 1.0
        heights = [y for y, _ in points]
        assert heights == sorted(heights)
        assert all(weight == 1.0 for _, weight in points[1:-1])

    def test_without_edges(self):
        points = _ring(field_count=3, field_edges=False).field_points()
        assert len(points) == 3
        assert all(weight == 1.0 for _, weight in points)

    def test_annulus_nodes_are_equal_area_centroids(self):
        count = 4
        ring = _ring(emitter_model="annulus", field_count=count, field_edges=False)
        r_in, r_out = ring.inner_radius, ring.outer_radius
        edges = np.sqrt(r_in**2 + np.arange(count + 1) / count * (r_out**2 - r_in**2))
        expected = (2.0 / 3.0) * np.diff(edges**3) / np.diff(edges**2)
        heights = np.array([y for y, _ in ring.field_points()])
        assert np.allclose(heights, expected, atol=6e-5)

    def test_single_discrete_node_is_the_mean_chip_radius(self):
        ring = _ring(field_count=1, field_edges=False)
        ((height, _),) = ring.field_points()
        # Independent reference: mean distance from the axis over one chip,
        # midpoint rule on a 2000 x 2000 grid (error below 1e-8 mm).
        cells = (np.arange(2000) + 0.5) / 2000 - 0.5
        x = cells * _H + 0.5 * _PITCH
        y = cells * _W
        radius = np.hypot(*np.meshgrid(x, y))
        assert height == pytest.approx(radius.mean(), abs=6e-5)


class TestApplyToOptic:
    def test_fields_and_wavelengths_follow_the_ring(self, set_test_backend):
        optic = _illumination_optic()
        spectrum = LEDSpectrum("gaussian", center_um=0.53, fwhm_um=0.03)
        ring = _ring(led=_led(spectrum=spectrum), field_count=3, wavelength_count=3)
        apply_led_ring(optic, ring)

        assert optic.light_source is ring
        assert type(optic.fields.field_definition).__name__ == "ObjectHeightField"
        expected = ring.field_points()
        assert_allclose(optic.fields.y_fields, be.array([y for y, _ in expected]))
        assert optic.fields.weights == tuple(w for _, w in expected)
        assert optic.wavelengths.num_wavelengths == 3
        assert optic.wavelengths.primary_index == 1
        assert optic.primary_wavelength == pytest.approx(0.53, abs=1e-9)

    def test_central_wavelength_alone_gives_one_wavelength(self, set_test_backend):
        optic = _illumination_optic()
        apply_led_ring(optic, _ring(led=_led(spectrum=LEDSpectrum(center_um=0.62))))
        assert optic.wavelengths.get_wavelengths() == [0.62]
        assert optic.wavelengths.primary_index == 0

    def test_the_optic_traces_the_ring_fields(self, set_test_backend):
        optic = _illumination_optic()
        ring = _ring()
        apply_led_ring(optic, ring)
        rays = optic.trace(0.0, 1.0, optic.primary_wavelength, 3, "line_y")
        # The outermost field starts at the outer edge of the emitting zone.
        assert_allclose(optic.surfaces.y[0], ring.outer_radius)
        assert rays.y.shape[0] == 3

    def test_settings_can_be_kept(self, set_test_backend):
        optic = _illumination_optic()
        apply_led_ring(optic, _ring(), fields=False, wavelengths=False)
        assert optic.fields.num_fields == 1
        assert optic.wavelengths.get_wavelengths() == [0.8]

    def test_none_removes_the_source_only(self, set_test_backend):
        optic = _illumination_optic()
        apply_led_ring(optic, _ring())
        fields = optic.fields.num_fields
        apply_led_ring(optic, None)
        assert optic.light_source is None
        assert optic.fields.num_fields == fields

    def test_object_at_infinity_is_refused(self, set_test_backend):
        optic = Optic()
        optic.surfaces.add(index=0, thickness=math.inf)
        optic.surfaces.add(index=1, is_stop=True)
        optic.surfaces.add(index=2)
        with pytest.raises(ValueError, match="infinity"):
            apply_led_ring(optic, _ring())
        assert optic.light_source is None

    def test_serialization_round_trip(self, set_test_backend):
        optic = _illumination_optic()
        ring = _ring(
            led=_led(
                radiation=RadiationPattern("half_angle", half_angle_deg=50.0),
                spectrum=LEDSpectrum("gaussian", center_um=0.47, fwhm_um=0.025),
                flux=0.3,
                flux_unit="lm",
            ),
            first_angle_deg=15.0,
            emitter_model="annulus",
        )
        apply_led_ring(optic, ring)
        restored = Optic.from_dict(optic.to_dict())
        assert restored.light_source == ring

    def test_optic_without_source_writes_no_key(self, set_test_backend):
        data = _illumination_optic().to_dict()
        assert "light_source" not in data
        assert Optic.from_dict(data).light_source is None

    def test_unknown_source_type_is_refused(self):
        assert light_source_from_dict(None) is None
        with pytest.raises(ValueError, match="light source type"):
            light_source_from_dict({"type": "laser"})
