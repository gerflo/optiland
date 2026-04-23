"""Tests for the catalog import/insertion pipeline."""

from __future__ import annotations

import shutil
from unittest.mock import MagicMock
from pathlib import Path

import pytest
import yaml

from optiland.materials import Material
from optiland.materials.material_file import MaterialFile

from optiland_gui.catalogs.insertion import record_to_insert_specs
from optiland_gui.catalogs.search import CatalogSearchQuery, CatalogSearchService
from optiland_gui.catalogs.schema import CatalogLensRecord, CatalogSource, LensSurfaceSpec
from optiland_gui.optiland_connector import OptilandConnector
from optiland_gui.services.surface_service import SurfaceService


def _mock_connector_with_optic(minimal_optic):
    conn = MagicMock()
    conn._optic = minimal_optic
    conn._capture_optic_state.return_value = {}
    conn._restore_optic_state.return_value = None
    conn._undo_redo_manager = MagicMock()
    conn.set_modified.return_value = None
    conn.opticChanged = MagicMock()
    conn.opticChanged.emit.return_value = None
    return conn


def _tmp_winlens_material_dir() -> Path:
    path = Path(".tmp_testdata") / "catalog_pipeline_winlens_material"
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)
    path.mkdir(parents=True, exist_ok=True)
    return path


class TestCatalogInsertionSpecs:
    def test_record_to_insert_specs_preserves_extra_geometry_data(self) -> None:
        record = CatalogLensRecord(
            catalog_id="thorlabs:al1815-c",
            manufacturer="Thorlabs",
            part_number="AL1815-C",
            product_name="Asphere",
            surfaces=[
                LensSurfaceSpec(
                    surface_type="even_asphere",
                    radius=11.65,
                    thickness=6.2,
                    material="S-LAH64",
                    conic=-1.1,
                    semi_diameter=9.0,
                    comment="AL1815-C S1",
                    extra_data={
                        "coefficients": [0.0, 3.69e-5, -1.28e-8],
                    },
                ),
                LensSurfaceSpec(
                    surface_type="toroidal",
                    radius="inf",
                    thickness=11.5,
                    material="Air",
                    conic=0.0,
                    semi_diameter=7.2,
                    comment="AL1815-C S2",
                    extra_data={
                        "radius_x": "inf",
                        "toroidal_coeffs_poly_y": [0.1, 0.2],
                    },
                ),
            ],
            source=CatalogSource(manufacturer="Thorlabs", source_type="zemax"),
        )

        surfaces, stop_offset = record_to_insert_specs(record)

        assert stop_offset is None
        assert surfaces[0]["surface_type"] == "even_asphere"
        assert surfaces[0]["coefficients"] == [0.0, 3.69e-5, -1.28e-8]
        assert surfaces[1]["surface_type"] == "toroidal"
        assert surfaces[1]["radius_x"] == float("inf")
        assert surfaces[1]["radius_y"] == float("inf")
        assert surfaces[1]["toroidal_coeffs_poly_y"] == [0.1, 0.2]

    def test_record_to_insert_specs_preserves_material_reference(self) -> None:
        record = CatalogLensRecord(
            catalog_id="winlens:wlte007",
            manufacturer="WinLens Library 2002",
            part_number="WLTE007",
            product_name="Tessar demo",
            surfaces=[
                LensSurfaceSpec(
                    surface_type="standard",
                    radius=12.0,
                    thickness=4.1,
                    material="BAFN10",
                    semi_diameter=8.0,
                    comment="Space 1",
                    extra_data={"material_catalog": "Schott"},
                )
            ],
            source=CatalogSource(
                manufacturer="WinLens Library 2002",
                source_type="winlens_spd",
            ),
        )

        surfaces, _stop_offset = record_to_insert_specs(record)

        assert surfaces[0]["material"] == "BAFN10"
        assert surfaces[0]["material_reference"] == "Schott"

    def test_record_to_insert_specs_formats_catalog_surface_comments_with_part_number(self) -> None:
        record = CatalogLensRecord(
            catalog_id="winlens:063823000",
            manufacturer="WinLens Library 2002",
            part_number="063823000",
            product_name="Plano-convex demo",
            surfaces=[
                LensSurfaceSpec(
                    surface_type="standard",
                    radius=51.212,
                    thickness=4.0,
                    material="N-BK7",
                    semi_diameter=12.7,
                    comment="Surf  1",
                ),
                LensSurfaceSpec(
                    surface_type="standard",
                    radius="inf",
                    thickness=0.0,
                    material="Air",
                    semi_diameter=12.7,
                    comment="Surface 2",
                ),
            ],
            source=CatalogSource(
                manufacturer="WinLens Library 2002",
                source_type="winlens_dat",
            ),
        )

        surfaces, _stop_offset = record_to_insert_specs(record)

        assert surfaces[0]["comment"] == "063823000 (S1)"
        assert surfaces[1]["comment"] == "063823000 (S2)"


class TestCatalogSurfaceInsertion:
    @pytest.fixture()
    def service(self, minimal_optic):
        return SurfaceService(_mock_connector_with_optic(minimal_optic))

    def test_insert_surface_sequence_preserves_even_asphere_parameters(self, service):
        service.insert_surface_sequence(
            1,
            [
                {
                    "surface_type": "even_asphere",
                    "radius": 11.65,
                    "thickness": 6.2,
                    "material": "S-LAH64",
                    "conic": -1.1,
                    "semi_diameter": 9.0,
                    "comment": "Inserted Asphere",
                    "coefficients": [0.0, 3.69e-5, -1.28e-8],
                }
            ],
        )

        surface = service._connector._optic.surfaces[1]
        assert surface.surface_type == "even_asphere"
        assert float(surface.geometry.radius) == pytest.approx(11.65)
        assert float(surface.geometry.k) == pytest.approx(-1.1)
        assert list(surface.geometry.coefficients) == pytest.approx(
            [0.0, 3.69e-5, -1.28e-8]
        )
        assert float(surface.aperture.r_max) == pytest.approx(9.0)

    def test_insert_surface_sequence_preserves_toroidal_parameters(self, service):
        service.insert_surface_sequence(
            1,
            [
                {
                    "surface_type": "toroidal",
                    "radius_y": 2.02,
                    "radius_x": float("inf"),
                    "conic": 0.0,
                    "thickness": 3.8,
                    "material": "N-BK7",
                    "semi_diameter": 2.0,
                    "comment": "Inserted Cyl Lens",
                    "toroidal_coeffs_poly_y": [0.0, 0.0],
                }
            ],
        )

        surface = service._connector._optic.surfaces[1]
        assert surface.surface_type == "toroidal"
        assert float(surface.geometry.R_yz) == pytest.approx(2.02)
        assert surface.geometry.R_rot == float("inf")
        assert list(surface.geometry.coeffs_poly_y) == pytest.approx([0.0, 0.0])
        assert float(surface.aperture.r_max) == pytest.approx(2.0)

    def test_insert_surface_sequence_uses_material_reference_for_winlens_glass(self, service):
        service.insert_surface_sequence(
            1,
            [
                {
                    "surface_type": "standard",
                    "radius": 20.0,
                    "thickness": 4.1,
                    "material": "BAFN10",
                    "material_reference": "Schott",
                    "semi_diameter": 8.0,
                    "comment": "Inserted WinLens Surface",
                }
            ],
        )

        surface = service._connector._optic.surfaces[1]
        assert surface.material_post.name in {"N-BAF10", "BAFN10"}
        assert surface.material_post.material_data["filename_no_ext"] in {"N-BAF10", "BAFN10"}
        assert surface.material_post.reference == "Schott"

    def test_insert_surface_sequence_rejects_unverified_winlens_material_mapping(self, service):
        with pytest.raises(ValueError, match="No matches found for material ZZ_UNKNOWN"):
            service.insert_surface_sequence(
                1,
                [
                    {
                        "surface_type": "standard",
                        "radius": 20.0,
                        "thickness": 4.1,
                        "material": "ZZ_UNKNOWN",
                        "material_reference": "Hoya",
                        "semi_diameter": 8.0,
                        "comment": "Inserted WinLens Surface",
                    }
                ],
            )

    def test_insert_surface_sequence_uses_imported_winlens_material_catalog(self, service):
        tmp_dir = _tmp_winlens_material_dir()
        database_root = Path(Material._filename).parent
        local_csv = database_root / "catalog_nk_winlens.csv"
        local_glass_root = database_root / "data-nk" / "glass" / "winlens"

        backup_csv = local_csv.read_bytes() if local_csv.exists() else None
        backup_glass_root = None
        if local_glass_root.exists():
            backup_glass_root = tmp_dir / "glass_winlens_backup"
            shutil.copytree(local_glass_root, backup_glass_root)

        hoya_dir = local_glass_root / "hoya"
        hoya_glass = hoya_dir / "ADC1.yml"
        try:
            if local_csv.exists():
                local_csv.unlink()
            if local_glass_root.exists():
                shutil.rmtree(local_glass_root)

            hoya_dir.mkdir(parents=True, exist_ok=True)
            hoya_glass.write_text(
                yaml.safe_dump(
                    {
                        "REFERENCES": "Test-only imported WinLens glass.",
                        "COMMENTS": "Synthetic direct WinLens import for pipeline coverage.",
                        "DATA": [
                            {
                                "type": "formula 3",
                                "wavelength_range": "0.36501 1.01398",
                                "coefficients": (
                                    "2.36274117 -0.0107297647 2 -0.0004333771 -2 "
                                    "0.0132729695 -4 -0.000607998162 -6 "
                                    "5.48245465e-05 -8"
                                ),
                            }
                        ],
                    },
                    sort_keys=False,
                    allow_unicode=False,
                ),
                encoding="utf-8",
            )
            specs = MaterialFile(str(hoya_glass))
            local_csv.write_text(
                (
                    "group,category_name,category_name_full,reference,name,filename,"
                    "min_wavelength,max_wavelength,filename_no_ext\n"
                    "glass,WinLens,WinLens imported Hoya,Hoya,ADC1,"
                    "glass/winlens/hoya/ADC1.yml,0.36501,1.01398,ADC1\n"
                ),
                encoding="utf-8",
            )
            Material._df = None

            service.insert_surface_sequence(
                1,
                [
                    {
                        "surface_type": "standard",
                        "radius": 20.0,
                        "thickness": 4.1,
                        "material": "ADC1",
                        "material_reference": "Hoya",
                        "semi_diameter": 8.0,
                        "comment": "Inserted Imported WinLens Surface",
                    }
                ],
            )

            surface = service._connector._optic.surfaces[1]
            assert surface.material_post.name == "ADC1"
            assert surface.material_post.reference == "Hoya"
            assert surface.material_post.material_data["filename"] == "glass/winlens/hoya/ADC1.yml"
            imported_index = surface.material_post.n(0.5875618).item()
            expected_index = specs.n(0.5875618).item()
            assert imported_index == pytest.approx(expected_index)
        finally:
            Material._df = None
            if local_csv.exists():
                local_csv.unlink()
            if local_glass_root.exists():
                shutil.rmtree(local_glass_root)
            if backup_csv is not None:
                local_csv.write_bytes(backup_csv)
            if backup_glass_root is not None and backup_glass_root.exists():
                shutil.copytree(backup_glass_root, local_glass_root)
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_insert_surface_sequence_preserves_existing_system_stop(self, service):
        optic = service._connector._optic
        original_stop_surface = optic.surfaces[2]

        service.insert_surface_sequence(
            3,
            [
                {
                    "surface_type": "standard",
                    "radius": 20.0,
                    "thickness": 3.0,
                    "material": "N-BK7",
                    "semi_diameter": 4.0,
                    "comment": "Catalog S1",
                },
                {
                    "surface_type": "standard",
                    "radius": -20.0,
                    "thickness": 0.0,
                    "material": "Air",
                    "semi_diameter": 4.0,
                    "comment": "Catalog S2",
                },
            ],
            stop_offset=0,
        )

        stop_surfaces = [surface for surface in optic.surfaces if surface.is_stop]
        assert stop_surfaces == [original_stop_surface]
        assert optic.surfaces.stop_index == optic.surfaces.index(original_stop_surface)

    def test_insert_catalog_lens_rejects_metadata_only_records(self) -> None:
        connector = MagicMock()
        connector._catalog_service = MagicMock()
        connector._surface_service = MagicMock()
        connector._catalog_service.get_record.return_value = CatalogLensRecord(
            catalog_id="excelitas:g063213000",
            manufacturer="Excelitas LINOS",
            part_number="G063213000",
            product_name="Achr. VIS ARB2; D=25.4; F=80; mounted",
            category="achromat",
            efl_mm=80.0,
            diameter_mm=25.4,
            source=CatalogSource(
                manufacturer="Excelitas LINOS",
                source_type="excelitas_shop_html",
            ),
        )
        connector._catalog_service.resolve_insertable_record.return_value = None

        with pytest.raises(ValueError, match="metadata-only"):
            OptilandConnector.insert_catalog_lens(connector, "excelitas:g063213000", 1, "after")

        connector._surface_service.insert_surface_sequence.assert_not_called()

    def test_insert_catalog_lens_uses_insertable_winlens_fallback_record(self) -> None:
        connector = MagicMock()
        connector._catalog_service = MagicMock()
        connector._surface_service = MagicMock()
        metadata_record = CatalogLensRecord(
            catalog_id="winlens:063213000",
            manufacturer="WinLens Library 2002",
            part_number="063213000",
            product_name="Achromat 80/25.4 ECO-Vers.-322 Achromat",
            category="achromat",
            efl_mm=80.0,
            diameter_mm=25.4,
            source=CatalogSource(
                manufacturer="WinLens Library 2002",
                source_type="winlens_dat",
            ),
        )
        optical_record = CatalogLensRecord(
            catalog_id="winlens:322307",
            manufacturer="WinLens Library 2002",
            part_number="322307",
            product_name="Achromat demo",
            category="achromat",
            surfaces=[
                LensSurfaceSpec(
                    surface_type="standard",
                    radius=25.0,
                    thickness=4.0,
                    material="N-BK7",
                    semi_diameter=12.7,
                    comment="Surface 1",
                )
            ],
            source=CatalogSource(
                manufacturer="WinLens Library 2002",
                source_type="winlens_spd",
            ),
        )
        connector._catalog_service.get_record.return_value = metadata_record
        connector._catalog_service.resolve_insertable_record.return_value = optical_record

        OptilandConnector.insert_catalog_lens(connector, "winlens:063213000", 1, "after")

        connector._surface_service.insert_surface_sequence.assert_called_once()
        assert (
            connector._surface_service.insert_surface_sequence.call_args.args[3]
            == metadata_record.part_number
        )
        assert (
            connector._surface_service.insert_surface_sequence.call_args.args[4]
            == "stock_part"
        )

    def test_insert_catalog_lens_reports_missing_winlens_surface_model_clearly(self) -> None:
        connector = MagicMock()
        connector._catalog_service = MagicMock()
        connector._surface_service = MagicMock()
        connector._catalog_service.get_record.return_value = CatalogLensRecord(
            catalog_id="winlens:063213000",
            manufacturer="WinLens Library 2002",
            part_number="063213000",
            product_name="Achromat 80/25.4 ECO-Vers.-322 Achromat",
            category="achromat",
            efl_mm=80.0,
            diameter_mm=25.4,
            source=CatalogSource(
                manufacturer="WinLens Library 2002",
                source_type="winlens_dat",
            ),
        )
        connector._catalog_service.resolve_insertable_record.return_value = None

        with pytest.raises(ValueError, match="No optical surface model was found"):
            OptilandConnector.insert_catalog_lens(connector, "winlens:063213000", 1, "after")

        connector._surface_service.insert_surface_sequence.assert_not_called()

    def test_insert_catalog_lens_uses_paraxial_surrogate_for_winlens_family_metadata(self) -> None:
        connector = MagicMock()
        connector._catalog_service = MagicMock()
        connector._surface_service = MagicMock()
        metadata_record = CatalogLensRecord(
            catalog_id="excelitas linos:g063213000",
            manufacturer="Excelitas LINOS",
            part_number="G063213000",
            product_name="Achr. VIS ARB2; D=25.4; F=80; mounted",
            category="achromat",
            efl_mm=80.0,
            diameter_mm=25.4,
            source=CatalogSource(
                manufacturer="Excelitas LINOS",
                source_type="excelitas_shop_html",
            ),
        )
        surrogate_record = CatalogLensRecord(
            catalog_id="winlens library 2002:063213000",
            manufacturer="WinLens Library 2002",
            part_number="063213000",
            product_name="Achromat 80/25.4 ECO-Vers.-322 Achromat",
            category="achromat",
            efl_mm=80.0,
            diameter_mm=25.4,
            surfaces=[
                LensSurfaceSpec(
                    surface_type="paraxial",
                    thickness=0.0,
                    material="Air",
                    semi_diameter=12.7,
                    comment="WinLens surrogate",
                    extra_data={"f": 80.0},
                )
            ],
            source=CatalogSource(
                manufacturer="WinLens Library 2002",
                source_type="winlens_dat",
            ),
        )
        connector._catalog_service.get_record.return_value = metadata_record
        connector._catalog_service.resolve_insertable_record.return_value = surrogate_record

        OptilandConnector.insert_catalog_lens(connector, "excelitas linos:g063213000", 1, "after")

        connector._surface_service.insert_surface_sequence.assert_called_once()
        inserted_surfaces = connector._surface_service.insert_surface_sequence.call_args.args[1]
        assert inserted_surfaces[0]["surface_type"] == "paraxial"
        assert inserted_surfaces[0]["f"] == 80.0
        assert inserted_surfaces[0]["semi_diameter"] == 12.7
        assert (
            connector._surface_service.insert_surface_sequence.call_args.args[3]
            == metadata_record.part_number
        )
        assert (
            connector._surface_service.insert_surface_sequence.call_args.args[4]
            == "stock_part"
        )


class TestCatalogSearchNormalization:
    def test_full_text_search_ignores_part_number_separators(self) -> None:
        record = CatalogLensRecord(
            catalog_id="excelitas:g063213000",
            manufacturer="Excelitas LINOS",
            part_number="G063213000",
            product_name="Achr. VIS ARB2; D=25.4; F=80; mounted",
            category="achromat",
            source=CatalogSource(
                manufacturer="Excelitas LINOS",
                source_type="excelitas_shop_html",
            ),
        )

        matches = CatalogSearchService().search(
            [record],
            CatalogSearchQuery(text="G063-213-000"),
        )

        assert [item.part_number for item in matches] == ["G063213000"]

    def test_part_number_filter_ignores_part_number_separators(self) -> None:
        record = CatalogLensRecord(
            catalog_id="excelitas:g063-213-000",
            manufacturer="Excelitas LINOS",
            part_number="G063-213-000",
            product_name="Achr. VIS ARB2; D=25.4; F=80; mounted",
            category="achromat",
            source=CatalogSource(
                manufacturer="Excelitas LINOS",
                source_type="excelitas_shop_html",
            ),
        )

        matches = CatalogSearchService().search(
            [record],
            CatalogSearchQuery(part_number="G063213000"),
        )

        assert [item.part_number for item in matches] == ["G063-213-000"]

    def test_part_number_filter_treats_leading_g_prefix_as_optional(self) -> None:
        record = CatalogLensRecord(
            catalog_id="winlens:063213000",
            manufacturer="WinLens Library 2002",
            part_number="063213000",
            product_name="Achromat f = 80/25.4 mm",
            category="achromat",
            source=CatalogSource(
                manufacturer="WinLens Library 2002",
                source_type="winlens_dat",
            ),
        )

        matches = CatalogSearchService().search(
            [record],
            CatalogSearchQuery(part_number="G063213000"),
        )

        assert [item.part_number for item in matches] == ["063213000"]

    def test_availability_filter_matches_legacy_records(self) -> None:
        legacy_record = CatalogLensRecord(
            catalog_id="winlens:322307",
            manufacturer="WinLens Library 2002",
            part_number="322307",
            product_name="Achromat f = 80/25.4 mm",
            category="achromat",
            availability_status="legacy",
            source=CatalogSource(
                manufacturer="WinLens Library 2002",
                source_type="winlens_dat",
            ),
        )
        unknown_record = CatalogLensRecord(
            catalog_id="winlens:317703",
            manufacturer="WinLens Library 2002",
            part_number="317703",
            product_name="Asphere demo",
            category="asphere",
            availability_status="unknown",
            source=CatalogSource(
                manufacturer="WinLens Library 2002",
                source_type="winlens_spd",
            ),
        )

        matches = CatalogSearchService().search(
            [legacy_record, unknown_record],
            CatalogSearchQuery(availability_text="legacy"),
        )

        assert [item.part_number for item in matches] == ["322307"]
