"""Tests for the D1 ray-level medium stack (NSQRayBundle.medium_stack /
medium_depth, pushed/popped by RefractiveComponent.interact).

Kramer Harrison, 2026
"""

from __future__ import annotations

import numpy as np
import pytest

import optiland.backend as be
from optiland.coordinate_system import CoordinateSystem
from optiland.nonsequential.backends.torch_backend import TorchBackend
from optiland.nonsequential.components.geometry.analytic.plane import (
    FinitePlaneGeometry,
)
from optiland.nonsequential.components.refractive import RefractiveComponent
from optiland.nonsequential.detectors.configs import IrradianceDetectorConfig
from optiland.nonsequential.ir.scene_ir import BsdfIR
from optiland.nonsequential.materials.nsq_material import (
    VACUUM,
    NSQMaterial,
    medium_stack_id,
)
from optiland.nonsequential.ray_bundle import (
    MEDIUM_STACK_EMPTY,
    MEDIUM_STACK_MAX_DEPTH,
    NSQRayBundle,
)
from optiland.nonsequential.rng import NSQRng
from optiland.nonsequential.scene import NSQScene
from optiland.nonsequential.sources.base import Spectrum
from optiland.nonsequential.sources.configs import CollimatedSourceConfig

GREEN = 0.55


class TestMediumStackId:
    def test_vacuum_instances_share_one_id(self):
        assert medium_stack_id(NSQMaterial()) == medium_stack_id(VACUUM) == 0

    def test_distinct_glass_instances_get_distinct_ids(self):
        a = NSQMaterial.from_glass("N-BK7")
        b = NSQMaterial.from_glass("N-BK7")
        assert medium_stack_id(a) != medium_stack_id(b)

    def test_same_instance_is_stable(self):
        a = NSQMaterial.from_glass("N-BK7")
        assert medium_stack_id(a) == medium_stack_id(a)


class TestNSQRayBundleFieldWiring:
    def _bundle(self, n=4):
        return NSQRayBundle(
            x=np.zeros(n),
            y=np.zeros(n),
            z=np.zeros(n),
            L=np.zeros(n),
            M=np.zeros(n),
            N=np.ones(n),
            flux=np.ones(n),
            wavelength=np.full(n, GREEN),
            n_current=np.ones(n),
            bounce=np.zeros(n, dtype=np.int32),
            alive=np.ones(n, dtype=bool),
            ray_id=np.arange(n, dtype=np.int64),
        )

    def test_defaults(self):
        rays = self._bundle()
        assert rays.medium_stack.shape == (4, MEDIUM_STACK_MAX_DEPTH)
        assert np.all(rays.medium_stack == MEDIUM_STACK_EMPTY)
        assert np.all(rays.medium_depth == 0)
        assert np.all(rays.medium_stack_underflows == 0)

    def test_compact_preserves_stack_state(self):
        rays = self._bundle()
        rays.medium_stack[:, 0] = 42
        rays.medium_depth[:] = 1
        rays.alive[0] = False
        compacted = rays.compact()
        assert compacted.num_rays == 3
        assert np.all(compacted.medium_depth == 1)
        assert np.all(compacted.medium_stack[:, 0] == 42)

    def test_select_copies_stack_state(self):
        rays = self._bundle()
        rays.medium_stack[:, 0] = 7
        rays.medium_depth[:] = 1
        rays.medium_stack_underflows[:] = 2
        sub = rays.select(np.array([0, 2]))
        assert np.all(sub.medium_depth == 1)
        assert np.all(sub.medium_stack[:, 0] == 7)
        assert np.all(sub.medium_stack_underflows == 2)
        # Independent copy: mutating the source must not affect the copy.
        rays.medium_stack[0, 0] = -5
        assert sub.medium_stack[0, 0] == 7

    def test_concat_stacks_fields(self):
        a = self._bundle(2)
        b = self._bundle(3)
        a.medium_depth[:] = 1
        b.medium_depth[:] = 2
        merged = NSQRayBundle.concat([a, b])
        assert merged.num_rays == 5
        np.testing.assert_array_equal(merged.medium_depth, [1, 1, 2, 2, 2])


class TestMediumStackPushPop:
    def _rays(self, n=1, depth=0, stack=None, direction=1.0):
        rays = NSQRayBundle(
            x=np.zeros(n),
            y=np.zeros(n),
            z=np.full(n, -1.0),
            L=np.zeros(n),
            M=np.zeros(n),
            N=np.full(n, direction),
            flux=np.ones(n),
            wavelength=np.full(n, GREEN),
            n_current=np.ones(n),
            bounce=np.zeros(n, dtype=np.int32),
            alive=np.ones(n, dtype=bool),
            ray_id=np.arange(n, dtype=np.int64),
        )
        rays.medium_depth[:] = depth
        if stack is not None:
            rays.medium_stack[:, : len(stack)] = stack
        return rays

    def _interact(self, comp, rays, forced_branch="transmit", direction=1.0):
        n = rays.num_rays
        normals = np.tile([0.0, 0.0, -direction], (n, 1))
        n_geom = np.tile([0.0, 0.0, 1.0], (n, 1))  # fixed surface convention
        t = np.ones(n)
        hit_mask = np.ones(n, dtype=bool)
        comp.interact(
            rays,
            t,
            normals,
            hit_mask,
            NSQRng(0),
            BsdfIR(kind="none"),
            n_geom,
            forced_branch=forced_branch,
        )

    def test_entering_glass_from_ambient_pushes(self):
        glass = NSQMaterial.from_glass("N-BK7")
        comp = RefractiveComponent(
            CoordinateSystem(),
            FinitePlaneGeometry(20, 20),
            VACUUM,
            glass,
        )
        rays = self._rays()
        self._interact(comp, rays)
        assert rays.medium_depth[0] == 1
        assert rays.medium_stack[0, 0] == medium_stack_id(glass)
        assert rays.medium_stack_underflows[0] == 0

    def test_exiting_to_ambient_pops(self):
        glass = NSQMaterial.from_glass("N-BK7")
        # This surface's own convention: front=glass, back=vacuum (like a
        # Lens's second face), and the ray approaches from inside the glass.
        comp = RefractiveComponent(
            CoordinateSystem(),
            FinitePlaneGeometry(20, 20),
            glass,
            VACUUM,
        )
        rays = self._rays(depth=1, stack=[medium_stack_id(glass)])
        self._interact(comp, rays)
        assert rays.medium_depth[0] == 0
        assert rays.medium_stack[0, 0] == MEDIUM_STACK_EMPTY
        assert rays.medium_stack_underflows[0] == 0

    def test_exiting_to_ambient_with_empty_stack_is_a_leak(self):
        glass = NSQMaterial.from_glass("N-BK7")
        comp = RefractiveComponent(
            CoordinateSystem(),
            FinitePlaneGeometry(20, 20),
            glass,
            VACUUM,
        )
        rays = self._rays(depth=0)
        self._interact(comp, rays)
        assert rays.medium_depth[0] == 0
        assert rays.medium_stack_underflows[0] == 1

    def test_cement_interface_pushes_then_ambient_exit_unwinds_fully(self):
        glass_a = NSQMaterial.from_glass("N-BK7")
        glass_b = NSQMaterial.from_glass("N-SF5")
        cement = RefractiveComponent(
            CoordinateSystem(),
            FinitePlaneGeometry(20, 20),
            glass_a,
            glass_b,
        )
        exit_face = RefractiveComponent(
            CoordinateSystem(),
            FinitePlaneGeometry(20, 20),
            glass_b,
            VACUUM,
        )
        rays = self._rays(depth=1, stack=[medium_stack_id(glass_a)])
        self._interact(cement, rays)
        assert rays.medium_depth[0] == 2
        assert rays.medium_stack_underflows[0] == 0

        self._interact(exit_face, rays)
        assert rays.medium_depth[0] == 0
        assert rays.medium_stack[0].tolist() == [MEDIUM_STACK_EMPTY] * len(
            rays.medium_stack[0]
        )
        assert rays.medium_stack_underflows[0] == 0

    def test_true_nesting_exit_pops_one_level_not_the_whole_stack(self):
        housing = NSQMaterial.from_glass("N-BK7")
        oil = NSQMaterial.from_glass("N-SF5")
        ball = RefractiveComponent(
            CoordinateSystem(),
            FinitePlaneGeometry(20, 20),
            oil,
            housing,
        )
        rays = self._rays(
            depth=2,
            stack=[medium_stack_id(housing), medium_stack_id(oil)],
            direction=-1.0,
        )
        # Ray inside the ball glass (pushed on top, not modelled here)
        # exits back into the surrounding oil: matches one level below top.
        rays.medium_stack[0, 2] = 999  # sentinel "ball glass" id at top
        rays.medium_depth[0] = 3
        # front=oil is the medium being returned to (entering_back=False).
        self._interact(ball, rays, direction=-1.0)
        assert rays.medium_depth[0] == 2
        assert rays.medium_stack[0, 1] == medium_stack_id(oil)
        assert rays.medium_stack_underflows[0] == 0

    def test_overflow_is_counted_not_raised(self):
        """O18: a push on a full stack is dropped and counted; the ray goes on."""
        deep = [i + 1 for i in range(MEDIUM_STACK_MAX_DEPTH)]
        glass = NSQMaterial.from_glass("N-BK7")
        other = NSQMaterial.from_glass("N-SF5")
        comp = RefractiveComponent(
            CoordinateSystem(),
            FinitePlaneGeometry(20, 20),
            glass,
            other,
        )
        rays = self._rays(depth=MEDIUM_STACK_MAX_DEPTH, stack=deep)
        self._interact(comp, rays)
        assert rays.medium_depth[0] == MEDIUM_STACK_MAX_DEPTH
        np.testing.assert_array_equal(rays.medium_stack[0], deep)
        assert rays.medium_stack_overflows[0] == 1
        assert rays.medium_stack_underflows[0] == 0
        # The physics went on: the ray refracted into the second medium.
        assert rays.n_current[0] == pytest.approx(float(other.n(GREEN)))
        assert bool(rays.alive[0])

    def test_reflection_never_touches_the_stack(self):
        glass = NSQMaterial.from_glass("N-BK7")
        comp = RefractiveComponent(
            CoordinateSystem(),
            FinitePlaneGeometry(20, 20),
            VACUUM,
            glass,
        )
        rays = self._rays()
        self._interact(comp, rays, forced_branch="reflect")
        assert rays.medium_depth[0] == 0
        assert rays.medium_stack_underflows[0] == 0


class TestDeepNestingTrace:
    """O18: a trace through more media than the stack holds completes.

    Found with a folded scene that ends in an eye model: rays reflected
    between the faces of the eye lens re-enter the same media until
    the diagnostic medium stack was full, and the whole 200 000-ray trace
    died with MediumStackOverflowError. The stack never feeds the physics,
    so an overflow is a diagnostic count, not an abort.
    """

    @staticmethod
    def _scene() -> NSQScene:
        # Nine abutting slabs of nine distinct media: every crossing pushes
        # (no medium repeats, none is ambient), the ninth push overflows.
        media = [VACUUM] + [
            NSQMaterial.from_glass("N-BK7") for _ in range(MEDIUM_STACK_MAX_DEPTH + 1)
        ]
        scene = NSQScene()
        for k in range(MEDIUM_STACK_MAX_DEPTH + 1):
            scene.add_component(
                f"slab_{k}",
                RefractiveComponent(
                    CoordinateSystem(z=1.0 + k),
                    FinitePlaneGeometry(20, 20),
                    media[k],
                    media[k + 1],
                ),
            )
        scene.add_source(
            "src",
            CoordinateSystem(),
            CollimatedSourceConfig(
                spectrum=Spectrum.monochromatic(GREEN),
                total_flux=1.0,
                aperture_radius=1.0,
            ),
        )
        scene.add_detector(
            "det",
            CoordinateSystem(z=15.0),
            IrradianceDetectorConfig(
                width=10.0, height=10.0, num_pixels_x=8, num_pixels_y=8
            ),
        )
        return scene

    @staticmethod
    def _check(result) -> None:
        # Every ray either reached the detector through all nine media
        # (one overflow at the ninth push) or was Fresnel-reflected at the
        # first vacuum-glass face and escaped; none was lost to an abort.
        hit = result.detectors["det"].num_rays_hit
        assert hit + result.num_rays_escaped == 64
        assert hit >= 50
        assert result.diagnostics.medium_stack_overflows == hit
        assert result.diagnostics.medium_stack_underflows == 0

    def test_numpy_backend_counts_the_overflow(self):
        result = self._scene().trace(num_rays=64, max_depth=20, seed=1)
        self._check(result)
        assert any("overflow" in w for w in result.diagnostics.warnings())
        hit = result.detectors["det"].num_rays_hit
        assert f"medium_stack_overflows:        {hit}" in result.diagnostics.report()

    def test_torch_backend_counts_the_overflow(self):
        be.set_backend("torch")
        try:
            result = self._scene().trace(
                num_rays=64, max_depth=20, seed=1, backend=TorchBackend(seed=1)
            )
        finally:
            be.set_backend("numpy")
        self._check(result)
