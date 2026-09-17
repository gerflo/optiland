"""Beam-splitter reference scene: one collimated source, a 45 deg 50:50
plate splitter and one detector per arm.

Regression background: under the Torch backend at float32 precision, rays
that had just left the splitter re-hit it (up to 12 times each) because the
self-intersection guard was a fixed 1e-9 mm while the float32 rounding
residual of a position near 10 mm is about 1e-6 mm. The detector split then
came out 0.404 / 0.596 instead of 0.5 / 0.5 while the total flux still
summed to 1 W, so an energy-conservation check alone did not catch it.
The guard is now scale- and dtype-aware
(``optiland.nonsequential._utils.self_intersection_offset``).

Kramer Harrison, 2026
"""

from __future__ import annotations

import math

import numpy as np
import pytest

import optiland.backend as be
from optiland.coatings import SimpleCoating
from optiland.coordinate_system import CoordinateSystem
from optiland.nonsequential import VACUUM, RefractiveComponent
from optiland.nonsequential._utils import (
    SELF_HIT_EPSILON_ABS,
    float_eps,
    self_intersection_offset,
)
from optiland.nonsequential.components.geometry.analytic.plane import (
    FinitePlaneGeometry,
)
from optiland.nonsequential.ir.scene_ir import SamplingPolicy
from optiland.nonsequential.ray_bundle import NSQRayBundle
from optiland.samples.nonsequential import SPLITTER_Z, beam_splitter_scene

NUM_RAYS = 2048
SEED = 7

_PRECISION_CASES = [
    ("numpy", "float64"),
    ("torch", "float64"),
    ("torch", "float32"),
]


@pytest.fixture(params=_PRECISION_CASES, ids=lambda c: f"{c[0]}-{c[1]}")
def backend_precision(request):
    """Like ``set_test_backend`` but also covers Torch at float32.

    The shared fixture always selects float64 for Torch, which is exactly
    why the float32 self-hit went unnoticed.
    """
    backend, precision = request.param
    if backend not in be.list_available_backends():
        pytest.skip(f"{backend} backend not available")
    be.set_backend(backend)
    if backend == "torch":
        be.set_device("cpu")
        be.set_precision(precision)
    yield backend, precision
    if backend == "torch":
        be.set_precision("float64")
    be.set_backend("numpy")


def _splitter_hits_per_ray(result) -> np.ndarray:
    events = result.ray_paths["events"]
    hits = events[
        (events["component_name"] == "splitter") & (events["event_type"] == "hit")
    ]
    _, counts = np.unique(hits["ray_id"], return_counts=True)
    return counts


class TestSelfIntersectionOffset:
    def test_float64_keeps_the_absolute_floor(self):
        be.set_backend("numpy")
        positions = np.array([[0.0, 0.0, 10.0], [3.0, -2.0, 9.0]])
        offset = be.to_numpy(self_intersection_offset(positions, np.zeros(3)))
        np.testing.assert_allclose(offset, SELF_HIT_EPSILON_ABS)

    def test_float32_scales_with_position_magnitude(self):
        be.set_backend("numpy")
        positions = np.array([[0.0, 0.0, 10.0], [0.0, 0.0, 1000.0]], dtype=np.float32)
        offset = be.to_numpy(self_intersection_offset(positions, np.zeros(3)))
        eps32 = float_eps(positions)
        assert eps32 == pytest.approx(2.0**-23)
        # Larger than the float32 rounding residual at each scale ...
        assert offset[0] > 10.0 * eps32
        assert offset[1] > 1000.0 * eps32
        # ... and grows with the coordinate magnitude.
        assert offset[1] > offset[0]
        # ... but is still far below any optical feature size at that scale.
        assert offset[1] < 1e-2

    def test_translation_contributes_to_the_scale(self):
        be.set_backend("numpy")
        positions = np.zeros((2, 3), dtype=np.float32)
        near = be.to_numpy(self_intersection_offset(positions, np.zeros(3)))
        far = be.to_numpy(self_intersection_offset(positions, np.array([0, 0, 500.0])))
        assert np.all(far > near)


def _bundle_on_splitter(x_values: np.ndarray, direction: tuple) -> NSQRayBundle:
    """Rays sitting exactly on the tilted splitter plane, in the current dtype."""
    n = len(x_values)
    # Plane through (0, 0, SPLITTER_Z) with normal (sin45, 0, cos45): the
    # points (x, 0, SPLITTER_Z - x) lie on it. Built as NumPy first (the way
    # every source builds its bundle) and promoted to the active backend
    # afterwards, so the bookkeeping fields stay plain NumPy.
    ones = np.ones(n)
    rays = NSQRayBundle(
        x=np.asarray(x_values, dtype=float),
        y=np.zeros(n),
        z=np.asarray(SPLITTER_Z - x_values, dtype=float),
        L=ones * direction[0],
        M=ones * direction[1],
        N=ones * direction[2],
        flux=ones.copy(),
        wavelength=ones * 0.55,
        n_current=ones.copy(),
        bounce=np.ones(n, dtype=np.int32),
        alive=np.ones(n, dtype=bool),
        ray_id=np.arange(n, dtype=np.int64),
    )
    for field in ("x", "y", "z", "L", "M", "N", "flux", "wavelength", "n_current"):
        setattr(rays, field, be.array(getattr(rays, field)))
    rays.alive = be.array(rays.alive)
    return rays


def _splitter_component() -> RefractiveComponent:
    return RefractiveComponent(
        cs=CoordinateSystem(z=SPLITTER_Z, ry=math.pi / 4),
        geometry=FinitePlaneGeometry(aperture_radius=5.0),
        material_front=VACUUM,
        material_back=VACUUM,
        coating=SimpleCoating(transmittance=0.5, reflectance=0.5),
        name="splitter",
    )


class TestIntersectGuard:
    def test_rays_leaving_the_surface_do_not_re_hit_it(self, backend_precision):
        """A reflected ray sits on the splitter up to rounding; it must not
        see the splitter again on its next intersection test."""
        component = _splitter_component()
        x_values = np.linspace(-0.9, 0.9, 61)
        rays = _bundle_on_splitter(x_values, direction=(-1.0, 0.0, 0.0))
        _t, _normals, hit, _n_geom = component.intersect(rays)
        assert not be.to_numpy(hit).any()

    def test_rays_just_in_front_of_the_surface_still_hit_it(self, backend_precision):
        component = _splitter_component()
        x_values = np.linspace(-0.9, 0.9, 7)
        rays = _bundle_on_splitter(x_values, direction=(0.0, 0.0, 1.0))
        # Back the rays off the plane by 0.01 mm along -z.
        rays.z = rays.z - 0.01
        t, _normals, hit, _n_geom = component.intersect(rays)
        assert be.to_numpy(hit).all()
        np.testing.assert_allclose(be.to_numpy(t), 0.01, atol=1e-5)


class TestBeamSplitterReferenceScene:
    def test_every_ray_meets_the_splitter_exactly_once(self, backend_precision):
        scene = beam_splitter_scene()
        result = scene.trace(num_rays=NUM_RAYS, seed=SEED, record_paths=True)

        counts = _splitter_hits_per_ray(result)
        assert counts.size == NUM_RAYS
        assert counts.max() == 1
        assert result.num_rays_escaped == 0
        assert result.num_rays_depth_killed == 0
        assert result.num_rays_flux_killed == 0

    def test_roulette_arm_powers_are_a_fair_split(self, backend_precision):
        scene = beam_splitter_scene()
        result = scene.trace(num_rays=NUM_RAYS, seed=SEED)

        t_flux = result.detectors["transmitted"].total_flux_float
        r_flux = result.detectors["reflected"].total_flux_float
        # Single-branch roulette with p = R = 0.5: each ray lands on exactly
        # one detector carrying its full flux, so the arm power is a
        # binomial proportion with sigma = 0.5 / sqrt(N).
        sigma = 0.5 / math.sqrt(NUM_RAYS)
        assert abs(t_flux - 0.5) < 4.0 * sigma
        assert abs(r_flux - 0.5) < 4.0 * sigma
        assert t_flux + r_flux == pytest.approx(1.0, abs=1e-5)
        n_t = result.detectors["transmitted"].num_rays_hit
        n_r = result.detectors["reflected"].num_rays_hit
        assert n_t + n_r == NUM_RAYS
        assert result.flux_conservation_error < 1e-5

    def test_float32_matches_float64_ray_for_ray(self):
        """The branch draws are keyed by ray id, so float32 and float64 must
        make the same reflect/transmit decisions; only accumulation
        rounding may differ. Pre-fix: 0.404 vs 0.501."""
        if "torch" not in be.list_available_backends():
            pytest.skip("torch backend not available")
        be.set_backend("numpy")
        reference = beam_splitter_scene().trace(num_rays=NUM_RAYS, seed=SEED)
        try:
            be.set_backend("torch")
            be.set_device("cpu")
            be.set_precision("float32")
            result = beam_splitter_scene().trace(num_rays=NUM_RAYS, seed=SEED)
        finally:
            be.set_precision("float64")
            be.set_backend("numpy")

        for name in ("transmitted", "reflected"):
            assert result.detectors[name].total_flux_float == pytest.approx(
                reference.detectors[name].total_flux_float, abs=1e-4
            )
            assert (
                result.detectors[name].num_rays_hit
                == reference.detectors[name].num_rays_hit
            )

    def test_bounded_splitting_is_exact_on_numpy(self):
        be.set_backend("numpy")
        scene = beam_splitter_scene()
        scene.sampling_policy = SamplingPolicy(split_depth=1)
        result = scene.trace(num_rays=NUM_RAYS, seed=SEED, record_paths=True)

        assert result.detectors["transmitted"].total_flux_float == pytest.approx(
            0.5, abs=1e-9
        )
        assert result.detectors["reflected"].total_flux_float == pytest.approx(
            0.5, abs=1e-9
        )
        assert result.detectors["transmitted"].num_rays_hit == NUM_RAYS
        assert result.detectors["reflected"].num_rays_hit == NUM_RAYS
        assert not result.diagnostics.split_budget_saturated
        counts = _splitter_hits_per_ray(result)
        assert counts.max() == 1

    @pytest.mark.parametrize("reflectance", [0.0, 0.3, 1.0])
    def test_unequal_and_edge_split_ratios(self, reflectance):
        be.set_backend("numpy")
        scene = beam_splitter_scene(reflectance=reflectance)
        scene.sampling_policy = SamplingPolicy(split_depth=1)
        result = scene.trace(num_rays=512, seed=SEED)

        assert result.detectors["reflected"].total_flux_float == pytest.approx(
            reflectance, abs=1e-9
        )
        assert result.detectors["transmitted"].total_flux_float == pytest.approx(
            1.0 - reflectance, abs=1e-9
        )
        assert result.flux_conservation_error < 1e-9

    def test_lossy_coating_keeps_the_energy_balance_honest(self):
        be.set_backend("numpy")
        scene = beam_splitter_scene(reflectance=0.4, transmittance=0.4)
        scene.sampling_policy = SamplingPolicy(split_depth=1)
        result = scene.trace(num_rays=512, seed=SEED)

        assert result.detectors["reflected"].total_flux_float == pytest.approx(
            0.4, abs=1e-9
        )
        assert result.detectors["transmitted"].total_flux_float == pytest.approx(
            0.4, abs=1e-9
        )
        # The coating absorbs 20 %; this is a modelled loss and is reported
        # as a conservation shortfall rather than silently hidden.
        assert result.total_flux_detected == pytest.approx(0.8, abs=1e-9)
