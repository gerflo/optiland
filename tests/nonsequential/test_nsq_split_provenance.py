"""Branch provenance of bounded splitting in the NSQ event log.

A spawned transmit child used to appear in ``ray_paths["events"]`` only
through its later hits, under a fresh ray id with no link to the ray it was
split from. It now starts with a ``"split"`` event whose ``parent_id``
names that ray, and follows its root's in-sample decision under
``record_paths: int``.

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
    CollimatedSourceConfig,
    IrradianceDetectorConfig,
    NSQMaterial,
    NSQScene,
    RefractiveComponent,
    Spectrum,
)
from optiland.nonsequential.components.geometry.analytic.plane import (
    FinitePlaneGeometry,
)
from optiland.nonsequential.ir.scene_ir import SamplingPolicy
from optiland.nonsequential.path_recording import (
    _EVENT_DTYPE,
    ColumnarPathLog,
    PathRecorder,
)
from optiland.nonsequential.visualization.rays import _paths_from_events
from optiland.samples.nonsequential import SPLITTER_Z, beam_splitter_scene

NUM_RAYS = 512
SEED = 11


@pytest.fixture(autouse=True)
def _numpy_backend():
    be.set_backend("numpy")
    yield
    be.set_backend("numpy")


def _split_trace(record_paths=True, num_rays=NUM_RAYS):
    scene = beam_splitter_scene()
    scene.sampling_policy = SamplingPolicy(split_depth=1)
    return scene.trace(num_rays=num_rays, seed=SEED, record_paths=record_paths)


class TestEventFormat:
    def test_parent_id_column_is_part_of_the_contract(self):
        assert "parent_id" in _EVENT_DTYPE.names
        assert _EVENT_DTYPE["parent_id"] == np.int64

    def test_events_without_a_parent_record_minus_one(self):
        result = beam_splitter_scene().trace(num_rays=64, seed=SEED, record_paths=True)
        events = result.ray_paths["events"]
        assert not (events["event_type"] == "split").any()
        assert (events["parent_id"] == -1).all()

    def test_columnar_log_records_the_given_parent_ids(self):
        from optiland.nonsequential.ray_bundle import NSQRayBundle

        n = 3
        ones = np.ones(n)
        rays = NSQRayBundle(
            x=ones,
            y=ones,
            z=ones,
            L=ones,
            M=ones,
            N=ones,
            flux=ones,
            wavelength=ones,
            n_current=ones,
            bounce=np.zeros(n, dtype=np.int32),
            alive=np.ones(n, dtype=bool),
            ray_id=np.array([10, 11, 12]),
        )
        log = ColumnarPathLog()
        log.log_event(
            3, np.array([True, False, True]), rays, None, "s", np.array([1, 2, 3])
        )
        events = log.to_events()
        assert list(events["event_type"]) == ["split", "split"]
        assert list(events["parent_id"]) == [1, 3]
        assert list(events["ray_id"]) == [10, 12]


class TestSplitProvenance:
    def test_each_source_ray_spawns_one_child_linked_by_parent_id(self):
        result = _split_trace()
        events = result.ray_paths["events"]
        splits = events[events["event_type"] == "split"]
        births = events[events["event_type"] == "birth"]

        assert len(births) == NUM_RAYS
        assert len(splits) == NUM_RAYS
        assert (splits["component_name"] == "splitter").all()
        # Every parent is a source-born ray, each split exactly once.
        np.testing.assert_array_equal(np.sort(splits["parent_id"]), births["ray_id"])
        # Children carry fresh ids, are never "born", and are the only rows
        # with a parent.
        child_ids = splits["ray_id"]
        assert not np.isin(child_ids, births["ray_id"]).any()
        assert len(np.unique(child_ids)) == NUM_RAYS
        assert (events[events["event_type"] != "split"]["parent_id"] == -1).all()

    def test_split_event_records_the_child_starting_state(self):
        result = _split_trace()
        events = result.ray_paths["events"]
        splits = events[events["event_type"] == "split"]
        # On the tilted plane through (0, 0, SPLITTER_Z): x + z == SPLITTER_Z.
        np.testing.assert_allclose(splits["x"] + splits["z"], SPLITTER_Z, atol=1e-9)
        # Transmit children keep the +z direction and carry T = 0.5 of the
        # parent flux (1 W / NUM_RAYS).
        np.testing.assert_allclose(splits["N"], 1.0, atol=1e-12)
        np.testing.assert_allclose(splits["flux"], 0.5 / NUM_RAYS, rtol=1e-9)
        # The child's hit count starts where the parent's ended.
        assert (splits["bounce"] == 1).all()

    def test_child_paths_start_at_the_split(self):
        result = _split_trace()
        events = result.ray_paths["events"]
        child_ids = set(events[events["event_type"] == "split"]["ray_id"])
        paths = _paths_from_events(events, 0)
        assert len(paths) == 2 * NUM_RAYS
        seen_children = 0
        for path in paths:
            first = str(path["event_type"][0])
            if int(path["ray_id"][0]) in child_ids:
                assert first == "split"
                seen_children += 1
            else:
                assert first == "birth"
            # Every path ends on a detector (hit) -- nothing escapes here.
            assert str(path["event_type"][-1]) == "hit"
        assert seen_children == NUM_RAYS

    def test_recorded_subset_keeps_children_with_their_parents(self):
        result = _split_trace(record_paths=100)
        events = result.ray_paths["events"]
        births = set(events[events["event_type"] == "birth"]["ray_id"])
        splits = events[events["event_type"] == "split"]
        assert 0 < len(births) < NUM_RAYS
        # A child is recorded iff its parent is: same set, one child each.
        assert set(splits["parent_id"]) == births
        assert len(splits) == len(births)
        # Every hit belongs either to a recorded parent or to its child.
        child_ids = set(splits["ray_id"])
        hits = events[events["event_type"] == "hit"]
        assert set(hits["ray_id"]) <= births | child_ids

    def test_root_of_follows_nested_splits(self):
        recorder = PathRecorder(True, 10, seed=1)
        recorder._register_children(np.array([20, 21]), np.array([3, 4]))
        recorder._register_children(np.array([30]), np.array([20]))
        np.testing.assert_array_equal(
            recorder.root_of(np.array([3, 20, 21, 30, 7])), [3, 3, 4, 3, 7]
        )


def _tir_scene() -> NSQScene:
    """Glass-to-vacuum plane hit from inside at 50 deg: total internal
    reflection, so the forced transmit child would carry zero flux. The
    glass is an ideal, non-absorbing n = 1.5 so no Beer-Lambert loss
    blurs the energy balance."""
    glass = NSQMaterial(optiland_material=IdealMaterial(n=1.5))
    angle = math.radians(50.0)
    z_source = 1.0
    scene = NSQScene()
    scene.add_source(
        "S",
        CoordinateSystem(
            x=-(SPLITTER_Z - z_source) * math.tan(angle), z=z_source, ry=angle
        ),
        CollimatedSourceConfig(
            spectrum=Spectrum.monochromatic(0.55),
            total_flux=1.0,
            aperture_radius=0.5,
            medium=glass,
        ),
    )
    scene.add_component(
        "exit_face",
        RefractiveComponent(
            cs=CoordinateSystem(z=SPLITTER_Z),
            geometry=FinitePlaneGeometry(aperture_radius=20.0),
            material_front=glass,
            material_back=VACUUM,
            name="exit_face",
        ),
    )
    scene.add_detector(
        "back",
        CoordinateSystem(z=0.0),
        IrradianceDetectorConfig(width=60, height=60, num_pixels_x=4, num_pixels_y=4),
    )
    scene.add_detector(
        "beyond",
        CoordinateSystem(z=2 * SPLITTER_Z),
        IrradianceDetectorConfig(width=60, height=60, num_pixels_x=4, num_pixels_y=4),
    )
    return scene


class TestTotalInternalReflection:
    def test_zero_flux_transmit_child_is_not_spawned(self):
        scene = _tir_scene()
        scene.sampling_policy = SamplingPolicy(split_depth=1)
        result = scene.trace(num_rays=128, seed=SEED, record_paths=True)
        events = result.ray_paths["events"]

        assert not (events["event_type"] == "split").any()
        assert result.detectors["back"].total_flux_float == pytest.approx(1.0)
        assert result.detectors["beyond"].total_flux_float == 0.0
        assert result.detectors["back"].num_rays_hit == 128
        assert result.flux_conservation_error < 1e-9

    def test_roulette_also_reflects_everything(self):
        result = _tir_scene().trace(num_rays=128, seed=SEED)
        assert result.detectors["back"].total_flux_float == pytest.approx(1.0)
        assert result.detectors["beyond"].num_rays_hit == 0
