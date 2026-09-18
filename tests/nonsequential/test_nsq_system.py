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
    OLSYS_FORMAT_VERSION,
    FoldSettings,
    MultiAxisSystem,
    OpticalPath,
    fold_system,
    optiland_version,
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

    def test_rebuild_without_paths_raises(self):
        plain = MultiAxisSystem(NSQScene())
        with pytest.raises(RuntimeError, match="no optical paths"):
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


class TestUnfoldedSystems:
    def test_from_optic_converts_a_single_path_in_place(self):
        system = MultiAxisSystem.from_optic(imaging_optic(), "Camera")
        assert system.fold is None and system.path_names == ["Camera"]
        path = system.path("Camera")
        assert path.role == ""
        assert {"S1", "S1.rim"} <= set(path.components)
        assert path.sources == ["field_0", "field_1"]  # object-height fields
        assert path.detectors == ["image"]
        assert set(path.sources) == set(system.scene.source_names)
        assert system.scene.detector_names == ["image"]
        assert system.paths_for_component("S1") == ["Camera"]
        report = system.last_report
        assert not report.is_fold
        assert "unfolded system: 1 path(s)" in report.summary()
        assert list(report.arms) == ["Camera"]

    def test_angle_fields_become_collimated_beams_that_reach_the_image(self):
        from optiland.samples.objectives import CookeTriplet

        system = MultiAxisSystem.from_optic(CookeTriplet().to_dict(), "Cooke")
        assert system.path("Cooke").sources == ["field_0", "field_1", "field_2"]
        result = system.scene.trace(num_rays=3000, max_depth=24, seed=1)
        assert result.total_flux_in == pytest.approx(3.0)
        assert result.detectors["image"].total_flux_float > 1.5

    def test_the_path_name_defaults_to_the_optic_name(self):
        optic = imaging_optic()
        optic.name = "Beobachtung"
        assert MultiAxisSystem.from_optic(optic, rebuild=False).path_names == [
            "Beobachtung"
        ]
        optic.name = ""
        assert MultiAxisSystem.from_optic(optic, rebuild=False).path_names == ["Path 1"]

    def test_several_unfolded_paths_get_prefixes(self):
        system = MultiAxisSystem(
            NSQScene(),
            [
                OpticalPath("A", imaging_optic().to_dict()),
                OpticalPath("B", illumination_optic().to_dict()),
            ],
        )
        report = system.rebuild()
        assert "A.S1" in system.path("A").components
        # Surface 1 of the illumination design is air-to-air: only its rim.
        assert {"B.S2", "B.S1.rim"} <= set(system.path("B").components)
        assert system.path("A").sources == ["A.field_0", "A.field_1"]
        assert system.path("B").detectors == ["B.image"]
        assert system.paths_for_component("B.image") == ["B"]
        assert set(report.arms) == {"A", "B"}

    def test_rebuild_without_paths_is_refused(self):
        with pytest.raises(RuntimeError, match="no optical paths"):
            MultiAxisSystem(NSQScene()).rebuild()

    def test_a_failed_conversion_leaves_the_scene_alone(self):
        from optiland.nonsequential.convert import ConversionError
        from optiland.samples.objectives import CookeTriplet

        system = MultiAxisSystem.from_optic(imaging_optic(), "A")
        names = system.scene.component_names
        members = list(system.path("A").components)
        bad = CookeTriplet()
        bad.set_field_type(field_type="object_height")  # but object at infinity
        system.set_path_optic("A", bad)
        with pytest.raises(ConversionError, match="infinity"):
            system.rebuild()
        assert system.scene.component_names == names
        assert system.path("A").components == members


class TestFileVersions:
    def test_the_file_records_format_and_application_versions(self, tmp_path):
        system, _ = _system()
        path = tmp_path / "v.olsys"
        system.to_json(path, application=("Optiland GUI", "0.3.0"))
        data = json.loads(path.read_text(encoding="utf-8"))
        assert list(data)[:3] == [
            "olsys_format_version",
            "application",
            "optiland_version",
        ]
        assert data["olsys_format_version"] == OLSYS_FORMAT_VERSION == 1
        assert data["application"] == {"name": "Optiland GUI", "version": "0.3.0"}
        assert data["optiland_version"] == optiland_version()
        back = MultiAxisSystem.from_json(path)
        assert back.application == {"name": "Optiland GUI", "version": "0.3.0"}
        assert back.path_names == system.path_names
        assert system.application is None  # never read from a file

    def test_the_library_is_the_default_application(self):
        data = _system()[0].to_dict()
        assert data["application"] == {
            "name": "optiland",
            "version": optiland_version(),
        }

    def test_files_from_before_the_version_keys_still_load(self):
        data = _system()[0].to_dict()
        for key in ("olsys_format_version", "application", "optiland_version"):
            del data[key]
        back = MultiAxisSystem.from_dict(data)
        assert back.application is None
        assert back.path_names == ["Camera path", "Ring illumination"]

    def test_a_newer_format_version_is_refused(self):
        data = _system()[0].to_dict()
        data["olsys_format_version"] = OLSYS_FORMAT_VERSION + 1
        data["application"] = {"name": "Optiland GUI", "version": "9.0.0"}
        with pytest.raises(ValueError, match=r"written by Optiland GUI 9.0.0"):
            MultiAxisSystem.from_dict(data)
        for bad in ("1", 0, True, 1.0):
            data["olsys_format_version"] = bad
            with pytest.raises(ValueError, match="olsys_format_version"):
                MultiAxisSystem.from_dict(data)
