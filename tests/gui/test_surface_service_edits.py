"""Regression tests for LDE cell-edit parsing and paraxial surfaces.

Found via a real user session:
(1) typing a thickness with a German decimal comma ("97,1") raised
    ValueError and reverted the edit, and
(2) any paraxial surface loaded from file crashed every LDE refresh with
    AttributeError: 'Surface' object has no attribute 'f' — the focal
    length lives on the ThinLensInteractionModel, but the GUI read the
    legacy loose ``surface.f`` attribute.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import optiland.backend as be
from optiland.interactions import (
    RefractiveReflectiveModel,
    ThinLensInteractionModel,
)
from optiland.optic import Optic
from optiland_gui.services.surface_service import SurfaceService

COL_TYPE = 0
COL_COMMENT = 1
COL_RADIUS = 2
COL_THICKNESS = 3
COL_MATERIAL = 4
COL_CONIC = 5
COL_SEMI_DIAMETER = 6


def _make_connector(optic: Optic) -> MagicMock:
    connector = MagicMock()
    connector._optic = optic
    connector.DEFAULT_WAVELENGTH_UM = 0.55
    connector._capture_optic_state.return_value = {}
    connector.COL_TYPE = COL_TYPE
    connector.COL_COMMENT = COL_COMMENT
    connector.COL_RADIUS = COL_RADIUS
    connector.COL_THICKNESS = COL_THICKNESS
    connector.COL_MATERIAL = COL_MATERIAL
    connector.COL_CONIC = COL_CONIC
    connector.COL_SEMI_DIAMETER = COL_SEMI_DIAMETER
    return connector


def _make_singlet() -> Optic:
    optic = Optic()
    optic.surfaces.add(index=0, radius=be.inf, thickness=be.inf)
    optic.surfaces.add(index=1, radius=50.0, thickness=5.0, material="N-BK7")
    optic.surfaces.add(index=2, radius=-50.0, thickness=45.0, is_stop=True)
    optic.surfaces.add(index=3, radius=be.inf, thickness=0.0)
    optic.set_aperture(aperture_type="EPD", value=10.0)
    optic.fields.set_type("angle")
    optic.fields.add(y=0.0)
    optic.wavelengths.add(value=0.55, is_primary=True)
    optic.updater.update()
    return optic


def _make_paraxial_system() -> Optic:
    optic = Optic()
    optic.surfaces.add(index=0, radius=be.inf, thickness=be.inf)
    optic.surfaces.add(
        index=1, surface_type="paraxial", f=100.0, thickness=100.0, is_stop=True
    )
    optic.surfaces.add(index=2, radius=be.inf, thickness=0.0)
    optic.set_aperture(aperture_type="EPD", value=10.0)
    optic.fields.set_type("angle")
    optic.fields.add(y=0.0)
    optic.wavelengths.add(value=0.55, is_primary=True)
    optic.updater.update()
    return optic


class TestDecimalCommaParsing:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("97,1", 97.1),
            ("97.1", 97.1),
            ("1,234.5", 1234.5),
            ("-0,25", -0.25),
            ("inf", float("inf")),
        ],
    )
    def test_parse_user_float(self, text: str, expected: float) -> None:
        assert SurfaceService._parse_user_float(text) == expected

    def test_parse_user_float_rejects_garbage(self) -> None:
        with pytest.raises(ValueError):
            SurfaceService._parse_user_float("abc")

    def test_thickness_edit_accepts_decimal_comma(self, qapp) -> None:
        optic = _make_singlet()
        service = SurfaceService(_make_connector(optic))

        service.set_surface_data(1, COL_THICKNESS, "97,1")

        thickness = float(be.to_numpy(optic.surfaces.get_thickness(1)[0]))
        assert thickness == pytest.approx(97.1)

    def test_radius_edit_accepts_decimal_comma(self, qapp) -> None:
        optic = _make_singlet()
        service = SurfaceService(_make_connector(optic))

        service.set_surface_data(1, COL_RADIUS, "51,5")

        assert float(be.to_numpy(optic.surfaces.surfaces[1].geometry.radius)) == (
            pytest.approx(51.5)
        )


class TestParaxialSurfaceEdits:
    def test_radius_column_reads_focal_length_without_crashing(self, qapp) -> None:
        """Regression: loaded paraxial surfaces have no ``surface.f``; the
        LDE refresh crashed with AttributeError on every repaint."""
        optic = _make_paraxial_system()
        service = SurfaceService(_make_connector(optic))

        value = service.get_surface_data(1, COL_RADIUS)

        assert value == "100.0000"

    def test_radius_edit_writes_to_interaction_model(self, qapp) -> None:
        """Editing the focal length must reach the model the ray trace uses,
        not a dead ``surface.f`` attribute."""
        optic = _make_paraxial_system()
        service = SurfaceService(_make_connector(optic))

        service.set_surface_data(1, COL_RADIUS, "50")

        model = optic.surfaces.surfaces[1].interaction_model
        assert isinstance(model, ThinLensInteractionModel)
        assert float(be.to_numpy(model.f)) == pytest.approx(50.0)
        assert service.get_surface_data(1, COL_RADIUS) == "50.0000"

    def test_type_conversion_swaps_interaction_model(self, qapp) -> None:
        optic = _make_singlet()
        service = SurfaceService(_make_connector(optic))

        service.set_surface_type(1, "paraxial")
        surface = optic.surfaces.surfaces[1]
        assert surface.surface_type == "paraxial"
        assert isinstance(surface.interaction_model, ThinLensInteractionModel)
        # The LDE radius column works right after the conversion.
        assert service.get_surface_data(1, COL_RADIUS) is not None

        service.set_surface_type(1, "standard")
        surface = optic.surfaces.surfaces[1]
        assert isinstance(surface.interaction_model, RefractiveReflectiveModel)
