"""Folding an imaging and an illumination path at a perforated mirror.

A synthetic coaxial illuminator: the imaging path looks through the hole
of a 45 deg mirror at a sample behind a shared lens; the illumination path
is relayed onto the mirror ring and folded through the same lens onto the
sample. Both paths are given as unfolded sequential optics, as designers
lay them out.

Kramer Harrison, 2026
"""

from __future__ import annotations

import math

import numpy as np
import pytest

import optiland.backend as be
from optiland.nonsequential import NSQScene
from optiland.nonsequential.components.base import _get_transform
from optiland.nonsequential.convert import ConversionError
from optiland.nonsequential.fold import (
    CAMERA,
    DUMP,
    ILLUMINATION,
    MIRROR,
    RETURN,
    SAMPLE,
    compare_tails,
    fold_paths,
    trace_per_source,
)
from optiland.nonsequential.serialization import scene_from_dict, scene_to_dict
from optiland.optic import Optic
from optiland.physical_apertures import RadialAperture

_R = 30.0  # shared lens radii
_T = 3.0  # shared lens thickness
_OBJ_TO_LENS = 20.0
_LENS_TO_FOLD = 37.0
_FOLD_IMAGING = 3
_FOLD_ILLUMINATION = 4


@pytest.fixture(autouse=True)
def _numpy_backend():
    be.set_backend("numpy")
    yield
    be.set_backend("numpy")


def imaging_optic(hole_radius: float = 2.0) -> Optic:
    """Sample -> shared lens -> hole -> camera lens -> camera."""
    optic = Optic()
    optic.add_surface(index=0, thickness=_OBJ_TO_LENS)
    optic.add_surface(
        index=1, radius=_R, thickness=_T, material="N-BK7", aperture=RadialAperture(8.0)
    )
    optic.add_surface(
        index=2, radius=-_R, thickness=_LENS_TO_FOLD, aperture=RadialAperture(8.0)
    )
    optic.add_surface(
        index=3, thickness=40.0, is_stop=True, aperture=RadialAperture(hole_radius)
    )
    optic.add_surface(
        index=4, radius=_R, thickness=_T, material="N-BK7", aperture=RadialAperture(8.0)
    )
    optic.add_surface(index=5, radius=-_R, thickness=50.0, aperture=RadialAperture(8.0))
    optic.add_surface(index=6, aperture=RadialAperture(6.0))
    optic.set_aperture(aperture_type="float_by_stop_size", value=2.0 * hole_radius)
    optic.set_field_type(field_type="object_height")
    optic.add_field(y=0.0)
    optic.add_field(y=0.5)
    optic.add_wavelength(value=0.55, is_primary=True)
    return optic


def illumination_optic(sample_distance: float = _OBJ_TO_LENS) -> Optic:
    """Ring source -> stop -> relay lens -> mirror ring -> shared lens -> sample."""
    optic = Optic()
    optic.add_surface(index=0, thickness=10.0)
    optic.add_surface(
        index=1, thickness=20.0, is_stop=True, aperture=RadialAperture(4.0)
    )
    optic.add_surface(
        index=2,
        radius=40.0,
        thickness=_T,
        material="N-BK7",
        aperture=RadialAperture(10.0),
    )
    optic.add_surface(
        index=3, radius=-40.0, thickness=50.0, aperture=RadialAperture(10.0)
    )
    optic.add_surface(
        index=4, thickness=_LENS_TO_FOLD, aperture=RadialAperture(12.0, 2.0)
    )
    optic.add_surface(
        index=5, radius=_R, thickness=_T, material="N-BK7", aperture=RadialAperture(8.0)
    )
    optic.add_surface(
        index=6, radius=-_R, thickness=sample_distance, aperture=RadialAperture(8.0)
    )
    optic.add_surface(index=7)
    optic.set_aperture(aperture_type="float_by_stop_size", value=8.0)
    optic.set_field_type(field_type="object_height")
    optic.add_field(y=3.0)
    optic.add_field(y=4.0)
    optic.add_wavelength(value=0.55, is_primary=True)
    return optic


def _fold(**kwargs):
    return fold_paths(
        imaging_optic(),
        illumination_optic(),
        _FOLD_IMAGING,
        _FOLD_ILLUMINATION,
        **kwargs,
    )


def _powers(result) -> dict[str, float]:
    return {name: det.total_flux_float for name, det in result.detectors.items()}


def _z(optic: Optic, index: int) -> float:
    return float(be.to_numpy(optic.surfaces.surfaces[index].geometry.cs.z))


class TestTailComparison:
    def test_matching_tails_report_nothing(self):
        assert (
            compare_tails(
                imaging_optic(), illumination_optic(), _FOLD_IMAGING, _FOLD_ILLUMINATION
            )
            == []
        )

    def test_drift_is_reported_not_absorbed(self):
        diffs = compare_tails(
            imaging_optic(), illumination_optic(sample_distance=20.4), 3, 4
        )
        assert len(diffs) == 1
        assert "sample distance" in diffs[0] and "20.4000" in diffs[0]
        _, report = fold_paths(imaging_optic(), illumination_optic(20.4), 3, 4)
        assert report.tail_differences == diffs
        assert "20.4000" in report.summary()


class TestGeometry:
    def test_mirror_hole_and_arm_placement(self):
        scene, report = _fold()
        mirror = scene.component_registry.get(MIRROR).component
        translation, rot = _get_transform(mirror.cs)
        # Optiland puts the first surface at z = 0 and the object in front.
        z_fold = _z(imaging_optic(), _FOLD_IMAGING)
        assert z_fold == pytest.approx(_T + _LENS_TO_FOLD)
        assert np.allclose(translation, [0.0, 0.0, z_fold])
        normal = rot @ np.array([0.0, 0.0, 1.0])
        assert np.allclose(normal, [math.sin(math.pi / 4), 0.0, math.cos(math.pi / 4)])
        geometry = mirror.geometry
        assert float(geometry.outer_radius) == pytest.approx(12.0)
        assert float(geometry.inner_radius) == pytest.approx(
            2.0 / math.cos(math.pi / 4)
        )
        assert float(geometry.inner_radius_y) == pytest.approx(2.0)
        assert report.hole_semi_axes == pytest.approx((2.0 * math.sqrt(2.0), 2.0))

        # The illumination relay lens lies on the -x axis at the mirror height.
        relay = scene.component_registry.get("ill.S2").component
        t_relay, r_relay = _get_transform(relay.cs)
        ill = illumination_optic()
        z_fold_ill = _z(ill, _FOLD_ILLUMINATION)
        assert np.allclose(t_relay, [_z(ill, 2) - z_fold_ill, 0.0, z_fold])
        assert np.allclose(r_relay @ np.array([0.0, 0.0, 1.0]), [1.0, 0.0, 0.0])
        source = scene.source_registry.get(ILLUMINATION)
        t_src, r_src = _get_transform(source.cs)
        assert np.allclose(t_src, [_z(ill, 0) - z_fold_ill, 0.0, z_fold])
        assert np.allclose(r_src @ np.array([0.0, 0.0, 1.0]), [1.0, 0.0, 0.0])
        assert float(source.inner_radius) == pytest.approx(3.0)
        assert float(source.aperture_radius) == pytest.approx(4.0)
        assert source.lambertian_cone is True

        # The shared tail comes from the imaging file and sits on the axis.
        assert report.tail.components == ["tail.S1", "tail.S2"]
        assert report.imaging_arm.components == ["img.S4", "img.S5"]
        assert report.illumination_arm.aperture_only == [1]
        assert set(report.detectors) == {CAMERA, SAMPLE, DUMP, RETURN}

    def test_physical_hole_is_circular_in_the_mirror_plane(self):
        scene, report = _fold(hole="physical")
        geometry = scene.component_registry.get(MIRROR).component.geometry
        assert float(geometry.inner_radius) == pytest.approx(2.0)
        assert float(geometry.inner_radius_y) == pytest.approx(2.0)
        assert report.hole_semi_axes == (2.0, 2.0)

    def test_tail_from_illumination_lands_on_the_same_axis(self):
        scene_a, _ = _fold(tail_from="imaging")
        scene_b, _ = _fold(tail_from="illumination")
        a_front = scene_a.component_registry.get("tail.S1").component
        b_back = scene_b.component_registry.get(
            "tail.S6"
        ).component  # same physical face
        t_a, r_a = _get_transform(a_front.cs)
        t_b, r_b = _get_transform(b_back.cs)
        assert np.allclose(t_a, t_b)
        # Opposite local orientation, opposite radius: the same surface.
        assert np.allclose(r_a @ np.array([0, 0, 1.0]), -(r_b @ np.array([0, 0, 1.0])))
        assert float(a_front.geometry.radius) == pytest.approx(
            -float(b_back.geometry.radius)
        )

    def test_fold_surface_must_be_an_aperture(self):
        with pytest.raises(ConversionError, match="air-to-air"):
            fold_paths(imaging_optic(), illumination_optic(), 1, _FOLD_ILLUMINATION)
        with pytest.raises(ValueError, match="inner surface"):
            fold_paths(imaging_optic(), illumination_optic(), 0, _FOLD_ILLUMINATION)


class TestEnergyFlow:
    def test_arms_stay_apart(self):
        scene, _ = _fold(illumination_flux=1.0, object_flux=1.0)
        results = trace_per_source(scene, 6000, seed=3, max_depth=24)
        assert set(results) == {"object_0", "object_1", ILLUMINATION}
        illumination = _powers(results[ILLUMINATION])
        # Folded onto the sample (most of the wide cone dies at the stop);
        # nothing reaches the camera directly.
        assert illumination[SAMPLE] > 0.01
        assert illumination[CAMERA] == 0.0
        # The hole leaks a little of the ring illumination straight through.
        assert illumination[DUMP] > 0.0
        on_axis = _powers(results["object_0"])
        # The source cone is matched to the (virtual) pupil, so most of the
        # object light passes the hole; the margin outside it is folded back
        # into the illumination arm, none of it lands on the sample.
        assert on_axis[CAMERA] > 0.5
        assert on_axis[RETURN] > 0.0
        assert on_axis[SAMPLE] == 0.0
        # The registry is intact afterwards.
        assert scene.source_names == ["object_0", "object_1", ILLUMINATION]

    def test_hole_shape_changes_the_camera_throughput(self):
        projected, _ = _fold(hole="projected")
        physical, _ = _fold(hole="physical")
        kwargs = {"seed": 5, "max_depth": 24, "sources": ["object_0"]}
        p_proj = _powers(trace_per_source(projected, 4000, **kwargs)["object_0"])
        p_phys = _powers(trace_per_source(physical, 4000, **kwargs)["object_0"])
        assert p_phys[CAMERA] < p_proj[CAMERA]
        assert p_phys[CAMERA] == pytest.approx(
            p_proj[CAMERA] * math.cos(math.pi / 4), rel=0.2
        )

    def test_json_round_trip_traces_identically(self, tmp_path):
        scene, _ = _fold()
        path = tmp_path / "fold.nsq.json"
        scene.to_json(path)
        restored = NSQScene.from_json(path)
        assert restored.component_names == scene.component_names
        a = _powers(scene.trace(num_rays=3000, seed=9, max_depth=24))
        b = _powers(restored.trace(num_rays=3000, seed=9, max_depth=24))
        assert a == pytest.approx(b)
        again = scene_from_dict(scene_to_dict(restored))
        assert again.source_names == scene.source_names
