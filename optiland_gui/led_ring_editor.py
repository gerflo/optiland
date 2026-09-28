"""System Properties page for the LED ring light source of a path.

An illumination path whose light source is a ring of LEDs describes the
ring here: the arrangement, the LED type (chip size, radiation pattern,
spectrum, flux) and how the ring is turned into the path's fields,
wavelengths and non-sequential emitter. *Apply LED Ring* sets it on the
optic (:func:`optiland.illumination.apply_led_ring`) as one undoable edit;
the fold of a multi-axis system then builds its emitter from it.

What a datasheet does not give can stay at its default: without a
radiation curve the LEDs are Lambertian, without a spectrum they emit at
their central wavelength, without a flux the trace is normalised.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from PySide6.QtCore import QStandardPaths, Qt, Slot
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from optiland.illumination import LEDRing, LEDSpectrum, LEDType, RadiationPattern

from . import gui_plot_utils
from .services.light_source_service import (
    LEDLibrary,
    fold_symmetric_curve,
    parse_xy_table,
)
from .system_properties_panel import PropertyEditorBase
from .utils.number_input import parse_user_float
from .utils.table_copy import TableCopySupport

if TYPE_CHECKING:
    from .optiland_connector import OptilandConnector

logger = logging.getLogger(__name__)

#: Radiation pattern forms: (key, label).
PATTERN_CHOICES: tuple[tuple[str, str], ...] = (
    ("lambertian", "Lambertian (nothing known)"),
    ("half_angle", "Half-intensity angle"),
    ("table", "Table (digitized curve)"),
)

#: Spectrum forms: (key, label).
SPECTRUM_CHOICES: tuple[tuple[str, str], ...] = (
    ("line", "Central wavelength only"),
    ("gaussian", "Central wavelength and FWHM"),
    ("table", "Table (digitized spectrum)"),
)

#: Non-sequential emitter models: (key, label).
EMITTER_CHOICES: tuple[tuple[str, str], ...] = (
    ("discrete", "Discrete chips"),
    ("annulus", "Homogeneous annulus (diffuser)"),
)

_DESCRIPTION = (
    "Describe the ring of LEDs in the object plane of this illumination "
    "path. Apply LED Ring makes it the path's light source: the fields "
    "become object heights across the emitting zone (equal-area bands, "
    "optionally framed by the zone edges at weight 0), the wavelengths "
    "represent the LED spectrum, and a folded system builds its emitter "
    "from the ring (one chip per LED, or a homogeneous annulus). Leave what "
    "the datasheet does not give at its default: Lambertian emission, the "
    "central wavelength, an unknown flux."
)


def default_library_root() -> Path:
    """Directory of the LED type library in the user's application data."""
    data_dir = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppDataLocation
    )
    return Path(data_dir) / "led_types"


def _spin(
    low: float, high: float, value: float, decimals: int = 4, suffix: str = ""
) -> QDoubleSpinBox:
    spin = QDoubleSpinBox()
    spin.setDecimals(decimals)
    spin.setRange(low, high)
    spin.setValue(value)
    spin.setSuffix(suffix)
    spin.setKeyboardTracking(False)
    spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
    return spin


def _combo(choices: tuple[tuple[str, str], ...]) -> QComboBox:
    combo = QComboBox()
    for key, label in choices:
        combo.addItem(label, userData=key)
    return combo


def _select(combo: QComboBox, key: str) -> None:
    index = combo.findData(key)
    if index >= 0:
        combo.setCurrentIndex(index)


class _CurveTable(QWidget):
    """Two-column table of a digitized curve with row and import buttons."""

    def __init__(self, headers: tuple[str, str], parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(list(headers))
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.table.setMinimumHeight(120)
        self._copy = TableCopySupport(self.table)
        layout.addWidget(self.table)
        buttons = QHBoxLayout()
        self.btnAdd = QPushButton("Add Row")
        self.btnRemove = QPushButton("Remove Row")
        self.btnPaste = QPushButton("Paste")
        self.btnLoad = QPushButton("Load CSV...")
        for button in (self.btnAdd, self.btnRemove, self.btnPaste, self.btnLoad):
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self.btnAdd.clicked.connect(self._add_row)
        self.btnRemove.clicked.connect(self._remove_row)

    def set_values(self, xs: list[float], ys: list[float]) -> None:
        """Fill the table with the pairs ``(xs[i], ys[i])``."""
        self.table.setRowCount(len(xs))
        for row, (x, y) in enumerate(zip(xs, ys, strict=True)):
            self.table.setItem(row, 0, QTableWidgetItem(f"{x:g}"))
            self.table.setItem(row, 1, QTableWidgetItem(f"{y:g}"))

    def values(self) -> tuple[list[float], list[float]]:
        """The pairs of the filled rows; empty rows are skipped.

        Raises:
            ValueError: If a filled cell is not a number.
        """
        xs: list[float] = []
        ys: list[float] = []
        for row in range(self.table.rowCount()):
            cells = [self.table.item(row, col) for col in (0, 1)]
            texts = [c.text().strip() if c is not None else "" for c in cells]
            if not any(texts):
                continue
            try:
                x, y = (parse_user_float(t) for t in texts)
            except ValueError:
                raise ValueError(
                    f"Row {row + 1} of the table is not a pair of numbers."
                ) from None
            xs.append(x)
            ys.append(y)
        return xs, ys

    def _add_row(self) -> None:
        self.table.insertRow(self.table.rowCount())

    def _remove_row(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            row = self.table.rowCount() - 1
        if row >= 0:
            self.table.removeRow(row)


class LEDRingEditor(PropertyEditorBase):
    """System Properties page: the LED ring light source of the path.

    Args:
        connector: The connector of the active optic.
        parent: Parent widget.
        library: LED type library; defaults to the user's application data.
    """

    def __init__(
        self,
        connector: OptilandConnector,
        parent=None,
        library: LEDLibrary | None = None,
    ) -> None:
        self._library = library or LEDLibrary(default_library_root())
        super().__init__(connector, parent)
        self.load_data()

    # -- construction ----------------------------------------------------------

    def init_ui(self) -> None:
        """Builds the page."""
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        outer.addWidget(scroll)
        content = QWidget()
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        self.chkEnabled = QCheckBox("Use an LED ring as the light source of this path")
        layout.addWidget(self.chkEnabled)
        self.descBox = self._make_description_box()
        self.descBox.setPlainText(_DESCRIPTION)
        layout.addWidget(self.descBox)

        self.groups = [
            self._build_arrangement_group(),
            self._build_led_group(),
            self._build_pattern_group(),
            self._build_spectrum_group(),
            self._build_generation_group(),
        ]
        for group in self.groups:
            layout.addWidget(group)

        self.lblStatus = QLabel()
        self.lblStatus.setWordWrap(True)
        self.lblStatus.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(self.lblStatus)
        self.btnApply = QPushButton("Apply LED Ring")
        layout.addWidget(self.btnApply)
        layout.addStretch(1)

        self._connect_signals()
        self._refresh_library()

    def _build_arrangement_group(self) -> QGroupBox:
        group = QGroupBox("Arrangement")
        form = QFormLayout(group)
        self.spnCount = QSpinBox()
        self.spnCount.setRange(1, 1000)
        self.spnCount.setValue(12)
        self.spnCount.setKeyboardTracking(False)
        form.addRow("Number of LEDs:", self.spnCount)
        self.spnPitch = _spin(0.001, 1e4, 6.5, suffix=" mm")
        form.addRow("Pitch diameter:", self.spnPitch)
        self.spnFirstAngle = _spin(-360.0, 360.0, 0.0, decimals=3, suffix=" °")
        form.addRow("Azimuth of LED 1:", self.spnFirstAngle)
        return group

    def _build_led_group(self) -> QGroupBox:
        group = QGroupBox("LED type")
        form = QFormLayout(group)
        library_row = QHBoxLayout()
        self.cmbLibrary = QComboBox()
        self.cmbLibrary.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.btnLoadType = QPushButton("Load")
        self.btnSaveType = QPushButton("Save")
        self.btnDeleteType = QPushButton("Delete")
        library_row.addWidget(self.cmbLibrary)
        for button in (self.btnLoadType, self.btnSaveType, self.btnDeleteType):
            library_row.addWidget(button)
        form.addRow("Library:", library_row)
        self.txtLedName = QLineEdit()
        self.txtLedName.setPlaceholderText("e.g. the part number")
        form.addRow("Name:", self.txtLedName)
        self.spnChipWidth = _spin(0.001, 1e3, 1.0, suffix=" mm")
        form.addRow("Emitting width (tangential):", self.spnChipWidth)
        self.spnChipHeight = _spin(0.001, 1e3, 1.0, suffix=" mm")
        form.addRow("Emitting height (radial):", self.spnChipHeight)
        flux_row = QHBoxLayout()
        self.chkFluxKnown = QCheckBox("known:")
        self.spnFlux = _spin(1e-9, 1e6, 0.1, decimals=6)
        self.cmbFluxUnit = QComboBox()
        self.cmbFluxUnit.addItems(["W", "lm"])
        flux_row.addWidget(self.chkFluxKnown)
        flux_row.addWidget(self.spnFlux, 1)
        flux_row.addWidget(self.cmbFluxUnit)
        form.addRow("Flux per LED:", flux_row)
        return group

    def _build_pattern_group(self) -> QGroupBox:
        group = QGroupBox("Radiation pattern")
        self.patternForm = form = QFormLayout(group)
        self.cmbPattern = _combo(PATTERN_CHOICES)
        form.addRow("Form:", self.cmbPattern)
        self.spnHalfAngle = _spin(0.1, 89.9, 60.0, decimals=2, suffix=" °")
        form.addRow("Half-intensity angle:", self.spnHalfAngle)
        self.patternTable = _CurveTable(("Angle (°)", "Rel. intensity"))
        form.addRow(self.patternTable)
        self.patternFigure = Figure(figsize=(4.0, 1.8), layout="constrained")
        self.patternCanvas = FigureCanvas(self.patternFigure)
        self.patternCanvas.setMinimumHeight(150)
        form.addRow(self.patternCanvas)
        return group

    def _build_spectrum_group(self) -> QGroupBox:
        group = QGroupBox("Spectrum")
        self.spectrumForm = form = QFormLayout(group)
        self.cmbSpectrum = _combo(SPECTRUM_CHOICES)
        form.addRow("Form:", self.cmbSpectrum)
        self.spnCenter = _spin(100.0, 20000.0, 550.0, decimals=2, suffix=" nm")
        form.addRow("Central wavelength:", self.spnCenter)
        self.spnFwhm = _spin(0.01, 5000.0, 25.0, decimals=2, suffix=" nm")
        form.addRow("FWHM:", self.spnFwhm)
        self.spectrumTable = _CurveTable(("Wavelength (nm)", "Rel. power"))
        form.addRow(self.spectrumTable)
        self.spectrumFigure = Figure(figsize=(4.0, 1.8), layout="constrained")
        self.spectrumCanvas = FigureCanvas(self.spectrumFigure)
        self.spectrumCanvas.setMinimumHeight(150)
        form.addRow(self.spectrumCanvas)
        return group

    def _build_generation_group(self) -> QGroupBox:
        group = QGroupBox("Generated settings")
        form = QFormLayout(group)
        self.spnFieldCount = QSpinBox()
        self.spnFieldCount.setRange(1, 200)
        self.spnFieldCount.setValue(5)
        self.spnFieldCount.setKeyboardTracking(False)
        form.addRow("Field points:", self.spnFieldCount)
        self.chkFieldEdges = QCheckBox("Add the zone edges as weight-0 fields")
        self.chkFieldEdges.setChecked(True)
        form.addRow("", self.chkFieldEdges)
        self.spnWavelengthCount = QSpinBox()
        self.spnWavelengthCount.setRange(1, 24)
        self.spnWavelengthCount.setValue(5)
        self.spnWavelengthCount.setKeyboardTracking(False)
        form.addRow("Wavelengths:", self.spnWavelengthCount)
        self.cmbEmitter = _combo(EMITTER_CHOICES)
        form.addRow("Non-sequential emitter:", self.cmbEmitter)
        self.chkReplaceFields = QCheckBox("Replace the fields")
        self.chkReplaceFields.setChecked(True)
        self.chkReplaceWavelengths = QCheckBox("Replace the wavelengths")
        self.chkReplaceWavelengths.setChecked(True)
        form.addRow("On apply:", self.chkReplaceFields)
        form.addRow("", self.chkReplaceWavelengths)
        return group

    def _connect_signals(self) -> None:
        refresh = self._on_input_changed
        self.chkEnabled.toggled.connect(refresh)
        for spin in (
            self.spnCount,
            self.spnPitch,
            self.spnFirstAngle,
            self.spnChipWidth,
            self.spnChipHeight,
            self.spnFlux,
            self.spnHalfAngle,
            self.spnCenter,
            self.spnFwhm,
            self.spnFieldCount,
            self.spnWavelengthCount,
        ):
            spin.valueChanged.connect(refresh)
        for combo in (self.cmbPattern, self.cmbSpectrum, self.cmbEmitter):
            combo.currentIndexChanged.connect(refresh)
        self.cmbFluxUnit.currentIndexChanged.connect(refresh)
        self.txtLedName.textChanged.connect(refresh)
        for check in (
            self.chkFluxKnown,
            self.chkFieldEdges,
            self.chkReplaceFields,
            self.chkReplaceWavelengths,
        ):
            check.toggled.connect(refresh)
        for curve in (self.patternTable, self.spectrumTable):
            curve.table.itemChanged.connect(refresh)
            curve.table.model().rowsRemoved.connect(refresh)
        self.patternTable.btnPaste.clicked.connect(
            lambda: self._paste_into(self.patternTable, pattern=True)
        )
        self.spectrumTable.btnPaste.clicked.connect(
            lambda: self._paste_into(self.spectrumTable, pattern=False)
        )
        self.patternTable.btnLoad.clicked.connect(
            lambda: self._load_csv_into(self.patternTable, pattern=True)
        )
        self.spectrumTable.btnLoad.clicked.connect(
            lambda: self._load_csv_into(self.spectrumTable, pattern=False)
        )
        self.btnLoadType.clicked.connect(self.load_led_type)
        self.btnSaveType.clicked.connect(self.save_led_type)
        self.btnDeleteType.clicked.connect(self.delete_led_type)
        self.btnApply.clicked.connect(self.apply_changes)

    # -- model <-> widgets -------------------------------------------------------

    def build_pattern(self) -> RadiationPattern:
        """The radiation pattern the page describes.

        Raises:
            ValueError: If the pattern is invalid.
        """
        kind = self.cmbPattern.currentData()
        if kind == "half_angle":
            return RadiationPattern(kind, half_angle_deg=self.spnHalfAngle.value())
        if kind == "table":
            angles, values = self.patternTable.values()
            return RadiationPattern(kind, angles_deg=angles, intensities=values)
        return RadiationPattern()

    def build_spectrum(self) -> LEDSpectrum:
        """The LED spectrum the page describes (nm on the page, um inside).

        Raises:
            ValueError: If the spectrum is invalid.
        """
        kind = self.cmbSpectrum.currentData()
        center = self.spnCenter.value() / 1000.0
        if kind == "gaussian":
            fwhm = self.spnFwhm.value() / 1000.0
            return LEDSpectrum(kind, center_um=center, fwhm_um=fwhm)
        if kind == "table":
            waves, powers = self.spectrumTable.values()
            return LEDSpectrum(
                kind, wavelengths_um=[w / 1000.0 for w in waves], powers=powers
            )
        return LEDSpectrum(center_um=center)

    def build_led(self) -> LEDType:
        """The LED type the page describes.

        Raises:
            ValueError: If an entry is invalid.
        """
        return LEDType(
            name=self.txtLedName.text().strip(),
            chip_width=self.spnChipWidth.value(),
            chip_height=self.spnChipHeight.value(),
            radiation=self.build_pattern(),
            spectrum=self.build_spectrum(),
            flux=self.spnFlux.value() if self.chkFluxKnown.isChecked() else None,
            flux_unit=self.cmbFluxUnit.currentText(),
        )

    def build_ring(self) -> LEDRing | None:
        """The LED ring the page describes; ``None`` when it is switched off.

        Raises:
            ValueError: If an entry is invalid.
        """
        if not self.chkEnabled.isChecked():
            return None
        return LEDRing(
            led=self.build_led(),
            count=self.spnCount.value(),
            pitch_diameter=self.spnPitch.value(),
            first_angle_deg=self.spnFirstAngle.value(),
            emitter_model=self.cmbEmitter.currentData(),
            field_count=self.spnFieldCount.value(),
            field_edges=self.chkFieldEdges.isChecked(),
            wavelength_count=self.spnWavelengthCount.value(),
        )

    def show_led(self, led: LEDType) -> None:
        """Put an LED type into the widgets."""
        loading, self.is_loading = self.is_loading, True
        try:
            self.txtLedName.setText(led.name)
            self.spnChipWidth.setValue(led.chip_width)
            self.spnChipHeight.setValue(led.chip_height)
            self.chkFluxKnown.setChecked(led.flux is not None)
            if led.flux is not None:
                self.spnFlux.setValue(led.flux)
            self.cmbFluxUnit.setCurrentText(led.flux_unit)
            pattern = led.radiation
            _select(self.cmbPattern, pattern.kind)
            if pattern.half_angle_deg is not None:
                self.spnHalfAngle.setValue(pattern.half_angle_deg)
            if pattern.kind == "table":
                self.patternTable.set_values(
                    list(pattern.angles_deg), list(pattern.intensities)
                )
            spectrum = led.spectrum
            _select(self.cmbSpectrum, spectrum.kind)
            if spectrum.kind in ("line", "gaussian"):
                self.spnCenter.setValue(spectrum.center_um * 1000.0)
            if spectrum.fwhm_um is not None:
                self.spnFwhm.setValue(spectrum.fwhm_um * 1000.0)
            if spectrum.kind == "table":
                self.spectrumTable.set_values(
                    [w * 1000.0 for w in spectrum.wavelengths_um],
                    list(spectrum.powers),
                )
        finally:
            self.is_loading = loading
        self._refresh()

    def show_ring(self, ring: LEDRing) -> None:
        """Put an LED ring into the widgets."""
        loading, self.is_loading = self.is_loading, True
        try:
            self.spnCount.setValue(ring.count)
            self.spnPitch.setValue(ring.pitch_diameter)
            self.spnFirstAngle.setValue(ring.first_angle_deg)
            _select(self.cmbEmitter, ring.emitter_model)
            self.spnFieldCount.setValue(ring.field_count)
            self.chkFieldEdges.setChecked(ring.field_edges)
            self.spnWavelengthCount.setValue(ring.wavelength_count)
            self.show_led(ring.led)
        finally:
            self.is_loading = loading
        self._refresh()

    @Slot()
    def load_data(self) -> None:
        """Show the light source of the active optic."""
        ring = self.connector.get_light_source()
        self.is_loading = True
        try:
            self.chkEnabled.setChecked(ring is not None)
            if ring is not None:
                self.show_ring(ring)
        finally:
            self.is_loading = False
        self._refresh()

    # -- actions ---------------------------------------------------------------

    @Slot()
    def apply_changes(self) -> None:
        """Set the described ring (or none) on the active optic."""
        try:
            ring = self.build_ring()
            self.connector.set_light_source(
                ring,
                fields=self.chkReplaceFields.isChecked(),
                wavelengths=self.chkReplaceWavelengths.isChecked(),
            )
        except ValueError as exc:
            self._show_status(str(exc), error=True)
            logger.warning("LED ring not applied: %s", exc)
            return
        if ring is None:
            logger.info("LED ring removed from the light source.")
        else:
            logger.info(
                "LED ring applied: %d LEDs on pitch diameter %g mm.",
                ring.count,
                ring.pitch_diameter,
            )

    @Slot()
    def load_led_type(self) -> None:
        """Put the selected library entry into the LED type widgets."""
        name = self.cmbLibrary.currentText()
        if not name:
            return
        try:
            led = self._library.load(name)
        except (KeyError, OSError, ValueError) as exc:
            self._show_status(f"LED type {name!r} could not be loaded: {exc}", True)
            return
        self.show_led(led)

    @Slot()
    def save_led_type(self) -> None:
        """Store the LED type of the page in the library under its name."""
        try:
            led = self.build_led()
            self._library.save(led)
        except (ValueError, OSError) as exc:
            self._show_status(f"LED type not saved: {exc}", error=True)
            return
        self._refresh_library(select=led.name)
        logger.info("LED type %r saved to %s.", led.name, self._library.root)

    @Slot()
    def delete_led_type(self) -> None:
        """Remove the selected library entry after confirmation."""
        name = self.cmbLibrary.currentText()
        if not name:
            return
        answer = QMessageBox.question(
            self, "Delete LED type", f"Delete the LED type {name!r} from the library?"
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._library.delete(name)
        self._refresh_library()

    def _refresh_library(self, select: str | None = None) -> None:
        current = select or self.cmbLibrary.currentText()
        self.cmbLibrary.clear()
        self.cmbLibrary.addItems(self._library.names())
        if current:
            index = self.cmbLibrary.findText(current)
            if index >= 0:
                self.cmbLibrary.setCurrentIndex(index)
        has_entries = self.cmbLibrary.count() > 0
        self.btnLoadType.setEnabled(has_entries)
        self.btnDeleteType.setEnabled(has_entries)

    def _paste_into(self, curve: _CurveTable, *, pattern: bool) -> None:
        self._fill_curve(curve, QApplication.clipboard().text(), pattern=pattern)

    def _load_csv_into(self, curve: _CurveTable, *, pattern: bool) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Load curve", "", "Tables (*.csv *.txt *.tsv);;All files (*)"
        )
        if not path:
            return
        try:
            text = Path(path).read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError) as exc:
            self._show_status(f"{path} could not be read: {exc}", error=True)
            return
        self._fill_curve(curve, text, pattern=pattern)

    def _fill_curve(self, curve: _CurveTable, text: str, *, pattern: bool) -> None:
        xs, ys = parse_xy_table(text)
        if len(xs) < 2:
            self._show_status(
                "No table found: expected two numeric columns.", error=True
            )
            return
        if pattern:
            xs, ys = fold_symmetric_curve(xs, ys)
        else:
            order = np.argsort(xs)
            xs = [xs[i] for i in order]
            ys = [ys[i] for i in order]
        curve.set_values(xs, ys)
        self._refresh()

    # -- feedback --------------------------------------------------------------

    def _on_input_changed(self, *_args) -> None:
        if not self.is_loading:
            self._refresh()

    def _refresh(self) -> None:
        """Update the visible rows, previews and the status line."""
        enabled = self.chkEnabled.isChecked()
        for group in self.groups:
            group.setEnabled(enabled)
        self.spnFlux.setEnabled(self.chkFluxKnown.isChecked())
        self.cmbFluxUnit.setEnabled(self.chkFluxKnown.isChecked())
        pattern_kind = self.cmbPattern.currentData()
        self.patternForm.setRowVisible(self.spnHalfAngle, pattern_kind == "half_angle")
        self.patternForm.setRowVisible(self.patternTable, pattern_kind == "table")
        spectrum_kind = self.cmbSpectrum.currentData()
        self.spectrumForm.setRowVisible(self.spnCenter, spectrum_kind != "table")
        self.spectrumForm.setRowVisible(self.spnFwhm, spectrum_kind == "gaussian")
        self.spectrumForm.setRowVisible(self.spectrumTable, spectrum_kind == "table")
        self._draw_pattern()
        self._draw_spectrum()
        self._update_status()

    def _update_status(self) -> None:
        try:
            ring = self.build_ring()
        except ValueError as exc:
            self._show_status(str(exc), error=True)
            return
        applied = self.connector.get_light_source()
        pending = "" if ring == applied else " (not applied yet)"
        if ring is None:
            text = "No LED ring: the path's object is an ordinary object."
            self._show_status(text + pending)
            return
        optic = self.connector.get_optic()
        obj = getattr(optic, "object_surface", None)
        if obj is not None and obj.is_infinite:
            self._show_status(
                "The object is at infinity; an LED ring needs a finite object "
                "distance.",
                error=True,
            )
            return
        points = ring.field_points()
        waves, primary = ring.led.spectrum.representative_wavelengths(
            ring.wavelength_count
        )
        wave_text = ", ".join(f"{w * 1000:.1f}" for w in waves)
        text = (
            f"Emitting zone r = {ring.inner_radius:.4g} … {ring.outer_radius:.4g} mm; "
            f"{len(points)} field points; wavelengths {wave_text} nm "
            f"(primary {waves[primary] * 1000:.1f} nm){pending}"
        )
        self._show_status(text)

    def _show_status(self, text: str, error: bool = False) -> None:
        self.lblStatus.setText(text)
        self.lblStatus.setStyleSheet("color: #c0392b;" if error else "")

    def _draw_pattern(self) -> None:
        figure = self.patternFigure
        figure.clear()
        ax = figure.add_subplot(111)
        theta = np.linspace(0.0, 90.0, 181)
        ax.plot(theta, np.cos(np.radians(theta)), ls="--", lw=1.0, label="Lambert")
        try:
            pattern = self.build_pattern()
        except ValueError:
            pattern = None
        if pattern is not None and pattern.kind != "lambertian":
            ax.plot(theta, pattern.intensity(theta), lw=1.5, label="LED")
            ax.legend(fontsize=7, loc="upper right")
        ax.set_xlim(0.0, 90.0)
        ax.set_ylim(0.0, 1.05)
        ax.set_xlabel("Angle (°)", fontsize=8)
        ax.set_ylabel("Rel. intensity", fontsize=8)
        ax.tick_params(labelsize=7)
        gui_plot_utils.apply_theme_to_existing_figure(figure)
        self.patternCanvas.draw_idle()

    def _draw_spectrum(self) -> None:
        figure = self.spectrumFigure
        figure.clear()
        ax = figure.add_subplot(111)
        try:
            spectrum = self.build_spectrum()
            nodes, _ = spectrum.representative_wavelengths(
                self.spnWavelengthCount.value()
            )
        except ValueError:
            spectrum, nodes = None, []
        if spectrum is not None:
            waves, power = spectrum.density()
            nm = np.asarray(waves) * 1000.0
            if spectrum.kind == "line":
                ax.vlines(nm, 0.0, 1.0, lw=1.5)
                ax.set_xlim(nm[0] - 20.0, nm[0] + 20.0)
            else:
                ax.plot(nm, np.asarray(power) / np.max(power), lw=1.5)
                ax.set_xlim(nm[0], nm[-1])
            for node in nodes:
                ax.axvline(node * 1000.0, ls=":", lw=1.0)
        ax.set_ylim(0.0, 1.05)
        ax.set_xlabel("Wavelength (nm)", fontsize=8)
        ax.set_ylabel("Rel. power", fontsize=8)
        ax.tick_params(labelsize=7)
        gui_plot_utils.apply_theme_to_existing_figure(figure)
        self.spectrumCanvas.draw_idle()
