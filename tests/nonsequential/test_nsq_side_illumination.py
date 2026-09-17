"""Side illumination and imaging in transmission through one beam splitter.

Two independent sources share the splitter: a collimated illumination
beam entering from the side, whose reflected half lights the sample plane,
and a point source at the sample plane standing in for the transmitted
light, whose transmitted half is imaged by a lens onto the camera. The
scene is the reference for "illumination from the side, imaging in
transmission" and for keeping two entrance arms apart.

Kramer Harrison, 2026
"""

from __future__ import annotations

import math

import numpy as np
import pytest

import optiland.backend as be
from optiland.nonsequential.ir.scene_ir import SamplingPolicy
from optiland.samples.nonsequential import (
    SAMPLE_SCENES,
    build_sample_scene,
    side_illumination_transmission_scene,
    thick_lens_image_distance,
)

NUM_RAYS = 4096
SEED = 5


@pytest.fixture(autouse=True)
def _numpy_backend():
    be.set_backend("numpy")
    yield
    be.set_backend("numpy")


def _deterministic_trace(scene, num_rays=NUM_RAYS, record_paths=False):
    scene.sampling_policy = SamplingPolicy(split_depth=1)
    return scene.trace(num_rays=num_rays, seed=SEED, record_paths=record_paths)


def _centroid_fraction(irradiance_map, radius: float) -> float:
    """Fraction of a detector's flux within ``radius`` of its centroid."""
    weights = irradiance_map.irradiance / irradiance_map.irradiance.sum()
    x, y = np.meshgrid(irradiance_map.x_coords, irradiance_map.y_coords)
    cx, cy = (weights * x).sum(), (weights * y).sum()
    r = np.hypot(x - cx, y - cy)
    return float(weights[r <= radius].sum())


class TestSampleRegistry:
    def test_registry_builds_every_scene(self):
        for name in SAMPLE_SCENES:
            scene = build_sample_scene(name)
            scene.validate()

    def test_unknown_name_raises(self):
        with pytest.raises(KeyError):
            build_sample_scene("no_such_scene")


class TestThickLensImageDistance:
    def test_thin_lens_limit(self):
        # Zero thickness: 1/s' = 1/f - 1/s with f = R / (2 (n - 1)).
        n, r = 1.5, 20.0
        f = r / (2.0 * (n - 1.0))
        s = 60.0
        expected = 1.0 / (1.0 / f - 1.0 / s)
        assert thick_lens_image_distance(s, r, -r, 0.0, n) == pytest.approx(expected)

    def test_thickness_pulls_the_image_in(self):
        n, r, s = 1.5, 20.0, 60.0
        thin = thick_lens_image_distance(s, r, -r, 0.0, n)
        thick = thick_lens_image_distance(s, r, -r, 4.0, n)
        assert thick < thin


class TestArmPowers:
    def test_each_arm_receives_its_share_exactly(self):
        scene = side_illumination_transmission_scene()
        result = _deterministic_trace(scene)
        det = result.detectors

        assert det["sample"].total_flux_float == pytest.approx(0.5, abs=1e-9)
        assert det["illumination_dump"].total_flux_float == pytest.approx(0.5, abs=1e-9)
        assert det["return"].total_flux_float == pytest.approx(0.5, abs=1e-9)
        # The camera arm passes 4 mm of N-BK7: only its bulk absorption is
        # missing, and it is accounted for, not lost.
        camera = det["camera"].total_flux_float
        assert camera == pytest.approx(0.5, abs=1e-3)
        assert camera + result.total_flux_bulk_absorbed == pytest.approx(0.5, abs=1e-9)
        assert result.num_rays_escaped == 0
        assert result.total_flux_lost == 0.0
        assert result.flux_conservation_error < 1e-9

    @pytest.mark.parametrize("reflectance", [0.3, 0.7])
    def test_split_ratio_sets_the_arm_powers(self, reflectance):
        scene = side_illumination_transmission_scene(
            reflectance=reflectance, illumination_flux=2.0, object_flux=0.5
        )
        result = _deterministic_trace(scene)
        det = result.detectors

        assert det["sample"].total_flux_float == pytest.approx(2.0 * reflectance)
        assert det["illumination_dump"].total_flux_float == pytest.approx(
            2.0 * (1.0 - reflectance)
        )
        assert det["return"].total_flux_float == pytest.approx(0.5 * reflectance)
        assert det["camera"].total_flux_float == pytest.approx(
            0.5 * (1.0 - reflectance), abs=1e-3
        )

    def test_illumination_footprint_on_the_sample(self):
        scene = side_illumination_transmission_scene(illumination_radius=1.5)
        result = _deterministic_trace(scene)
        sample = result.detectors["sample"]
        # A 1.5 mm collimated beam lands as a 1.5 mm disk, not a blur.
        assert _centroid_fraction(sample, 1.6) > 0.99
        assert _centroid_fraction(sample, 0.75) < 0.5


class TestImaging:
    def test_camera_sits_at_the_paraxial_image_of_the_sample(self):
        scene = side_illumination_transmission_scene()
        result = _deterministic_trace(scene)
        camera = result.detectors["camera"]
        assert camera.num_rays_hit == NUM_RAYS // 2
        # A point on the sample images to a point: nearly all of the flux
        # lands within two pixels (0.16 mm each) of the centroid.
        assert _centroid_fraction(camera, 0.3) > 0.95

    def test_defocused_camera_spreads_the_image(self):
        scene = side_illumination_transmission_scene()
        camera = scene.detector_registry.get("camera")
        camera.cs.z = camera.cs.z - 15.0
        result = _deterministic_trace(scene)
        assert _centroid_fraction(result.detectors["camera"], 0.3) < 0.5


class TestArmsStayApart:
    def test_illumination_never_reaches_the_camera_and_object_never_the_sample(
        self,
    ):
        scene = side_illumination_transmission_scene()
        result = _deterministic_trace(scene, num_rays=1024, record_paths=True)
        events = result.ray_paths["events"]

        births = events[events["event_type"] == "birth"]
        source_of = dict(zip(births["ray_id"], births["component_name"], strict=True))
        # Split children inherit their parent's source.
        for row in events[events["event_type"] == "split"]:
            source_of[int(row["ray_id"])] = source_of[int(row["parent_id"])]

        hits = events[events["event_type"] == "hit"]
        landed = {}
        for name in ("sample", "illumination_dump", "camera", "return"):
            ids = hits[hits["component_name"] == name]["ray_id"]
            landed[name] = {source_of[int(i)] for i in ids}

        assert landed["sample"] == {"illumination"}
        assert landed["illumination_dump"] == {"illumination"}
        assert landed["camera"] == {"object"}
        assert landed["return"] == {"object"}


@pytest.mark.skipif(
    "torch" not in be.list_available_backends(), reason="torch backend not available"
)
@pytest.mark.parametrize("precision", ["float64", "float32"])
def test_roulette_on_torch_matches_the_deterministic_split(precision):
    be.set_backend("torch")
    be.set_device("cpu")
    be.set_precision(precision)
    try:
        result = side_illumination_transmission_scene().trace(
            num_rays=NUM_RAYS, seed=SEED
        )
    finally:
        be.set_precision("float64")
        be.set_backend("numpy")

    # Each source launches NUM_RAYS / 2 rays; every ray ends on exactly one
    # of its arm's two detectors, so each arm power is a binomial
    # proportion with sigma = 0.5 / sqrt(NUM_RAYS / 2) of the source power.
    sigma = 0.5 / math.sqrt(NUM_RAYS / 2)
    det = result.detectors
    for name in ("sample", "illumination_dump", "return"):
        assert abs(det[name].total_flux_float - 0.5) < 4.0 * sigma
    assert abs(det["camera"].total_flux_float - 0.5) < 4.0 * sigma + 1e-3
    assert result.num_rays_escaped == 0
    assert result.flux_conservation_error < 1e-4
