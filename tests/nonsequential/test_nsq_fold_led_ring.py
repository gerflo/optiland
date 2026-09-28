"""The fold builds its illumination emitter from the path's LED ring (O14).

Before, the emitter was the span of the illumination field radii. When the
fields are quadrature nodes inside the luminous ring (RCR07: 36 nodes at
r 2.811..3.734 in a ring r 2.65..3.85), the emitter came out too narrow
without a word, and its inner edge sets the dark core at the cornea. An
illumination optic that declares its LED ring
(:attr:`~optiland.optic.Optic.light_source`) now gets exactly that emitter:
its chips (or annulus), radiation pattern, spectrum and flux.

Kramer Harrison, 2026
"""

from __future__ import annotations

import math

import numpy as np
import pytest

import optiland.backend as be
from optiland.illumination import LEDRing, LEDSpectrum, LEDType, RadiationPattern
from optiland.nonsequential import LEDRingSource
from optiland.nonsequential.fold import ILLUMINATION, fold_paths
from optiland.nonsequential.sources.extended import ExtendedSource
from optiland.nonsequential.system import MultiAxisSystem, fold_system

from .test_nsq_fold_paths import (
    _FOLD_ILLUMINATION,
    _FOLD_IMAGING,
    illumination_optic,
    imaging_optic,
)

# The illumination fixture's fields sit at r = 3 and 4 mm, inside this
# ring's emitting zone r = 2.8 .. 4.2 (chip corners 4.23).
_W = 1.0
_H = 1.4
_PITCH = 7.0


@pytest.fixture(autouse=True)
def _numpy_backend():
    be.set_backend("numpy")
    yield
    be.set_backend("numpy")


def _ring(**kwargs) -> LEDRing:
    led_kwargs = kwargs.pop("led", {})
    led = LEDType(name="ring LED", chip_width=_W, chip_height=_H, **led_kwargs)
    return LEDRing(led=led, count=12, pitch_diameter=_PITCH, **kwargs)


def _fold_with(ring: LEDRing | None, **kwargs):
    illumination = illumination_optic()
    # Declared, not applied: the fields stay inside the ring, as in RCR07.
    illumination.light_source = ring
    return fold_paths(
        imaging_optic(), illumination, _FOLD_IMAGING, _FOLD_ILLUMINATION, **kwargs
    )


def _emitter(scene):
    return scene.source_registry.get(ILLUMINATION)


class TestDeclaredRing:
    def test_discrete_chips_become_the_emitter(self):
        scene, report = _fold_with(_ring(first_angle_deg=15.0))
        source = _emitter(scene)
        assert isinstance(source, LEDRingSource)
        assert source.count == 12
        assert float(source.pitch_radius) == pytest.approx(0.5 * _PITCH)
        assert float(source.chip_width) == pytest.approx(_W)
        assert float(source.chip_height) == pytest.approx(_H)
        assert float(source.first_angle_deg) == pytest.approx(15.0)
        assert any("LED ring" in note for note in report.notes)

    def test_annulus_spans_the_emitting_zone_not_the_fields(self):
        scene, _ = _fold_with(_ring(emitter_model="annulus"))
        source = _emitter(scene)
        assert isinstance(source, ExtendedSource)
        assert float(source.inner_radius) == pytest.approx(0.5 * _PITCH - 0.5 * _H)
        assert float(source.aperture_radius) == pytest.approx(0.5 * _PITCH + 0.5 * _H)

    def test_emitted_rays_leave_the_chips(self):
        scene, _ = _fold_with(_ring())
        source = _emitter(scene)
        from optiland.nonsequential.rng import NSQRng  # noqa: PLC0415

        bundle = source.generate(np.arange(6000), NSQRng(seed=1))
        # The emitter plane is the illumination object plane, turned onto
        # the -x arm; the ring lies across the arm's axis, in y and z.
        axis_point = np.array(
            [float(v) for v in source.cs.position_in_gcs], dtype=float
        )
        offsets = np.stack([bundle.x, bundle.y, bundle.z], axis=1) - axis_point
        radius = np.linalg.norm(offsets, axis=1)
        assert radius.min() >= 0.5 * _PITCH - 0.5 * _H - 1e-9
        assert radius.max() <= math.hypot(0.5 * _PITCH + 0.5 * _H, 0.5 * _W) + 1e-9
        # The chips reach beyond the fields at r = 3 and 4 mm on both sides.
        assert radius.min() < 2.9 and radius.max() > 4.1

    def test_pattern_and_spectrum_reach_the_emitter(self):
        pattern = RadiationPattern("half_angle", half_angle_deg=35.0)
        spectrum = LEDSpectrum("gaussian", center_um=0.53, fwhm_um=0.03)
        scene, _ = _fold_with(_ring(led={"radiation": pattern, "spectrum": spectrum}))
        source = _emitter(scene)
        assert source.radiation == pattern
        waves = np.asarray(source.spectrum.wavelengths)
        assert waves.size > 100
        assert waves.min() < 0.53 < waves.max()

    def test_central_wavelength_alone_is_monochromatic(self):
        scene, _ = _fold_with(_ring(led={"spectrum": LEDSpectrum(center_um=0.62)}))
        waves = np.asarray(_emitter(scene).spectrum.wavelengths)
        assert waves.tolist() == [0.62]

    def test_known_flux_is_emitted_inside_the_cone(self):
        pattern = RadiationPattern("half_angle", half_angle_deg=50.0)
        ring = _ring(led={"radiation": pattern, "flux": 0.05, "flux_unit": "W"})
        scene, _ = _fold_with(ring, illumination_half_angle_deg=30.0)
        expected = 12 * 0.05 * pattern.flux_fraction(30.0)
        assert float(_emitter(scene).total_flux) == pytest.approx(expected)

    def test_unknown_flux_keeps_the_normalised_flux(self):
        scene, _ = _fold_with(_ring(), illumination_flux=2.0)
        assert float(_emitter(scene).total_flux) == pytest.approx(2.0)


class TestWithoutRing:
    def test_field_span_is_still_the_fallback(self):
        scene, report = _fold_with(None)
        source = _emitter(scene)
        assert isinstance(source, ExtendedSource)
        assert float(source.inner_radius) == pytest.approx(3.0)
        assert float(source.aperture_radius) == pytest.approx(4.0)
        assert any("field" in note for note in report.notes)


class TestSystem:
    def test_the_ring_survives_the_system_file(self, tmp_path):
        illumination = illumination_optic()
        illumination.light_source = _ring()
        system, _ = fold_system(
            imaging_optic(), illumination, _FOLD_IMAGING, _FOLD_ILLUMINATION
        )
        path = tmp_path / "ring.olsys"
        system.to_json(path)
        back = MultiAxisSystem.from_json(path)
        back.rebuild()
        assert isinstance(back.scene.source_registry.get(ILLUMINATION), LEDRingSource)
