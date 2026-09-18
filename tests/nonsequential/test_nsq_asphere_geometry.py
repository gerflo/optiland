"""Even-asphere geometry for non-sequential tracing.

The A18-15HPX ophthalmoscope lens of the RCR-03 fundus camera is an even
asphere with seven coefficients; without this geometry the NSQ scene could
only carry its base conic and the imaging path would not match the
sequential design.

Kramer Harrison, 2026
"""

from __future__ import annotations

import numpy as np
import pytest

import optiland.backend as be
from optiland.coordinate_system import CoordinateSystem
from optiland.geometries.even_asphere import EvenAsphere
from optiland.nonsequential import (
    CollimatedSourceConfig,
    ConicGeometry,
    EvenAsphereGeometry,
    IrradianceDetectorConfig,
    LensConfig,
    NSQScene,
    Spectrum,
)
from optiland.nonsequential.ir.lower import lower
from optiland.nonsequential.serialization import scene_from_dict, scene_to_dict

# A18-15HPX-U-S as stored in the user's design file (coefficients[0] -> r^2).
_A18 = {
    "radius": -11.65,
    "conic": -1.1,
    "coefficients": [
        -3.6906721e-05,
        1.2854612e-08,
        1.4001677e-10,
        2.5131166e-13,
        -5.0178988e-16,
        -5.8558715e-18,
        1.1277944e-20,
    ],
}


@pytest.fixture(autouse=True)
def _numpy_backend():
    be.set_backend("numpy")
    yield
    be.set_backend("numpy")


def _rays(n: int, seed: int = 1, oblique: bool = False):
    rng = np.random.default_rng(seed)
    r = 8.5 * np.sqrt(rng.uniform(size=n))
    phi = rng.uniform(0.0, 2.0 * np.pi, n)
    origins = np.stack([r * np.cos(phi), r * np.sin(phi), np.full(n, 5.0)], axis=1)
    if oblique:
        dirs = np.stack([np.full(n, 0.3), np.full(n, -0.2), np.full(n, -1.0)], axis=1)
    else:
        dirs = np.tile([0.0, 0.0, -1.0], (n, 1))
    dirs /= np.linalg.norm(dirs, axis=1, keepdims=True)
    return origins, dirs


class TestSagAndNormal:
    def test_sag_matches_the_sequential_even_asphere(self):
        geom = EvenAsphereGeometry(aperture_radius=9.0, **_A18)
        seq = EvenAsphere(CoordinateSystem(), **_A18)
        r = np.linspace(0.0, 8.5, 40)
        nsq = be.to_numpy(geom._sag(r, np.zeros_like(r)))
        ref = be.to_numpy(seq.sag(r, np.zeros_like(r)))
        assert np.abs(nsq - ref).max() < 1e-12

    @pytest.mark.parametrize("oblique", [False, True])
    def test_hits_lie_on_the_surface_with_the_sequential_normal(self, oblique):
        geom = EvenAsphereGeometry(aperture_radius=9.0, **_A18)
        seq = EvenAsphere(CoordinateSystem(), **_A18)
        origins, dirs = _rays(2000, oblique=oblique)
        t, normals, hit, n_geom = geom.ray_intersect(origins, dirs)
        hit = be.to_numpy(hit)
        assert hit.sum() > 1500
        p = origins + be.to_numpy(t)[:, None] * dirs
        residual = p[:, 2] - be.to_numpy(seq.sag(p[:, 0], p[:, 1]))
        assert np.abs(residual[hit]).max() < 1e-9
        assert np.hypot(p[hit, 0], p[hit, 1]).max() <= 9.0 + 1e-9
        nx, ny, nz = seq._surface_normal(p[:, 0], p[:, 1])
        n_ref = np.stack([nx, ny, nz], axis=1)
        dots = np.abs((be.to_numpy(n_geom) * n_ref).sum(axis=1))
        assert dots[hit].min() > 1.0 - 1e-9
        # Normals face the incoming ray.
        assert ((be.to_numpy(normals) * dirs).sum(axis=1)[hit] < 0.0).all()

    def test_zero_coefficients_reduce_to_the_conic(self):
        asphere = EvenAsphereGeometry(-11.65, -1.1, 9.0, coefficients=[0.0, 0.0])
        conic = ConicGeometry(-11.65, -1.1, 9.0)
        origins, dirs = _rays(1000, oblique=True)
        ta, _, ha, _ = asphere.ray_intersect(origins, dirs)
        tc, _, hc, _ = conic.ray_intersect(origins, dirs)
        assert (be.to_numpy(ha) == be.to_numpy(hc)).all()
        assert np.abs(be.to_numpy(ta)[ha] - be.to_numpy(tc)[hc]).max() < 1e-9

    def test_rays_outside_the_aperture_miss(self):
        geom = EvenAsphereGeometry(aperture_radius=3.0, **_A18)
        origins = np.array([[0.0, 0.0, 5.0], [4.0, 0.0, 5.0], [0.0, 2.9, 5.0]])
        dirs = np.tile([0.0, 0.0, -1.0], (3, 1))
        _, _, hit, _ = geom.ray_intersect(origins, dirs)
        assert be.to_numpy(hit).tolist() == [True, False, True]

    def test_bounding_box_contains_the_sampled_sag(self):
        geom = EvenAsphereGeometry(aperture_radius=9.0, **_A18)
        box = geom.bounding_box((np.zeros(3), np.eye(3)))
        assert box.xmin == pytest.approx(-9.0) and box.xmax == pytest.approx(9.0)
        assert box.zmin <= geom.sag_float(9.0) <= box.zmax
        assert box.zmin <= 0.0 <= box.zmax


class TestIntegration:
    def _plano_asphere_scene(self, coefficients):
        scene = NSQScene()
        scene.add_source(
            "beam",
            CoordinateSystem(z=-10.0),
            CollimatedSourceConfig(
                spectrum=Spectrum.monochromatic(0.55),
                total_flux=1.0,
                aperture_radius=6.0,
            ),
        )
        # Convex asphere facing the beam: the front face of an A18 used
        # plane-side-to-focus, so the beam is focused behind the lens.
        scene.add_lens(
            "A18",
            CoordinateSystem(),
            LensConfig(
                r1=11.65,
                r2=0.0,
                thickness=6.2,
                material="N-BK7",
                front_aperture_radius=9.0,
                conic1=-1.1,
                coefficients1=coefficients,
            ),
        )
        scene.add_detector(
            "focus",
            CoordinateSystem(z=6.2 + 12.0),
            IrradianceDetectorConfig(
                width=4.0, height=4.0, num_pixels_x=8, num_pixels_y=8
            ),
        )
        return scene

    def test_lens_config_coefficients_build_an_asphere_face(self):
        scene = self._plano_asphere_scene([0.0, -1e-5])
        front = scene.component_registry.get("A18").surfaces[0]
        assert isinstance(front.geometry, EvenAsphereGeometry)
        assert be.to_numpy(front.geometry.coefficients[1]) == pytest.approx(-1e-5)
        conic_only = self._plano_asphere_scene([])
        assert type(conic_only.component_registry.get("A18").surfaces[0].geometry) is (
            ConicGeometry
        )

    def test_coefficients_change_the_trace_and_round_trip(self):
        aspheric = self._plano_asphere_scene([0.0, -2e-4])
        conic = self._plano_asphere_scene([])
        flux_aspheric = aspheric.trace(num_rays=2000, seed=3).detectors["focus"]
        flux_conic = conic.trace(num_rays=2000, seed=3).detectors["focus"]
        assert flux_aspheric.num_rays_hit != flux_conic.num_rays_hit

        restored = scene_from_dict(scene_to_dict(aspheric))
        cfg = restored.component_registry.get("A18")._config
        assert list(cfg.coefficients1) == pytest.approx([0.0, -2e-4])
        again = restored.trace(num_rays=2000, seed=3).detectors["focus"]
        assert again.total_flux_float == pytest.approx(flux_aspheric.total_flux_float)

    def test_lowers_to_its_own_ir_kind(self):
        scene = self._plano_asphere_scene([0.0, -1e-5])
        ir = lower(scene)
        kinds = {p.name: p.kind for p in ir.primitives}
        assert kinds["A18.front"] == "even_asphere"
        params = next(p for p in ir.primitives if p.name == "A18.front").params
        assert [float(c) for c in params["coefficients"]] == pytest.approx([0.0, -1e-5])

    def test_torch_backend_agrees_with_numpy(self):
        pytest.importorskip("torch")
        scene = self._plano_asphere_scene([0.0, -2e-4])
        expected = scene.trace(num_rays=1024, seed=5).detectors["focus"]
        be.set_backend("torch")
        try:
            be.set_precision("float64")
            got = self._plano_asphere_scene([0.0, -2e-4]).trace(num_rays=1024, seed=5)
        finally:
            be.set_backend("numpy")
        assert got.detectors["focus"].num_rays_hit == expected.num_rays_hit
        assert got.detectors["focus"].total_flux_float == pytest.approx(
            expected.total_flux_float, rel=1e-6
        )
