"""A multi-axis system: folded scene plus its named optical paths.

The System view needs to know which sequential designs a scene was folded
from, so a path can be activated in the sequential tools, renamed, edited
and folded again.

Kramer Harrison, 2026
"""

from __future__ import annotations

import json

import pytest

import optiland.backend as be
from optiland.nonsequential import NSQScene
from optiland.nonsequential.fold import CAMERA, MIRROR, SAMPLE
from optiland.nonsequential.system import (
    FoldSettings,
    MultiAxisSystem,
    OpticalPath,
    fold_system,
)
from tests.nonsequential.test_nsq_fold_paths import (
    _FOLD_ILLUMINATION,
    _FOLD_IMAGING,
    illumination_optic,
    imaging_optic,
)


@pytest.fixture(autouse=True)
def _numpy_backend():
    be.set_backend("numpy")
    yield
    be.set_backend("numpy")


def _system():
    imaging = imaging_optic()
    imaging.name = "Camera path"
    illumination = illumination_optic()
    illumination.name = "Ring illumination"
    return fold_system(imaging, illumination, _FOLD_IMAGING, _FOLD_ILLUMINATION)


class TestFoldSystem:
    def test_paths_are_named_after_the_optics_and_know_their_members(self):
        system, report = _system()
        assert system.path_names == ["Camera path", "Ring illumination"]
        camera = system.path("Camera path")
        ring = system.path("Ring illumination")
        assert camera.role == "imaging" and ring.role == "illumination"
        assert set(camera.components) >= set(report.tail.components) | {MIRROR}
        assert set(camera.components) >= set(report.imaging_arm.components)
        assert set(ring.components) >= set(report.illumination_arm.components)
        assert camera.sources == ["object_0", "object_1"]
        assert ring.sources == ["illumination"]
        assert camera.detectors == [CAMERA]
        assert SAMPLE in ring.detectors
        assert system.fold.imaging == "Camera path"
        assert system.fold.fold_illumination == _FOLD_ILLUMINATION

    def test_default_names_and_duplicate_names(self):
        system, _ = fold_system(
            imaging_optic(), illumination_optic(), _FOLD_IMAGING, _FOLD_ILLUMINATION
        )
        assert system.path_names == ["Imaging", "Illumination"]
        same, _ = fold_system(
            imaging_optic(),
            illumination_optic(),
            _FOLD_IMAGING,
            _FOLD_ILLUMINATION,
            imaging_name="X",
            illumination_name="X",
        )
        assert same.path_names == ["X", "X (illumination)"]

    def test_paths_for_component(self):
        system, _ = _system()
        assert system.paths_for_component(MIRROR) == [
            "Camera path",
            "Ring illumination",
        ]
        assert system.paths_for_component("tail.S1") == [
            "Camera path",
            "Ring illumination",
        ]
        assert system.paths_for_component("img.S4") == ["Camera path"]
        assert system.paths_for_component("ill.S2") == ["Ring illumination"]
        assert system.paths_for_component("illumination") == ["Ring illumination"]
        assert system.paths_for_component("nothing") == []


class TestPathsEditing:
    def test_rename_keeps_fold_settings_consistent(self):
        system, _ = _system()
        system.rename_path("Camera path", "Beobachtung")
        assert system.path_names == ["Beobachtung", "Ring illumination"]
        assert system.fold.imaging == "Beobachtung"
        with pytest.raises(ValueError, match="already exists"):
            system.rename_path("Ring illumination", "Beobachtung")
        with pytest.raises(ValueError, match="empty"):
            system.rename_path("Ring illumination", "  ")
        with pytest.raises(KeyError):
            system.rename_path("missing", "x")
        # Rebuilding still works under the new name.
        system.rebuild()

    def test_editing_a_path_and_rebuilding_changes_the_scene(self):
        system, _ = _system()
        before = system.scene.component_registry.get("img.S4").component
        r_before = float(be.to_numpy(before.geometry.radius))

        optic = system.path("Camera path").build_optic()
        optic.set_radius(2.0 * r_before, 4)
        system.set_path_optic("Camera path", optic)
        report = system.rebuild()

        after = system.scene.component_registry.get("img.S4").component
        assert float(be.to_numpy(after.geometry.radius)) == pytest.approx(
            2.0 * r_before
        )
        assert after is not before
        assert report.tail_differences == []
        assert system.last_report is report

    def test_rebuild_without_fold_settings_raises(self):
        plain = MultiAxisSystem(NSQScene())
        with pytest.raises(RuntimeError, match="not folded"):
            plain.rebuild()
        assert plain.path_names == []
        assert plain.paths_for_component("x") == []

    def test_duplicate_path_names_are_rejected(self):
        with pytest.raises(ValueError, match="unique"):
            MultiAxisSystem(
                NSQScene(),
                [OpticalPath("a", {}), OpticalPath("a", {})],
            )


class TestSerialization:
    def test_round_trip_keeps_paths_fold_and_scene(self, tmp_path):
        system, _ = _system()
        system.rename_path("Ring illumination", "LED ring")
        path = tmp_path / "system.olsys"
        system.to_json(path)

        restored = MultiAxisSystem.from_json(path)
        assert restored.path_names == ["Camera path", "LED ring"]
        assert restored.fold == system.fold
        assert isinstance(restored.fold, FoldSettings)
        assert (
            restored.path("LED ring").components == system.path("LED ring").components
        )
        assert restored.scene.component_names == system.scene.component_names
        # The stored sequential design is complete: it rebuilds the same scene.
        rebuilt = MultiAxisSystem.from_json(path)
        rebuilt.rebuild()
        assert rebuilt.scene.component_names == system.scene.component_names

    def test_a_system_file_is_also_a_plain_scene_file(self, tmp_path):
        system, _ = _system()
        path = tmp_path / "system.olsys"
        system.to_json(path)
        scene = NSQScene.from_json(path)
        assert scene.component_names == system.scene.component_names
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["nsq_schema_version"] == 1
        assert [p["name"] for p in data["paths"]] == system.path_names
        assert data["fold"]["lossless"] == "glass"

    def test_a_plain_scene_file_loads_without_paths(self, tmp_path):
        from optiland.samples.nonsequential import beam_splitter_scene

        path = tmp_path / "scene.json"
        beam_splitter_scene().to_json(path)
        system = MultiAxisSystem.from_json(path)
        assert system.paths == [] and system.fold is None
        assert set(system.scene.detector_names) == {"transmitted", "reflected"}

    def test_unknown_lossless_policy_is_rejected(self):
        fold = FoldSettings("a", "b", 1, 1, lossless="shiny")
        with pytest.raises(ValueError, match="lossless"):
            fold.fold_kwargs()
