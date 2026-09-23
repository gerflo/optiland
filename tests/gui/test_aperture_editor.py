"""Regression tests: the aperture editor of the System Properties panel (O10).

Found in the user's session log (2026-09-23): typing ``4.5`` into the
aperture value field printed ``Aperture updated: float_by_stop_size, 40.6``,
``... 4.6``, ``... 4.0`` and ``... 4.5`` to the console. Every keystroke set
the aperture on the optic and retraced the system, and the messages never
reached the GUI log or a toast.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

import optiland.backend as be
from optiland.optic import Optic
from optiland_gui.optiland_connector import OptilandConnector
from optiland_gui.system_properties_panel import ApertureEditor


def _optic() -> Optic:
    optic = Optic()
    optic.surfaces.add(index=0, radius=be.inf, thickness=10.0)
    optic.surfaces.add(index=1, radius=be.inf, thickness=20.0, is_stop=True)
    optic.surfaces.add(index=2, radius=be.inf, thickness=0.0)
    optic.set_aperture(aperture_type="EPD", value=10.0)
    optic.fields.set_type("object_height")
    optic.fields.add(y=0.0)
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


@pytest.fixture()
def editor(connector) -> ApertureEditor:
    editor = ApertureEditor(connector)
    editor.load_data()
    return editor


def test_typing_a_value_applies_it_once_when_committed(connector, editor) -> None:
    applied: list[float] = []
    connector.opticChanged.connect(
        lambda: applied.append(connector.get_optic().aperture.value)
    )
    spin = editor.spnApertureValue
    decimal_point = spin.locale().decimalPoint()

    spin.selectAll()
    QTest.keyClicks(spin, f"4{decimal_point}5")
    assert applied == [], "keystrokes must not set the aperture"

    QTest.keyClick(spin, Qt.Key_Return)
    assert applied == [pytest.approx(4.5)]
    assert connector.get_optic().aperture.value == pytest.approx(4.5)


def test_a_committed_value_is_logged_not_printed(
    connector, editor, caplog, capsys
) -> None:
    with caplog.at_level(logging.INFO, logger="optiland_gui"):
        editor.spnApertureValue.setValue(4.5)

    assert connector.get_optic().aperture.value == pytest.approx(4.5)
    assert capsys.readouterr().out == ""
    messages = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
    assert any("4.5" in m for m in messages), messages


def test_a_rejected_value_is_reported_as_a_warning(
    connector, editor, caplog, capsys, monkeypatch
) -> None:
    def refuse(aperture_type, value):  # noqa: ANN001
        raise ValueError("not a valid aperture")

    monkeypatch.setattr(connector.get_optic(), "set_aperture", refuse)

    with caplog.at_level(logging.WARNING, logger="optiland_gui"):
        editor.spnApertureValue.setValue(4.5)

    assert capsys.readouterr().out == ""
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert warnings, "a rejected aperture must reach the user, not only stdout"
    assert "not a valid aperture" in warnings[0].getMessage()
    # The editor shows the optic's value again, not the rejected one.
    assert editor.spnApertureValue.value() == pytest.approx(10.0)
