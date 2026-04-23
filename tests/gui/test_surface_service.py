"""Tests for SurfaceService."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from optiland_gui.services.file_service import SpecialFloatEncoder
from optiland_gui.services.surface_service import SurfaceService


@pytest.fixture()
def mock_connector(minimal_optic):
    """A minimal mock connector wired to a real Optic."""
    conn = MagicMock()
    conn._optic = minimal_optic
    conn._capture_optic_state.return_value = {}
    conn._restore_optic_state.return_value = None
    conn._undo_redo_manager = MagicMock()
    conn.set_modified.return_value = None
    conn.opticChanged = MagicMock()
    conn.opticChanged.emit.return_value = None
    # Column constants
    conn.COL_COMMENT = 1
    conn.COL_RADIUS = 2
    conn.COL_THICKNESS = 3
    conn.COL_MATERIAL = 4
    conn.COL_CONIC = 5
    conn.COL_SEMI_DIAMETER = 6
    return conn


@pytest.fixture()
def service(mock_connector):
    return SurfaceService(mock_connector)


class TestSurfaceService:
    def test_add_surface_increases_count(self, service, mock_connector):
        initial = service.get_surface_count()
        service.add_surface()
        assert service.get_surface_count() == initial + 1
        mock_connector.opticChanged.emit.assert_called()

    def test_remove_surface_decreases_count(self, service, mock_connector):
        initial = service.get_surface_count()
        # Remove surface at row 1 (first real lens surface)
        service.remove_surface(1)
        assert service.get_surface_count() == initial - 1
        mock_connector.opticChanged.emit.assert_called()

    def test_update_radius(self, service, mock_connector):
        # Surface 1 radius should update without raising
        service.set_surface_data(1, mock_connector.COL_RADIUS, "75.0")
        optic = mock_connector._optic
        radius = optic.surface_group.surfaces[1].geometry.radius
        assert abs(float(radius) - 75.0) < 1e-6
        mock_connector.opticChanged.emit.assert_called()

    def test_type_conversion_standard_to_biconic(self, service, mock_connector):
        surface = mock_connector._optic.surface_group.surfaces[1]
        assert surface.surface_type != "biconic"
        service.set_surface_type(1, "biconic")
        surface = mock_connector._optic.surface_group.surfaces[1]
        assert surface.surface_type == "biconic"

    def test_get_geometry_types_contains_standard(self, service):
        types = service.get_geometry_types()
        assert isinstance(types, list)
        assert len(types) > 0
        assert "standard" in types

    def test_unknown_surface_type_ignored(self, service, mock_connector):
        # Should not raise and should not change the surface
        original_type = mock_connector._optic.surface_group.surfaces[1].surface_type
        service.set_surface_type(1, "not_a_real_type")
        assert mock_connector._optic.surface_group.surfaces[1].surface_type == original_type

    def test_even_asphere_coefficients_remain_json_serializable(
        self, service, mock_connector
    ):
        import json

        service.set_surface_type(1, "even_asphere")
        service.set_surface_geometry_params(1, {"Coefficients": "[0.1, 0.01, 0.001]"})

        geometry = mock_connector._optic.surface_group.surfaces[1].geometry
        assert isinstance(geometry.coefficients, list)
        assert geometry.coefficients == [0.1, 0.01, 0.001]

        payload = mock_connector._optic.to_dict()
        encoded = json.dumps(payload, cls=SpecialFloatEncoder)
        assert '"coefficients": [\n' in encoded or '"coefficients": [' in encoded

    def test_create_rename_and_ungroup_surface_element(self, service, mock_connector):
        group_id = service.create_surface_group([1, 2], "L1", "lens")

        assert group_id is not None
        assert service.get_group_rows(1) == [1, 2]
        assert mock_connector._optic.surfaces.surfaces[1].group_name == "L1"
        assert mock_connector._optic.surfaces.surfaces[2].group_role == "lens"

        service.rename_surface_group(1, "Front Group")
        assert mock_connector._optic.surfaces.surfaces[1].group_name == "Front Group"
        assert mock_connector._optic.surfaces.surfaces[2].group_name == "Front Group"

        service.ungroup_surface_element(1)
        assert service.get_group_rows(1) == []
        assert mock_connector._optic.surfaces.surfaces[1].group_id is None
        assert mock_connector._optic.surfaces.surfaces[2].group_name is None

    def test_insert_surface_sequence_assigns_group_metadata(self, service):
        service.insert_surface_sequence(
            2,
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
            group_name="Edmund 12345",
            group_role="stock_part",
        )

        inserted = service._connector._optic.surfaces.surfaces[2:4]
        assert inserted[0].group_id is not None
        assert inserted[0].group_id == inserted[1].group_id
        assert inserted[0].group_name == "Edmund 12345"
        assert inserted[1].group_role == "stock_part"

    def test_duplicate_surface_element_clones_block_with_new_group_id(
        self, service, mock_connector
    ):
        group_id = service.create_surface_group([1, 2], "L1", "lens")

        new_rows = service.duplicate_surface_element(1)

        assert new_rows == [3, 4]
        duplicated = [mock_connector._optic.surfaces.surfaces[row] for row in new_rows]
        assert duplicated[0].group_id != group_id
        assert duplicated[0].group_id == duplicated[1].group_id
        assert duplicated[0].group_name == "L1"
        assert duplicated[1].group_role == "lens"
        assert not duplicated[0].is_stop
        assert not duplicated[1].is_stop

    def test_move_surface_element_repositions_group_and_preserves_stop(
        self, service, mock_connector
    ):
        service.add_surface()
        service.create_surface_group([1, 2], "L1", "lens")

        moved_rows = service.move_surface_element(1, 4)

        assert moved_rows == [2, 3]
        moved = [mock_connector._optic.surfaces.surfaces[row] for row in moved_rows]
        assert [surface.group_name for surface in moved] == ["L1", "L1"]
        assert [surface.group_role for surface in moved] == ["lens", "lens"]
        assert mock_connector._optic.surfaces.stop_index == moved_rows[-1]

    def test_flip_surface_element_reverses_singlet_surface_order(self, service, mock_connector):
        service.create_surface_group([1, 2], "L1", "lens")

        flipped_rows = service.flip_surface_element(1)

        assert flipped_rows == [1, 2]
        flipped = [mock_connector._optic.surfaces.surfaces[row] for row in flipped_rows]
        assert [float(surface.geometry.radius) for surface in flipped] == [50.0, -50.0]
        assert [float(surface.thickness) for surface in flipped] == [5.0, 45.0]
        assert flipped[0].material_post.to_dict()["name"] == "N-BK7"
        assert flipped[1].material_post.to_dict()["type"] == "IdealMaterial"
        assert mock_connector._optic.surfaces.stop_index == 1

    def test_flip_surface_element_reverses_cemented_doublet_interfaces(
        self, service, mock_connector
    ):
        from optiland.materials import Material as OptilandMaterial

        optic = mock_connector._optic
        optic.surfaces.surfaces[1].geometry.radius = 30.0
        optic.surfaces.surfaces[1].thickness = 4.0
        optic.surfaces.surfaces[1].material_post = OptilandMaterial("N-BK7")
        optic.surfaces.surfaces[1].is_stop = False

        optic.surfaces.surfaces[2].geometry.radius = -20.0
        optic.surfaces.surfaces[2].thickness = 2.0
        optic.surfaces.surfaces[2].material_post = OptilandMaterial("N-SF5")
        optic.surfaces.surfaces[2].is_stop = False

        optic.surfaces.add(index=3, radius=-60.0, thickness=45.0, material="air")
        optic.updater.update()
        service.create_surface_group([1, 2, 3], "D1", "doublet")

        flipped_rows = service.flip_surface_element(1)

        assert flipped_rows == [1, 2, 3]
        flipped = [optic.surfaces.surfaces[row] for row in flipped_rows]
        assert [float(surface.geometry.radius) for surface in flipped] == [60.0, 20.0, -30.0]
        assert [float(surface.thickness) for surface in flipped] == [2.0, 4.0, 45.0]
        assert flipped[0].material_post.to_dict()["name"] == "N-SF5"
        assert flipped[1].material_post.to_dict()["name"] == "N-BK7"
        assert flipped[2].material_post.to_dict()["type"] == "IdealMaterial"
