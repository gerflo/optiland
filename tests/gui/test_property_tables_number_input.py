"""Regression tests: numbers typed into the field and wavelength tables.

Found in the user's session log (2026-09-22): typing ``3,5`` into the
System Properties field table printed ``Invalid data in fields table row
4: could not convert string to float: '3,5'`` to the console and reloaded
the table, so the edit vanished without any message in the GUI. The Lens
Data Editor already accepts a decimal comma; the field and wavelength
tables parsed with a bare ``float()``.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest
from PySide6.QtWidgets import QTableWidgetItem

import optiland.backend as be
from optiland.optic import Optic
from optiland_gui.optiland_connector import OptilandConnector
from optiland_gui.system_properties_panel import FieldsEditor, WavelengthsEditor


def _optic() -> Optic:
    optic = Optic()
    optic.surfaces.add(index=0, radius=be.inf, thickness=10.0)
    optic.surfaces.add(index=1, radius=be.inf, thickness=20.0, is_stop=True)
    optic.surfaces.add(index=2, radius=be.inf, thickness=0.0)
    optic.set_aperture(aperture_type="EPD", value=4.0)
    optic.fields.set_type("object_height")
    optic.fields.add(y=0.0)
    optic.fields.add(y=1.0)
    optic.wavelengths.add(value=0.55, is_primary=True)
    optic.updater.update()
    return optic


@pytest.fixture()
def connector(qapp, monkeypatch) -> OptilandConnector:
    monkeypatch.setattr(
        "optiland_gui.optiland_connector.CatalogService",
        lambda connector: MagicMock(),
    )
    monkeypatch.setattr(
        "optiland_gui.optiland_connector.MaterialCatalogService",
        lambda connector: MagicMock(),
    )
    connector = OptilandConnector()
    connector.toast_manager = MagicMock()
    connector.load_optic_from_object(_optic())
    return connector


def _type(table, row: int, col: int, text: str) -> None:  # noqa: ANN001
    table.setItem(row, col, QTableWidgetItem(text))


def test_field_table_accepts_a_decimal_comma(connector) -> None:
    editor = FieldsEditor(connector)
    editor.load_data()
    _type(editor.tableFields, 1, 1, "3,5")

    editor.apply_table_field_changes()

    assert connector.get_optic().fields.fields[1].y == pytest.approx(3.5)


def test_invalid_field_entry_is_reported_as_a_warning(connector, caplog) -> None:
    editor = FieldsEditor(connector)
    editor.load_data()
    _type(editor.tableFields, 1, 1, "abc")

    with caplog.at_level(logging.WARNING, logger="optiland_gui"):
        editor.apply_table_field_changes()

    assert connector.get_optic().fields.fields[1].y == pytest.approx(1.0)
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert warnings, "an invalid entry must reach the user, not only stdout"
    assert "row 2" in warnings[0].getMessage()
    assert "abc" in warnings[0].getMessage()


def test_wavelength_table_accepts_a_decimal_comma(connector) -> None:
    editor = WavelengthsEditor(connector)
    editor.load_data()
    _type(editor.tableWavelengths, 0, 0, "0,6328")

    editor.apply_table_wavelength_changes()

    wavelength = connector.get_optic().wavelengths.wavelengths[0]
    assert wavelength.value == pytest.approx(0.6328)


def test_invalid_wavelength_entry_is_reported_as_a_warning(connector, caplog) -> None:
    editor = WavelengthsEditor(connector)
    editor.load_data()
    _type(editor.tableWavelengths, 0, 0, "grün")

    with caplog.at_level(logging.WARNING, logger="optiland_gui"):
        editor.apply_table_wavelength_changes()

    assert connector.get_optic().wavelengths.wavelengths[0].value == pytest.approx(0.55)
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert warnings, "an invalid entry must reach the user, not only stdout"
    assert "row 1" in warnings[0].getMessage()
    assert "grün" in warnings[0].getMessage()
