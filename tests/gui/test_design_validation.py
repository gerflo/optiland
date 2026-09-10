"""Tests for on-load design-file validation and offered corrections.

Derived from defects found in real user files: impossible apertures,
thickness/position contradictions, glass-filled gaps inside grouped
elements, and stock parts without physical apertures.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from optiland_gui.design_validation import (
    ValidationFinding,
    apply_design_fixes,
    validate_design,
)


def _cs(z: float) -> dict:
    return {"x": 0.0, "y": 0.0, "z": z, "rx": 0.0, "ry": 0.0, "rz": 0.0,
            "reference_cs": None}


def _air() -> dict:
    return {"type": "IdealMaterial",
            "propagation_model": {"class": "HomogeneousPropagation"},
            "index": 1.0, "absorp": 0.0}


def _glass(name: str = "N-BK7") -> dict:
    return {"type": "Material",
            "propagation_model": {"class": "HomogeneousPropagation"},
            "filename": None, "name": name, "reference": None, "catalog": None,
            "match_policy": "warn", "robust_search": None,
            "min_wavelength": None, "max_wavelength": None}


def _surface(z: float, thickness: float, *, radius: float = float("inf"),
             conic: float = 0.0, material: dict | None = None,
             aperture: float | None = None, group_id: str | None = None,
             group_role: str | None = None, comment: str = "") -> dict:
    geo_type = "StandardGeometry" if radius != float("inf") else "Plane"
    geometry: dict = {"type": geo_type, "cs": _cs(z), "radius": radius}
    if geo_type == "StandardGeometry":
        geometry["conic"] = conic
    surface = {
        "type": "Surface",
        "surface_type": "standard",
        "thickness": thickness,
        "geometry": geometry,
        "material_post": material or _air(),
        "is_stop": False,
        "comment": comment,
        "group_id": group_id,
        "group_name": group_id,
        "group_role": group_role,
        "interaction_model": {"type": "RefractiveReflectiveModel",
                              "is_reflective": False, "coating": None,
                              "bsdf": None},
    }
    if aperture is not None:
        surface["aperture"] = {"type": "RadialAperture", "r_max": aperture,
                               "r_min": 0.0}
    return surface


def _design(surfaces: list[dict]) -> dict:
    return {"surface_group": {"surfaces": surfaces}}


def _clean_design() -> dict:
    return _design([
        _surface(0.0, 20.0, comment="Object"),
        _surface(20.0, 5.0, radius=50.0, material=_glass(), aperture=10.0,
                 comment="Front"),
        _surface(25.0, 40.0, radius=-50.0, aperture=10.0, comment="Back"),
        _surface(65.0, 0.0, comment="Image"),
    ])


class TestValidateDesign:
    def test_clean_design_has_no_findings(self) -> None:
        assert validate_design(_clean_design()) == []

    def test_detects_aperture_beyond_sag_domain(self) -> None:
        design = _clean_design()
        # |R| = 1.463 but aperture r_max = 1.5: cap wider than the sphere.
        design["surface_group"]["surfaces"][1]["geometry"]["radius"] = -1.463
        design["surface_group"]["surfaces"][1]["aperture"]["r_max"] = 1.5

        findings = validate_design(design)
        codes = [f.code for f in findings]
        assert "aperture_exceeds_sag_domain" in codes
        finding = next(f for f in findings if f.code == "aperture_exceeds_sag_domain")
        assert finding.severity == "error"
        assert finding.apply_by_default
        assert finding.fix_data["r_max"] < 1.463

    def test_detects_thickness_position_mismatch(self) -> None:
        design = _clean_design()
        design["surface_group"]["surfaces"][2]["thickness"] = 90.0  # gap is 40

        findings = validate_design(design)
        assert [f.code for f in findings] == ["thickness_position_mismatch"]
        assert findings[0].surface_index == 2

    def test_detects_glass_gap_inside_grouped_element(self) -> None:
        design = _design([
            _surface(0.0, 20.0, comment="Object"),
            _surface(20.0, 4.0, radius=60.0, material=_glass(), aperture=12.7,
                     group_id="doublet", comment="S1"),
            _surface(24.0, 22.9, material=_glass(), aperture=1.75,
                     comment="Lochspiegel"),
            _surface(46.9, 2.5, radius=-45.0, material=_glass("SF5"),
                     aperture=12.7, group_id="doublet", comment="S2"),
            _surface(49.4, 0.0, comment="Image"),
        ])

        findings = validate_design(design)
        codes = [f.code for f in findings]
        assert "glass_gap_in_foreign_element" in codes
        finding = next(f for f in findings if f.code == "glass_gap_in_foreign_element")
        assert finding.surface_index == 2
        assert not finding.apply_by_default  # design decision, opt-in fix

    def test_detects_stock_part_without_aperture_once_per_group(self) -> None:
        design = _clean_design()
        for i in (1, 2):
            surface = design["surface_group"]["surfaces"][i]
            surface.pop("aperture")
            surface["group_id"] = "lens1"
            surface["group_role"] = "stock_part"

        findings = validate_design(design)
        stock = [f for f in findings if f.code == "stock_part_missing_aperture"]
        assert len(stock) == 1
        assert stock[0].severity == "info"
        assert not stock[0].fixable


class TestApplyDesignFixes:
    def test_aperture_clamped_to_domain(self) -> None:
        design = _clean_design()
        design["surface_group"]["surfaces"][1]["geometry"]["radius"] = -1.463
        design["surface_group"]["surfaces"][1]["aperture"]["r_max"] = 1.5
        findings = validate_design(design)

        fixed = apply_design_fixes(design, findings)

        r_max = fixed["surface_group"]["surfaces"][1]["aperture"]["r_max"]
        assert r_max < 1.463
        assert validate_design(fixed) == []
        # original untouched
        assert design["surface_group"]["surfaces"][1]["aperture"]["r_max"] == 1.5

    def test_positions_recomputed_from_thickness(self) -> None:
        design = _clean_design()
        design["surface_group"]["surfaces"][2]["thickness"] = 90.0
        findings = validate_design(design)

        fixed = apply_design_fixes(design, findings)

        surfaces = fixed["surface_group"]["surfaces"]
        assert surfaces[3]["geometry"]["cs"]["z"] == pytest.approx(115.0)
        assert validate_design(fixed) == []

    def test_glass_gap_fix_sets_air(self) -> None:
        design = _design([
            _surface(0.0, 20.0),
            _surface(20.0, 4.0, radius=60.0, material=_glass(), aperture=12.7,
                     group_id="doublet"),
            _surface(24.0, 22.9, material=_glass(), aperture=1.75),
            _surface(46.9, 2.5, radius=-45.0, material=_glass("SF5"),
                     aperture=12.7, group_id="doublet"),
            _surface(49.4, 0.0),
        ])
        findings = validate_design(design)

        fixed = apply_design_fixes(design, findings)

        material = fixed["surface_group"]["surfaces"][2]["material_post"]
        assert material["type"] == "IdealMaterial"
        assert material["index"] == 1.0

    def test_unfixable_findings_are_ignored(self) -> None:
        design = _clean_design()
        finding = ValidationFinding(
            code="stock_part_missing_aperture", severity="info",
            surface_index=1, message="x",
        )
        assert apply_design_fixes(design, [finding]) == design


class TestFileServiceIntegration:
    def _make_connector(self, monkeypatch):
        from optiland_gui.optiland_connector import OptilandConnector

        monkeypatch.setattr(
            "optiland_gui.optiland_connector.CatalogService",
            lambda connector: MagicMock(),
        )
        monkeypatch.setattr(
            "optiland_gui.optiland_connector.MaterialCatalogService",
            lambda connector: MagicMock(),
        )
        return OptilandConnector()

    def _write_mismatched_file(self, connector, tmp_path) -> str:
        """A file whose stored thickness (30) contradicts its positions (20)."""
        data = connector._capture_optic_state()
        data["surface_group"]["surfaces"][1]["thickness"] = 30.0
        filepath = tmp_path / "mismatch.json"
        filepath.write_text(json.dumps(data), encoding="utf-8")
        return str(filepath)

    def test_without_handler_file_loads_unchanged(self, qapp, monkeypatch, tmp_path):
        connector = self._make_connector(monkeypatch)
        filepath = self._write_mismatched_file(connector, tmp_path)

        connector.load_optic_from_file(filepath)

        import numpy as np
        thickness = float(np.asarray(connector._optic.surfaces.get_thickness(1)[0]))
        assert thickness == pytest.approx(20.0)  # positions win, no fix
        assert connector.has_unsaved_changes() is False

    def test_handler_fixes_are_applied_and_marked_unsaved(
        self, qapp, monkeypatch, tmp_path
    ):
        connector = self._make_connector(monkeypatch)
        filepath = self._write_mismatched_file(connector, tmp_path)

        def handler(data, path):  # noqa: ANN001
            findings = validate_design(data)
            assert findings, "expected a thickness/position finding"
            return apply_design_fixes(data, findings), True

        connector.design_validation_handler = handler
        connector.load_optic_from_file(filepath)

        import numpy as np
        thickness = float(np.asarray(connector._optic.surfaces.get_thickness(1)[0]))
        assert thickness == pytest.approx(30.0)  # fix applied: thickness wins
        assert connector.has_unsaved_changes() is True  # must be saved to persist

    def test_failing_handler_does_not_block_loading(self, qapp, monkeypatch, tmp_path):
        connector = self._make_connector(monkeypatch)
        filepath = self._write_mismatched_file(connector, tmp_path)
        connector.design_validation_handler = MagicMock(side_effect=RuntimeError("x"))

        connector.load_optic_from_file(filepath)

        assert connector._optic.surfaces.num_surfaces == 3


class TestDesignValidationDialog:
    def _findings(self):
        return [
            ValidationFinding(
                code="aperture_exceeds_sag_domain", severity="error",
                surface_index=1, message="aperture too wide",
                fix_description="clamp", apply_by_default=True,
                fix_data={"r_max": 1.4},
            ),
            ValidationFinding(
                code="glass_gap_in_foreign_element", severity="warning",
                surface_index=2, message="glass gap",
                fix_description="set air", apply_by_default=False,
            ),
            ValidationFinding(
                code="stock_part_missing_aperture", severity="info",
                surface_index=3, message="no aperture",
            ),
        ]

    def test_default_check_states_follow_findings(self, qapp) -> None:
        from optiland_gui.widgets.design_validation_dialog import (
            DesignValidationDialog,
        )

        dialog = DesignValidationDialog(self._findings(), "demo.json")
        checked = {f.code for f in dialog.checked_findings()}
        assert checked == {"aperture_exceeds_sag_domain"}

    def test_accept_collects_checked_findings(self, qapp) -> None:
        from optiland_gui.widgets.design_validation_dialog import (
            DesignValidationDialog,
        )

        dialog = DesignValidationDialog(self._findings(), "demo.json")
        for checkbox in dialog._checkboxes.values():
            checkbox.setChecked(True)
        dialog.accept()

        codes = {f.code for f in dialog.selected_findings}
        assert codes == {
            "aperture_exceeds_sag_domain",
            "glass_gap_in_foreign_element",
        }
