"""Tests for saving a designed element as a user stock-catalog entry.

Covers the CatalogService persistence path, the SurfaceService element
extraction, and the AddToCatalogDialog record assembly.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

import pytest


def _workspace_tmp_dir() -> Path:
    path = Path("tests") / "_tmp_add_to_catalog" / uuid4().hex
    path.mkdir(parents=True, exist_ok=True)
    return path


def _sample_record_data(manufacturer: str = "MyVendor", part: str = "MV-100") -> dict:
    return {
        "manufacturer": manufacturer,
        "part_number": part,
        "product_name": f"{manufacturer} Test Singlet",
        "category": "singlet",
        "efl_mm": 100.0,
        "diameter_mm": 25.4,
        "surfaces": [
            {
                "surface_type": "standard",
                "radius": 50.0,
                "thickness": 5.0,
                "material": "N-BK7",
                "conic": 0.0,
                "semi_diameter": 12.7,
            },
            {
                "surface_type": "standard",
                "radius": -50.0,
                "thickness": 45.0,
                "material": "Air",
                "conic": 0.0,
                "semi_diameter": 12.7,
            },
        ],
    }


class TestAddManualRecord:
    def _make_service(self, monkeypatch, tmp_path: Path):
        from optiland_gui.services.catalog_service import CatalogService

        monkeypatch.setattr(
            "optiland_gui.catalogs.storage.QStandardPaths.writableLocation",
            lambda *_args, **_kwargs: str(tmp_path),
        )
        return CatalogService(MagicMock(), session=MagicMock())

    def test_persists_record_for_new_manufacturer(self, monkeypatch) -> None:
        tmp_path = _workspace_tmp_dir()
        try:
            service = self._make_service(monkeypatch, tmp_path)
            record = service.add_manual_record(_sample_record_data())

            assert record.catalog_id == "myvendor:mv-100"
            assert "MyVendor" in service.get_manufacturers()
            assert service.get_record("myvendor:mv-100") is not None

            cache_file = tmp_path / "catalogs" / "myvendor.json"
            assert cache_file.exists()
            payload = json.loads(cache_file.read_text(encoding="utf-8"))
            assert payload["manufacturer"] == "MyVendor"
            assert len(payload["records"]) == 1
            assert payload["records"][0]["source"]["source_type"] == "user"
        finally:
            shutil.rmtree(tmp_path.parent, ignore_errors=True)

    def test_second_record_merges_into_same_cache(self, monkeypatch) -> None:
        tmp_path = _workspace_tmp_dir()
        try:
            service = self._make_service(monkeypatch, tmp_path)
            service.add_manual_record(_sample_record_data(part="MV-100"))
            service.add_manual_record(_sample_record_data(part="MV-200"))

            cache_file = tmp_path / "catalogs" / "myvendor.json"
            payload = json.loads(cache_file.read_text(encoding="utf-8"))
            parts = {item["part_number"] for item in payload["records"]}
            assert parts == {"MV-100", "MV-200"}
        finally:
            shutil.rmtree(tmp_path.parent, ignore_errors=True)

    def test_saved_record_is_insertable(self, monkeypatch) -> None:
        from optiland_gui.catalogs.insertion import record_to_insert_specs

        tmp_path = _workspace_tmp_dir()
        try:
            service = self._make_service(monkeypatch, tmp_path)
            record = service.add_manual_record(_sample_record_data())
            surfaces, stop_offset = record_to_insert_specs(record)

            assert len(surfaces) == 2
            assert surfaces[0]["material"] == "N-BK7"
            assert stop_offset is None
        finally:
            shutil.rmtree(tmp_path.parent, ignore_errors=True)

    def test_add_manual_record_skips_full_refresh(self, monkeypatch) -> None:
        """Regression: saving one element triggered a full catalog reload and
        the WinLens fuzzy-match rebuild (75 s on a large library), freezing
        the GUI. A manual add must stay incremental."""
        tmp_path = _workspace_tmp_dir()
        try:
            service = self._make_service(monkeypatch, tmp_path)
            winlens_calls: list[bool] = []
            reload_calls: list[bool] = []
            monkeypatch.setattr(
                service,
                "_refresh_winlens_record_links",
                lambda: winlens_calls.append(True),
            )
            monkeypatch.setattr(
                service, "_reload_all", lambda: reload_calls.append(True)
            )

            record = service.add_manual_record(_sample_record_data())

            assert winlens_calls == []
            assert reload_calls == []
            # The record is still immediately visible in memory and on disk.
            assert service.get_record(record.catalog_id) is not None
            assert "MyVendor" in service.get_manufacturers()
            assert (tmp_path / "catalogs" / "myvendor.json").exists()
        finally:
            shutil.rmtree(tmp_path.parent, ignore_errors=True)

    @pytest.mark.parametrize(
        "override",
        [
            {"manufacturer": ""},
            {"part_number": ""},
            {"surfaces": []},
        ],
    )
    def test_rejects_incomplete_records(self, monkeypatch, override) -> None:
        tmp_path = _workspace_tmp_dir()
        try:
            service = self._make_service(monkeypatch, tmp_path)
            data = {**_sample_record_data(), **override}
            with pytest.raises(ValueError):
                service.add_manual_record(data)
        finally:
            shutil.rmtree(tmp_path.parent, ignore_errors=True)


class TestElementCatalogDraft:
    def _make_service(self, minimal_optic):
        from optiland_gui.services.surface_service import SurfaceService

        connector = MagicMock()
        connector._optic = minimal_optic
        connector.DEFAULT_WAVELENGTH_UM = 0.55
        return SurfaceService(connector)

    @pytest.mark.parametrize("row", [1, 2])
    def test_element_rows_span_the_ungrouped_singlet(self, qapp, minimal_optic, row):
        service = self._make_service(minimal_optic)
        assert service.get_element_rows(row) == [1, 2]

    def test_draft_extracts_singlet_surfaces(self, qapp, minimal_optic) -> None:
        service = self._make_service(minimal_optic)
        draft = service.get_element_catalog_draft(1)

        surfaces = draft["surfaces"]
        assert len(surfaces) == 2
        assert surfaces[0]["material"] == "N-BK7"
        assert surfaces[0]["radius"] == pytest.approx(50.0)
        assert surfaces[0]["thickness"] == pytest.approx(5.0)
        assert surfaces[1]["material"] == "Air"
        assert surfaces[1]["radius"] == pytest.approx(-50.0)
        # Row 2 (back surface) is the stop in the minimal_optic fixture.
        assert draft["stop_surface_offset"] == 1
        assert draft["material_summary"] == "N-BK7"
        assert draft["center_thickness_mm"] == pytest.approx(5.0)
        if draft["efl_mm"] is not None:
            assert draft["efl_mm"] == pytest.approx(48.7, abs=1.0)

    def test_draft_is_json_serializable(self, qapp, minimal_optic) -> None:
        service = self._make_service(minimal_optic)
        draft = service.get_element_catalog_draft(1)
        json.dumps(draft)  # must not raise

    def test_object_row_is_rejected(self, qapp, minimal_optic) -> None:
        service = self._make_service(minimal_optic)
        with pytest.raises(ValueError):
            service.get_element_catalog_draft(0)


class TestAddToCatalogDialog:
    def _make_dialog(self, connector=None, draft=None):
        from optiland_gui.widgets.add_to_catalog_dialog import AddToCatalogDialog

        connector = connector or MagicMock()
        connector.get_catalog_manufacturers.return_value = ["Edmund", "Thorlabs"]
        draft = draft or {
            "surfaces": _sample_record_data()["surfaces"],
            "stop_surface_offset": None,
            "product_name": "",
            "diameter_mm": 25.4,
            "center_thickness_mm": 5.0,
            "material_summary": "N-BK7",
            "efl_mm": 100.0,
        }
        return AddToCatalogDialog(connector, draft), connector

    def test_save_disabled_until_required_fields_set(self, qapp) -> None:
        from PySide6.QtWidgets import QDialogButtonBox

        dialog, _ = self._make_dialog()
        save = dialog._buttons.button(QDialogButtonBox.StandardButton.Save)
        assert not save.isEnabled()

        dialog.manufacturer_combo.setCurrentText("MyVendor")
        assert not save.isEnabled()
        dialog.part_number_edit.setText("MV-100")
        assert save.isEnabled()

    def test_build_record_data_merges_draft_and_fields(self, qapp) -> None:
        dialog, _ = self._make_dialog()
        dialog.manufacturer_combo.setCurrentText("MyVendor")
        dialog.part_number_edit.setText("MV-100")
        dialog.category_edit.setText("achromat")

        data = dialog.build_record_data()
        assert data["manufacturer"] == "MyVendor"
        assert data["part_number"] == "MV-100"
        assert data["product_name"] == "MV-100"  # falls back to part number
        assert data["category"] == "achromat"
        assert data["efl_mm"] == 100.0
        assert len(data["surfaces"]) == 2

    def test_accept_persists_via_connector(self, qapp) -> None:
        dialog, connector = self._make_dialog()
        connector.add_catalog_record.return_value = "myvendor:mv-100"
        dialog.manufacturer_combo.setCurrentText("MyVendor")
        dialog.part_number_edit.setText("MV-100")

        dialog.accept()

        connector.add_catalog_record.assert_called_once()
        assert dialog.saved_catalog_id == "myvendor:mv-100"

    def test_accept_shows_error_and_stays_open_on_failure(self, qapp) -> None:
        dialog, connector = self._make_dialog()
        connector.add_catalog_record.side_effect = ValueError("boom")
        dialog.manufacturer_combo.setCurrentText("MyVendor")
        dialog.part_number_edit.setText("MV-100")

        dialog.accept()

        assert dialog.saved_catalog_id is None
        assert dialog.result() != dialog.DialogCode.Accepted


class TestIdealMaterialRoundtrip:
    """Regression: a cataloged element built from IdealMaterial surfaces
    (e.g. a schematic eye) failed to insert with 'No matches found for
    material Ideal n=...', because the display label went through the
    glass-catalog lookup instead of being recognized as an ideal index.
    """

    def _make_mouse_eye_optic(self):
        import optiland.backend as be
        from optiland.materials import IdealMaterial
        from optiland.optic import Optic

        optic = Optic()
        optic.surfaces.add(index=0, radius=be.inf, thickness=be.inf)
        optic.surfaces.add(
            index=1, radius=1.155, thickness=2.032, material=IdealMaterial(n=1.6778)
        )
        optic.surfaces.add(
            index=2, radius=-1.248, thickness=0.452, material=IdealMaterial(n=1.3376),
            is_stop=True,
        )
        optic.surfaces.add(index=3, radius=be.inf, thickness=0.0)
        optic.set_aperture(aperture_type="EPD", value=2.0)
        optic.fields.set_type("angle")
        optic.fields.add(y=0.0)
        optic.wavelengths.add(value=0.55, is_primary=True)
        optic.updater.update()
        return optic

    def _make_service(self, optic):
        from optiland_gui.services.surface_service import SurfaceService

        connector = MagicMock()
        connector._optic = optic
        connector.DEFAULT_WAVELENGTH_UM = 0.55
        connector._capture_optic_state.return_value = {}
        return SurfaceService(connector)

    def test_extracted_ideal_material_reinserts(self, qapp) -> None:
        import pytest as _pytest

        from optiland.materials import IdealMaterial
        from optiland_gui.catalogs.insertion import record_to_insert_specs
        from optiland_gui.catalogs.schema import CatalogLensRecord

        source = self._make_mouse_eye_optic()
        draft = self._make_service(source).get_element_catalog_draft(1)
        assert draft["surfaces"][0]["material"].startswith("Ideal n=")

        record = CatalogLensRecord.from_dict(
            {
                "manufacturer": "Imedos",
                "part_number": "xx-001",
                "product_name": "Mouse model",
                "surfaces": draft["surfaces"],
                "stop_surface_offset": draft["stop_surface_offset"],
            }
        )
        specs, stop_offset = record_to_insert_specs(record)

        import optiland.backend as be
        from optiland.optic import Optic

        target = Optic()
        target.surfaces.add(index=0, radius=be.inf, thickness=be.inf)
        target.surfaces.add(index=1, radius=be.inf, thickness=10.0, is_stop=True)
        target.surfaces.add(index=2, radius=be.inf, thickness=0.0)
        target.set_aperture(aperture_type="EPD", value=2.0)
        target.fields.set_type("angle")
        target.fields.add(y=0.0)
        target.wavelengths.add(value=0.55, is_primary=True)
        target.updater.update()

        service = self._make_service(target)
        service.insert_surface_sequence(2, specs, stop_offset, "xx-001", "stock_part")

        assert target.surfaces.num_surfaces == 5
        inserted = target.surfaces.surfaces[2]
        assert isinstance(inserted.material_post, IdealMaterial)
        n = float(inserted.material_post.n(0.55))
        assert n == _pytest.approx(1.6778, abs=1e-6)

    def test_parse_ideal_index_label_variants(self, qapp) -> None:
        from optiland_gui.services.surface_service import SurfaceService

        parse = SurfaceService._parse_ideal_index
        assert parse("Ideal n=1.6778") == pytest.approx(1.6778)
        assert parse("ideal n = 1.5") == pytest.approx(1.5)
        assert parse("1.5") == pytest.approx(1.5)
        assert parse("N-BK7") is None
        assert parse("Mirror") is None
        assert parse("inf") is None
        assert parse("-1.5") is None

    def test_mirror_material_is_normalized_for_insertion(self, qapp) -> None:
        """The factory's mirror special-case compares against exact lowercase."""
        import optiland.backend as be
        from optiland.optic import Optic

        target = Optic()
        target.surfaces.add(index=0, radius=be.inf, thickness=be.inf)
        target.surfaces.add(index=1, radius=be.inf, thickness=10.0, is_stop=True)
        target.surfaces.add(index=2, radius=be.inf, thickness=0.0)
        target.set_aperture(aperture_type="EPD", value=2.0)
        target.fields.set_type("angle")
        target.fields.add(y=0.0)
        target.wavelengths.add(value=0.55, is_primary=True)
        target.updater.update()

        service = self._make_service(target)
        specs = [
            {
                "surface_type": "standard",
                "radius": -100.0,
                "thickness": -10.0,
                "material": "Mirror",
                "conic": 0.0,
                "semi_diameter": 5.0,
                "comment": "Fold mirror",
            }
        ]
        service.insert_surface_sequence(2, specs, None, "mirror", "stock_part")

        inserted = target.surfaces.surfaces[2]
        assert inserted.interaction_model.is_reflective
