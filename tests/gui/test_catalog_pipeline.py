"""Tests for the catalog import/insertion pipeline."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from optiland_gui.catalogs.insertion import record_to_insert_specs
from optiland_gui.catalogs.schema import CatalogLensRecord, CatalogSource, LensSurfaceSpec
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
