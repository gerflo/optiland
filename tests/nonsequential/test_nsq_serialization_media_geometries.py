"""JSON round trip of constant-index media, annular mirrors and aspheres.

The folded fundus-camera scene needs all three: the eye model is made of
``IdealMaterial`` media, the perforated fold mirror is an annulus with an
elliptical hole, and the ophthalmoscope lens is an even asphere. Before
this, ``NSQScene.to_json`` rejected the media and the geometries.

Kramer Harrison, 2026
"""

from __future__ import annotations

import math

import numpy as np
import pytest

import optiland.backend as be
from optiland.coordinate_system import CoordinateSystem
from optiland.materials.ideal import IdealMaterial
from optiland.nonsequential import (
    VACUUM,
    AnnularPlaneGeometry,
    CollimatedSourceConfig,
    EvenAsphereGeometry,
    IrradianceDetectorConfig,
    NSQMaterial,
    NSQScene,
    ReflectiveComponent,
    RefractiveComponent,
    Spectrum,
)
from optiland.nonsequential.serialization import (
    _deserialize_material,
    _serialize_material,
    scene_from_dict,
    scene_to_dict,
)


@pytest.fixture(autouse=True)
def _numpy_backend():
    be.set_backend("numpy")
    yield
    be.set_backend("numpy")


def _f(value) -> float:
    return float(np.ravel(be.to_numpy(value))[0])


class TestIdealMedia:
    def test_material_value_round_trip(self):
        vitreous = NSQMaterial(optiland_material=IdealMaterial(n=1.3365, k=2e-5))
        data = _serialize_material(vitreous)
        assert data == {"type": "ideal", "index": 1.3365, "absorp": 2e-5}
        restored = _deserialize_material(data)
        assert isinstance(restored, NSQMaterial)
        assert _f(restored.n(0.55)) == pytest.approx(1.3365)
        assert _f(restored.k(0.55)) == pytest.approx(2e-5)
        assert _deserialize_material({"type": "catalog", "name": "N-BK7"}) == "N-BK7"

    def test_eye_like_scene_round_trips(self):
        aqueous = NSQMaterial(optiland_material=IdealMaterial(n=1.3376))
        lens = NSQMaterial(optiland_material=IdealMaterial(n=1.6778))
        scene = NSQScene()
        scene.add_source(
            "S",
            CoordinateSystem(z=-5.0),
            CollimatedSourceConfig(
                spectrum=Spectrum.monochromatic(0.55),
                total_flux=1.0,
                aperture_radius=0.6,
            ),
        )
        scene.add_component(
            "cornea",
            RefractiveComponent(
                cs=CoordinateSystem(),
                geometry=EvenAsphereGeometry(1.5, 0.0, 1.2, coefficients=[0.0, 0.0]),
                material_front=VACUUM,
                material_back=aqueous,
            ),
        )
        scene.add_component(
            "lens_front",
            RefractiveComponent(
                cs=CoordinateSystem(z=0.5),
                geometry=EvenAsphereGeometry(1.2, -0.5, 1.0, coefficients=[0.0, 0.01]),
                material_front=aqueous,
                material_back=lens,
            ),
        )
        scene.add_detector(
            "D",
            CoordinateSystem(z=3.0),
            IrradianceDetectorConfig(
                width=3.0, height=3.0, num_pixels_x=8, num_pixels_y=8
            ),
        )
        data = scene_to_dict(scene)
        media = {c["name"]: c["material_back"] for c in data["components"]}
        assert media["cornea"] == {"type": "ideal", "index": 1.3376, "absorp": 0.0}
        restored = scene_from_dict(data)
        front = restored.component_registry.get("lens_front").component
        assert _f(front.material_front.n(0.55)) == pytest.approx(1.3376)
        assert isinstance(front.geometry, EvenAsphereGeometry)
        assert [_f(c) for c in front.geometry.coefficients] == [0.0, 0.01]
        a = scene.trace(num_rays=256, seed=1).detectors["D"]
        b = restored.trace(num_rays=256, seed=1).detectors["D"]
        assert a.total_flux_float == pytest.approx(b.total_flux_float)
        assert a.num_rays_hit == b.num_rays_hit > 0


class TestAnnularMirror:
    def _scene(self, inner_y):
        scene = NSQScene()
        scene.add_source(
            "S",
            CoordinateSystem(x=-20.0, z=10.0, ry=math.pi / 2),
            CollimatedSourceConfig(
                spectrum=Spectrum.monochromatic(0.55),
                total_flux=1.0,
                aperture_radius=6.0,
            ),
        )
        scene.add_component(
            "ring",
            ReflectiveComponent(
                cs=CoordinateSystem(z=10.0, ry=math.pi / 4),
                # Outer radius 12 keeps the whole 6 mm beam on the tilted
                # plate (its projected radius along x is 12 sin 45 = 8.5).
                geometry=AnnularPlaneGeometry(
                    inner_radius=2.0 / math.cos(math.pi / 4),
                    outer_radius=12.0,
                    inner_radius_y=inner_y,
                ),
                reflectance=0.9,
            ),
        )
        scene.add_detector(
            "folded",
            CoordinateSystem(z=-10.0),
            IrradianceDetectorConfig(
                width=20.0, height=20.0, num_pixels_x=8, num_pixels_y=8
            ),
        )
        scene.add_detector(
            "leak",
            CoordinateSystem(x=20.0, z=10.0, ry=-math.pi / 2),
            IrradianceDetectorConfig(
                width=20.0, height=20.0, num_pixels_x=8, num_pixels_y=8
            ),
        )
        return scene

    def test_elliptical_hole_round_trips_and_traces_identically(self):
        scene = self._scene(2.0)
        data = scene_to_dict(scene)
        geometry = next(c for c in data["components"] if c["name"] == "ring")[
            "geometry"
        ]
        assert geometry["kind"] == "annulus"
        assert geometry["inner_radius_y"] == pytest.approx(2.0)
        restored = scene_from_dict(data)
        ring = restored.component_registry.get("ring").component
        assert ring.geometry.is_elliptical
        assert _f(ring.geometry.inner_radius) == pytest.approx(2.0 * math.sqrt(2.0))
        a = scene.trace(num_rays=2048, seed=2)
        b = restored.trace(num_rays=2048, seed=2)
        for name in ("folded", "leak"):
            assert a.detectors[name].total_flux_float == pytest.approx(
                b.detectors[name].total_flux_float
            )
        # The beam travels +x, so the hole is seen along x: an ellipse with
        # semi-axis 2 sqrt(2) along the plate leaks a circle of radius 2.
        leak = a.detectors["leak"].total_flux_float
        assert leak == pytest.approx((2.0 / 6.0) ** 2, rel=0.1)

    def test_circular_hole_stays_circular(self):
        restored = scene_from_dict(scene_to_dict(self._scene(None)))
        ring = restored.component_registry.get("ring").component
        assert not ring.geometry.is_elliptical
        assert ring.geometry.inner_radius_y is None
