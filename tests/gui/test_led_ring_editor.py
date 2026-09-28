"""LED ring light source in the System Properties (service, library, page).

The page describes a ring of LEDs as the light source of the active path;
Apply sets it on the optic with generated fields and wavelengths as one
undoable edit, and a folded system then builds its emitter from it (O14).
What a datasheet does not give -- radiation curve, spectrum, flux -- can
stay at its default.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QMessageBox

import optiland.backend as be
from optiland.illumination import LEDRing, LEDSpectrum, LEDType, RadiationPattern
from optiland.nonsequential import LEDRingSource
from optiland.nonsequential.fold import ILLUMINATION
from optiland.optic import Optic
from optiland_gui.led_ring_editor import LEDRingEditor
from optiland_gui.optiland_connector import OptilandConnector
from optiland_gui.services.light_source_service import (
    LEDLibrary,
    fold_symmetric_curve,
    parse_xy_table,
)
from optiland_gui.system_properties_panel import FieldsEditor, SystemPropertiesPanel


@pytest.fixture(autouse=True)
def _numpy_backend():
    be.set_backend("numpy")
    yield
    be.set_backend("numpy")


def _optic(object_distance: float = 10.0) -> Optic:
    optic = Optic()
    optic.surfaces.add(index=0, radius=be.inf, thickness=object_distance)
    optic.surfaces.add(index=1, radius=be.inf, thickness=20.0, is_stop=True)
    optic.surfaces.add(index=2, radius=be.inf, thickness=0.0)
    optic.set_aperture(aperture_type="EPD", value=4.0)
    if object_distance == be.inf:
        optic.fields.set_type("angle")
    else:
        optic.fields.set_type("object_height")
    optic.fields.add(y=0.0)
    optic.wavelengths.add(value=0.8, is_primary=True)
    optic.updater.update()
    return optic


def _patch_side_services(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(
        "optiland_gui.optiland_connector.CatalogService",
        lambda connector: MagicMock(),
    )
    monkeypatch.setattr(
        "optiland_gui.optiland_connector.MaterialCatalogService",
        lambda connector: MagicMock(),
    )


@pytest.fixture()
def connector(qapp, monkeypatch) -> OptilandConnector:
    _patch_side_services(monkeypatch)
    connector = OptilandConnector()
    connector.toast_manager = MagicMock()
    connector.load_optic_from_object(_optic())
    return connector


@pytest.fixture()
def library(tmp_path) -> LEDLibrary:
    return LEDLibrary(tmp_path / "led_types")


@pytest.fixture()
def editor(connector, library) -> LEDRingEditor:
    return LEDRingEditor(connector, library=library)


def _ring(**kwargs) -> LEDRing:
    led = kwargs.pop("led", LEDType(name="Test LED", chip_width=1.0, chip_height=1.2))
    return LEDRing(led=led, count=kwargs.pop("count", 12), pitch_diameter=6.5, **kwargs)


class TestService:
    def test_apply_generates_fields_and_wavelengths(self, connector):
        spectrum = LEDSpectrum("gaussian", center_um=0.53, fwhm_um=0.03)
        ring = _ring(
            led=LEDType(chip_width=1.0, chip_height=1.2, spectrum=spectrum),
            field_count=3,
            wavelength_count=3,
        )
        connector.set_light_source(ring)
        optic = connector.get_optic()
        assert optic.light_source == ring
        assert optic.fields.num_fields == 5
        assert optic.wavelengths.num_wavelengths == 3
        assert connector.is_modified()

    def test_apply_is_one_undo_step(self, connector):
        connector.set_light_source(_ring())
        connector.undo()
        optic = connector.get_optic()
        assert optic.light_source is None
        assert optic.fields.num_fields == 1
        assert optic.wavelengths.get_wavelengths() == [0.8]
        connector.redo()
        assert connector.get_optic().light_source == _ring()

    def test_object_at_infinity_changes_nothing(self, qapp, monkeypatch):
        _patch_side_services(monkeypatch)
        connector = OptilandConnector()
        connector.load_optic_from_object(_optic(object_distance=be.inf))
        with pytest.raises(ValueError, match="infinity"):
            connector.set_light_source(_ring())
        assert connector.get_optic().light_source is None
        assert not connector._undo_redo_manager.can_undo()


class TestLibrary:
    def test_save_list_load_delete(self, library):
        led = LEDType(
            name="Luxeon Z / warm",
            chip_width=1.3,
            chip_height=1.3,
            radiation=RadiationPattern("half_angle", half_angle_deg=60.0),
            spectrum=LEDSpectrum(center_um=0.59),
            flux=0.5,
            flux_unit="lm",
        )
        path = library.save(led)
        assert path.parent == library.root
        assert "/" not in path.name
        assert library.names() == ["Luxeon Z / warm"]
        assert library.load("Luxeon Z / warm") == led
        library.delete("Luxeon Z / warm")
        assert library.names() == []

    def test_a_type_needs_a_name(self, library):
        with pytest.raises(ValueError, match="name"):
            library.save(LEDType())

    def test_missing_type(self, library):
        assert library.names() == []
        with pytest.raises(KeyError):
            library.load("nothing")


class TestCurveImport:
    def test_comma_separated_with_header(self):
        xs, ys = parse_xy_table("angle,intensity\n0,1.0\n30,0.85\n60, 0.5\n")
        assert xs == [0.0, 30.0, 60.0]
        assert ys == [1.0, 0.85, 0.5]

    def test_semicolon_and_decimal_comma(self):
        xs, ys = parse_xy_table("Wellenlänge;Leistung\n450,5;0,12\n451,0;0,20\n")
        assert xs == [450.5, 451.0]
        assert ys == [0.12, 0.20]

    def test_tabs_and_extra_columns(self):
        xs, ys = parse_xy_table("# digitized\n1\t2\t9\n3\t4\t9\n")
        assert (xs, ys) == ([1.0, 3.0], [2.0, 4.0])

    def test_symmetric_curve_is_folded_and_averaged(self):
        angles = [-60, -30, 0, 30, 60]
        values = [0.4, 0.8, 1.0, 0.9, 0.6]
        half_a, half_v = fold_symmetric_curve(angles, values)
        assert half_a == [0.0, 30.0, 60.0]
        assert half_v == pytest.approx([1.0, 0.85, 0.5])

    def test_negative_side_alone_is_mirrored(self):
        half_a, half_v = fold_symmetric_curve([-60, -30, 0], [0.5, 0.8, 1.0])
        assert half_a == [0.0, 30.0, 60.0]
        assert half_v == [1.0, 0.8, 0.5]


class TestEditor:
    def test_defaults_are_off_and_apply_nothing(self, connector, editor):
        assert not editor.chkEnabled.isChecked()
        assert editor.build_ring() is None
        editor.apply_changes()
        assert connector.get_optic().light_source is None

    def test_apply_with_datasheet_minimum(self, connector, editor):
        """Only chip size, arrangement and central wavelength are known."""
        editor.chkEnabled.setChecked(True)
        editor.spnCount.setValue(8)
        editor.spnPitch.setValue(7.0)
        editor.spnChipWidth.setValue(1.3)
        editor.spnChipHeight.setValue(1.3)
        editor.spnCenter.setValue(625.0)
        editor.spnFieldCount.setValue(4)
        editor.apply_changes()

        ring = connector.get_optic().light_source
        assert ring is not None
        assert ring.count == 8
        assert ring.pitch_diameter == pytest.approx(7.0)
        assert ring.led.radiation.kind == "lambertian"
        assert ring.led.spectrum == LEDSpectrum(center_um=0.625)
        assert ring.led.flux is None
        optic = connector.get_optic()
        assert optic.fields.num_fields == 6
        assert optic.wavelengths.get_wavelengths() == [pytest.approx(0.625)]
        assert "not applied" not in editor.lblStatus.text()

    def test_page_shows_the_applied_ring(self, connector, library):
        pattern = RadiationPattern(
            "table", angles_deg=(0, 30, 60, 90), intensities=(1, 0.9, 0.5, 0)
        )
        spectrum = LEDSpectrum(
            "table", wavelengths_um=(0.50, 0.52, 0.54), powers=(0.1, 1.0, 0.2)
        )
        ring = _ring(
            led=LEDType(
                name="Tabled",
                chip_width=1.0,
                chip_height=1.2,
                radiation=pattern,
                spectrum=spectrum,
                flux=0.25,
            ),
            first_angle_deg=15.0,
            emitter_model="annulus",
            field_count=7,
            field_edges=False,
            wavelength_count=3,
        )
        connector.set_light_source(ring)
        page = LEDRingEditor(connector, library=library)
        assert page.chkEnabled.isChecked()
        assert page.build_ring() == ring

    def test_invalid_ring_is_reported_not_applied(self, connector, editor):
        editor.chkEnabled.setChecked(True)
        editor.spnChipWidth.setValue(3.0)  # 12 chips of 3 mm overlap on D6.5
        editor.apply_changes()
        assert connector.get_optic().light_source is None
        assert "overlap" in editor.lblStatus.text()

    def test_switching_off_removes_the_source(self, connector, editor):
        connector.set_light_source(_ring())
        editor.load_data()
        editor.chkEnabled.setChecked(False)
        editor.apply_changes()
        assert connector.get_optic().light_source is None

    def test_pasted_symmetric_pattern_becomes_a_table(self, editor, monkeypatch):
        clipboard = MagicMock()
        clipboard.text.return_value = "-60;0,5\n-30;0,85\n0;1\n30;0,85\n60;0,5\n"
        monkeypatch.setattr(
            "optiland_gui.led_ring_editor.QApplication.clipboard", lambda: clipboard
        )
        editor.chkEnabled.setChecked(True)
        editor.cmbPattern.setCurrentIndex(editor.cmbPattern.findData("table"))
        editor.patternTable.btnPaste.click()
        pattern = editor.build_pattern()
        assert pattern.angles_deg == (0.0, 30.0, 60.0)
        assert pattern.intensities == pytest.approx((1.0, 0.85, 0.5))

    def test_rows_follow_the_chosen_forms(self, editor):
        editor.chkEnabled.setChecked(True)
        form = editor.patternForm
        assert not form.isRowVisible(editor.spnHalfAngle)
        editor.cmbPattern.setCurrentIndex(editor.cmbPattern.findData("half_angle"))
        assert form.isRowVisible(editor.spnHalfAngle)
        assert not form.isRowVisible(editor.patternTable)
        spectrum_form = editor.spectrumForm
        assert not spectrum_form.isRowVisible(editor.spnFwhm)
        editor.cmbSpectrum.setCurrentIndex(editor.cmbSpectrum.findData("gaussian"))
        assert spectrum_form.isRowVisible(editor.spnFwhm)

    def test_library_buttons(self, editor, library, monkeypatch):
        editor.chkEnabled.setChecked(True)
        editor.txtLedName.setText("Ring LED 590")
        editor.spnChipWidth.setValue(0.9)
        editor.spnCenter.setValue(590.0)
        editor.btnSaveType.click()
        assert library.names() == ["Ring LED 590"]
        assert editor.cmbLibrary.currentText() == "Ring LED 590"

        editor.spnChipWidth.setValue(2.0)
        editor.btnLoadType.click()
        assert editor.spnChipWidth.value() == pytest.approx(0.9)

        monkeypatch.setattr(
            "optiland_gui.led_ring_editor.QMessageBox.question",
            lambda *args: QMessageBox.StandardButton.Yes,
        )
        editor.btnDeleteType.click()
        assert library.names() == []
        assert not editor.btnLoadType.isEnabled()

    @pytest.mark.parametrize("figure_name", ["patternFigure", "spectrumFigure"])
    def test_previews_fill_their_canvas(self, editor, figure_name):
        editor.chkEnabled.setChecked(True)
        editor.cmbPattern.setCurrentIndex(editor.cmbPattern.findData("half_angle"))
        editor.cmbSpectrum.setCurrentIndex(editor.cmbSpectrum.findData("gaussian"))
        figure = getattr(editor, figure_name)
        figure.set_size_inches(420 / figure.dpi, 150 / figure.dpi)
        figure.canvas.draw()
        (ax,) = figure.axes
        box, full = ax.get_position(), ax.get_position(original=True)
        assert box.width == pytest.approx(full.width, rel=0.02)
        assert box.height == pytest.approx(full.height, rel=0.02)
        # Only the tick labels and axis labels take room from the plot.
        assert box.width > 0.75
        assert box.height > 0.5


class TestFieldsTable:
    def test_weights_are_shown_and_edited(self, connector):
        connector.set_light_source(_ring(field_count=2))
        fields = FieldsEditor(connector)
        fields.load_data()
        table = fields.tableFields
        assert table.columnCount() == 5
        assert [table.item(r, 4).text() for r in range(table.rowCount())] == [
            "0",
            "1",
            "1",
            "0",
        ]
        assert fields.lblLightSource.isVisibleTo(fields)

        table.item(1, 4).setText("0,5")
        fields.apply_table_field_changes()
        assert connector.get_optic().fields.fields[1].weight == pytest.approx(0.5)

    def test_negative_weight_is_refused(self, connector):
        fields = FieldsEditor(connector)
        fields.load_data()
        fields.tableFields.item(0, 4).setText("-1")
        fields.apply_table_field_changes()
        assert connector.get_optic().fields.fields[0].weight == 1.0
        assert fields.tableFields.item(0, 4).text() == "1"


class TestPanel:
    def test_the_panel_offers_the_page(self, connector):
        panel = SystemPropertiesPanel(connector)
        names = [
            panel.navTree.topLevelItem(i).text(0)
            for i in range(panel.navTree.topLevelItemCount())
        ]
        assert "LED Ring" in names
        assert isinstance(panel.ledRingEditor, LEDRingEditor)


class TestFoldedSystem:
    def test_applying_on_the_illumination_path_rebuilds_the_emitter(
        self, qapp, monkeypatch, tmp_path
    ):
        from tests.gui.test_system_paths import _loaded_panel  # noqa: PLC0415

        panel, connector, service = _loaded_panel(monkeypatch, tmp_path)
        service.activate_path("Ring illumination", connector)
        connector.set_light_source(_ring())
        panel.flush_pending_rebuild()
        QCoreApplication.processEvents()
        source = service.scene.source_registry.get(ILLUMINATION)
        assert isinstance(source, LEDRingSource)
        assert source.count == 12
