"""JSON round trip of raw surfaces added via ``NSQScene.add_component``.

The beam-splitter scenes are built from a bare ``RefractiveComponent`` with
a ``SimpleCoating``; before this, ``NSQScene.to_json`` rejected any raw
surface, so the reference scenes could not be saved or reopened.

Kramer Harrison, 2026
"""

from __future__ import annotations

import math

import numpy as np
import pytest

import optiland.backend as be
from optiland.coatings import SimpleCoating
from optiland.coordinate_system import CoordinateSystem
from optiland.nonsequential import (
    VACUUM,
    AbsorbingComponent,
    CollimatedSourceConfig,
    ConicGeometry,
    FinitePlaneGeometry,
    IrradianceDetectorConfig,
    NSQMaterial,
    NSQScene,
    PlaneGeometry,
    ReflectiveComponent,
    RefractiveComponent,
    Spectrum,
    SphereGeometry,
)
from optiland.nonsequential.bsdf.lambertian import LambertianBSDF
from optiland.nonsequential.components import SingleSurfaceCompound
from optiland.nonsequential.ir.scene_ir import SamplingPolicy
from optiland.nonsequential.serialization import scene_from_dict, scene_to_dict
from optiland.samples.nonsequential import (
    beam_splitter_scene,
    side_illumination_transmission_scene,
)


@pytest.fixture(autouse=True)
def _numpy_backend():
    be.set_backend("numpy")
    yield
    be.set_backend("numpy")


def _arm_powers(scene, num_rays=1024):
    scene.sampling_policy = SamplingPolicy(split_depth=1)
    result = scene.trace(num_rays=num_rays, seed=2)
    return {name: det.total_flux_float for name, det in result.detectors.items()}


class TestSingleSurfaceCompound:
    def test_add_component_wraps_in_a_public_compound(self):
        scene = beam_splitter_scene()
        compound = scene.component_registry.get("splitter")
        assert isinstance(compound, SingleSurfaceCompound)
        assert compound.name == "splitter"
        assert isinstance(compound.component, RefractiveComponent)
        assert compound.surfaces == [compound.component]
        assert compound.coordinate_system is compound.component.cs


class TestRoundTrip:
    @pytest.mark.parametrize(
        "builder", [beam_splitter_scene, side_illumination_transmission_scene]
    )
    def test_sample_scenes_trace_identically_after_round_trip(self, builder):
        original = builder()
        restored = scene_from_dict(scene_to_dict(original))

        assert restored.component_names == original.component_names
        assert restored.detector_names == original.detector_names
        assert restored.source_names == original.source_names
        assert _arm_powers(restored) == pytest.approx(_arm_powers(original), abs=1e-12)

    def test_json_file_round_trip(self, tmp_path):
        path = tmp_path / "splitter.json"
        beam_splitter_scene(reflectance=0.3).to_json(path)
        restored = NSQScene.from_json(path)
        splitter = restored.component_registry.get("splitter").component
        assert splitter.coating.reflectance == pytest.approx(0.3)
        assert splitter.coating.transmittance == pytest.approx(0.7)
        assert splitter.name == "splitter"
        np.testing.assert_allclose(
            be.to_numpy(splitter.cs.get_effective_transform()[1]),
            be.to_numpy(
                beam_splitter_scene()
                .component_registry.get("splitter")
                .component.cs.get_effective_transform()[1]
            ),
        )

    def test_reflective_and_absorbing_surfaces_and_all_geometries(self):
        glass = NSQMaterial.from_glass("N-BK7")
        scene = NSQScene()
        scene.add_source(
            "S",
            CoordinateSystem(),
            CollimatedSourceConfig(
                spectrum=Spectrum.monochromatic(0.55),
                total_flux=1.0,
                aperture_radius=1.0,
            ),
        )
        scene.add_component(
            "mirror",
            ReflectiveComponent(
                cs=CoordinateSystem(z=30, ry=math.pi / 4),
                geometry=ConicGeometry(radius=-100.0, conic=-1.0, aperture_radius=8.0),
                reflectance=0.9,
                name="fold",
            ),
        )
        scene.add_component(
            "coated_mirror",
            ReflectiveComponent(
                cs=CoordinateSystem(x=-40, z=30),
                geometry=SphereGeometry(radius=50.0, aperture_radius=5.0),
                reflectance=SimpleCoating(transmittance=0.0, reflectance=0.8),
            ),
        )
        scene.add_component(
            "baffle",
            AbsorbingComponent(
                cs=CoordinateSystem(z=60), geometry=PlaneGeometry(), name="baffle"
            ),
        )
        scene.add_component(
            "window",
            RefractiveComponent(
                cs=CoordinateSystem(z=5),
                geometry=FinitePlaneGeometry(width=4.0, height=6.0),
                material_front=VACUUM,
                material_back=glass,
            ),
        )
        scene.add_detector(
            "D",
            CoordinateSystem(z=80),
            IrradianceDetectorConfig(
                width=10, height=10, num_pixels_x=4, num_pixels_y=4
            ),
        )

        data = scene_to_dict(scene)
        kinds = {c["name"]: (c["type"], c.get("kind")) for c in data["components"]}
        assert kinds == {
            "mirror": ("surface", "reflective"),
            "coated_mirror": ("surface", "reflective"),
            "baffle": ("surface", "absorbing"),
            "window": ("surface", "refractive"),
        }
        geometries = {c["name"]: c["geometry"]["kind"] for c in data["components"]}
        assert geometries == {
            "mirror": "conic",
            "coated_mirror": "sphere",
            "baffle": "plane",
            "window": "finite_plane",
        }

        restored = scene_from_dict(data)
        mirror = restored.component_registry.get("mirror").component
        assert isinstance(mirror, ReflectiveComponent)
        assert mirror.reflectance == pytest.approx(0.9)
        assert mirror.name == "fold"
        assert mirror.geometry.conic == pytest.approx(-1.0)
        coated = restored.component_registry.get("coated_mirror").component
        assert coated.reflectance.reflectance == pytest.approx(0.8)
        assert coated.geometry.aperture_radius == pytest.approx(5.0)
        baffle = restored.component_registry.get("baffle").component
        assert isinstance(baffle, AbsorbingComponent)
        assert isinstance(baffle.geometry, PlaneGeometry)
        window = restored.component_registry.get("window").component
        assert window.geometry.width == pytest.approx(4.0)
        assert window.geometry.height == pytest.approx(6.0)
        assert window.geometry.aperture_radius is None
        assert window.material_back.optiland_material.name == "N-BK7"
        assert window.material_front.optiland_material is None


class TestSurfaceConfigRoundTrip:
    def test_lens_face_coatings_survive(self):
        """The imaging lens of the side-illumination scene is lossless only
        through its face coatings; dropping them changed the camera power
        by 9 % after a reload."""
        from optiland.nonsequential import InteractionType, LensConfig, SurfaceConfig

        scene = side_illumination_transmission_scene()
        data = scene_to_dict(scene)
        lens = next(c for c in data["components"] if c["name"] == "imaging_lens")
        assert lens["config"]["front"]["coating"] == {
            "reflectance": 0.0,
            "transmittance": 1.0,
        }
        assert lens["config"]["edge"] is None

        scene.add_lens(
            "overrides",
            CoordinateSystem(z=-80),
            LensConfig(
                r1=30.0,
                r2=-30.0,
                thickness=3.0,
                material="N-BK7",
                front_aperture_radius=5.0,
                back=SurfaceConfig(
                    interaction=InteractionType.REFLECTIVE,
                    reflectance=0.95,
                    scatter_fraction=0.5,
                ),
            ),
        )
        restored = scene_from_dict(scene_to_dict(scene))
        back = restored.component_registry.get("overrides")._config.back
        assert back.interaction is InteractionType.REFLECTIVE
        assert back.reflectance == pytest.approx(0.95)
        assert back.aperture_radius is None
        assert back.scatter_fraction == pytest.approx(0.5)
        assert back.coating is None


class TestUnsupported:
    def test_bsdf_on_a_raw_surface_is_rejected(self):
        scene = beam_splitter_scene()
        scene.add_component(
            "diffuser",
            RefractiveComponent(
                cs=CoordinateSystem(z=40),
                geometry=FinitePlaneGeometry(aperture_radius=3.0),
                material_front=VACUUM,
                material_back=VACUUM,
                bsdf=LambertianBSDF(reflectance_value=0.5),
            ),
        )
        with pytest.raises(TypeError, match="BSDF"):
            scene_to_dict(scene)

    def test_callable_reflectance_is_rejected(self):
        scene = beam_splitter_scene()
        scene.add_component(
            "mirror",
            ReflectiveComponent(
                cs=CoordinateSystem(z=40),
                geometry=FinitePlaneGeometry(aperture_radius=3.0),
                reflectance=lambda wl: 0.5 * wl,
            ),
        )
        with pytest.raises(TypeError, match="callable"):
            scene_to_dict(scene)

    def test_lens_face_bsdf_is_rejected_instead_of_dropped(self):
        from optiland.nonsequential import LensConfig, SurfaceConfig

        scene = beam_splitter_scene()
        scene.add_lens(
            "diffusing_lens",
            CoordinateSystem(z=40),
            LensConfig(
                r1=20.0,
                r2=-20.0,
                thickness=3.0,
                material="N-BK7",
                front_aperture_radius=5.0,
                front=SurfaceConfig(bsdf=LambertianBSDF(reflectance_value=0.5)),
            ),
        )
        with pytest.raises(TypeError, match="BSDF"):
            scene_to_dict(scene)

    def test_unknown_surface_kind_raises(self):
        data = scene_to_dict(beam_splitter_scene())
        data["components"][0]["kind"] = "diffractive"
        with pytest.raises(ValueError, match="diffractive"):
            scene_from_dict(data)
