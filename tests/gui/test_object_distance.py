"""Regression tests: the object distance in the GUI.

Found with the user's illumination design (LED ring -> ring stop 0.1 mm
-> diffuser):

(1) the Lens Data Editor locked the object row's Thickness, so the
    distance from the object to the first surface could not be set;
(2) disabling surface 1 dropped its gap from the drawn system: the object
    stayed where it was while the next surface moved up to z = 0 (the
    LED-to-diffuser distance shrank from 1.0 to 0.9 mm). Its thickness
    was added to the object's ``thickness`` attribute, which does not
    place the object (and reads 0 for a file-loaded finite object).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import Qt

import optiland.backend as be
from optiland.optic import Optic
from optiland_gui.optiland_connector import OptilandConnector


def _patch_connector_side_services(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(
        "optiland_gui.optiland_connector.CatalogService",
        lambda connector: MagicMock(),
    )
    monkeypatch.setattr(
        "optiland_gui.optiland_connector.MaterialCatalogService",
        lambda connector: MagicMock(),
    )


def _ring_source_optic(object_distance: float = 0.9) -> Optic:
    """LED plane -> ring stop (0.1 mm) -> 0.3 mm diffuser -> lens -> image."""
    optic = Optic()
    optic.surfaces.add(index=0, radius=be.inf, thickness=object_distance)
    optic.surfaces.add(index=1, radius=be.inf, thickness=0.1, comment="ring stop")
    optic.surfaces.add(
        index=2, radius=be.inf, thickness=0.3, material="N-BK7", comment="diffuser"
    )
    optic.surfaces.add(index=3, radius=be.inf, thickness=20.0, is_stop=True)
    optic.surfaces.add(index=4, radius=40.0, thickness=4.0, material="N-BK7")
    optic.surfaces.add(index=5, radius=-40.0, thickness=30.0)
    optic.surfaces.add(index=6, radius=be.inf, thickness=0.0)
    optic.set_aperture(aperture_type="float_by_stop_size", value=4.0)
    optic.fields.set_type("object_height")
    optic.fields.add(y=2.0)
    optic.wavelengths.add(value=0.53, is_primary=True)
    optic.updater.update()
    return optic


def _z(optic: Optic) -> list[float]:
    return [float(be.to_numpy(s.geometry.cs.z)) for s in optic.surfaces]


@pytest.fixture()
def connector(qapp, monkeypatch) -> OptilandConnector:
    _patch_connector_side_services(monkeypatch)
    connector = OptilandConnector()
    connector.toast_manager = MagicMock()
    connector.load_optic_from_object(_ring_source_optic())
    return connector


# ---------------------------------------------------------------------------
# Disabled surfaces keep the geometry of the rest
# ---------------------------------------------------------------------------


def test_disabling_surface_1_keeps_the_object_distance(connector) -> None:
    live = _z(connector.get_optic())

    connector.set_surface_disabled(1, True)
    effective = _z(connector.get_effective_optic())

    # The diffuser is the first surface now (z = 0 by definition); the
    # object keeps its distance to it (0.9 + 0.1 mm).
    assert effective[1] == pytest.approx(0.0)
    assert effective[1] - effective[0] == pytest.approx(live[2] - live[0])
    assert effective[1] - effective[0] == pytest.approx(1.0)
    # Everything behind keeps its spacing.
    assert effective[2] - effective[1] == pytest.approx(live[3] - live[2])


def test_disabling_a_later_surface_keeps_the_positions_behind_it(connector) -> None:
    live = _z(connector.get_optic())

    connector.set_surface_disabled(2, True)
    effective = _z(connector.get_effective_optic())

    assert effective[0] == pytest.approx(live[0])
    assert effective[2:] == pytest.approx(live[3:])


def test_disabling_surface_1_with_the_object_at_infinity(connector) -> None:
    optic = _ring_source_optic()
    optic.updater.set_thickness(be.inf, 0)
    optic.fields.set_type("angle")
    connector.load_optic_from_object(optic)
    live = _z(connector.get_optic())

    connector.set_surface_disabled(1, True)
    effective = _z(connector.get_effective_optic())

    assert effective[0] == -float("inf")
    assert effective[1:] == pytest.approx([z - live[2] for z in live[2:]])


def test_the_file_loaded_object_is_placed_by_position(connector, tmp_path) -> None:
    # A finite object read back from a file has thickness attribute 0; only
    # its position says how far away it is.
    path = str(tmp_path / "ring.json")
    connector.save_optic_to_file(path)
    connector.load_optic_from_file(path)
    live = _z(connector.get_optic())

    connector.set_surface_disabled(1, True)
    effective = _z(connector.get_effective_optic())

    assert effective[1] - effective[0] == pytest.approx(live[2] - live[0])


# ---------------------------------------------------------------------------
# The Lens Data Editor lets the object distance be edited
# ---------------------------------------------------------------------------


class _DefaultSettings:
    def __init__(self, *_args, **_kwargs) -> None:
        pass

    def value(self, _key: str, default=None, *, type=None):  # noqa: A002, ANN001
        return default

    def setValue(self, _key: str, _value) -> None:  # noqa: ANN001, N802
        return None


@pytest.fixture()
def editor(connector, monkeypatch):
    from optiland_gui.lens_editor import LensEditor

    monkeypatch.setattr("optiland_gui.lens_editor.QSettings", _DefaultSettings)
    editor = LensEditor(connector)
    editor.load_data()
    yield editor
    editor.close()


def _object_item(editor, column: int):
    return editor.tableWidget.item(0, column)


def test_the_object_thickness_is_editable(editor, connector) -> None:
    item = _object_item(editor, connector.COL_THICKNESS)

    assert item is not None
    assert item.flags() & Qt.ItemFlag.ItemIsEditable


def test_the_rest_of_the_object_row_stays_locked(editor, connector) -> None:
    for column in (connector.COL_RADIUS, connector.COL_CONIC):
        item = _object_item(editor, column)
        assert item is not None
        assert not (item.flags() & Qt.ItemFlag.ItemIsEditable), column


def test_editing_the_object_thickness_moves_the_object(editor, connector) -> None:
    _object_item(editor, connector.COL_THICKNESS).setText("0,5")

    z = _z(connector.get_optic())
    assert z[1] - z[0] == pytest.approx(0.5)
    assert z[1] == pytest.approx(0.0)
    assert _object_item(editor, connector.COL_THICKNESS).text() == "0.5000"


def test_the_object_can_be_moved_to_infinity(editor, connector) -> None:
    connector.get_optic().fields.set_type("angle")

    _object_item(editor, connector.COL_THICKNESS).setText("inf")

    assert _z(connector.get_optic())[0] == -float("inf")
    assert _object_item(editor, connector.COL_THICKNESS).text() == "inf"
