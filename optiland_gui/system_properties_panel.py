"""
Provides the GUI panel for editing system-wide optical properties.

This module defines the `SystemPropertiesPanel` which contains editors for
aperture, fields, wavelengths, and other system settings. It uses a navigation
tree to switch between different property editors.

@author: Manuel Fragata Mendes, 2025
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QAbstractItemView,
    QAbstractSpinBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from optiland.fields import (
    AngleField,
    ObjectHeightField,
    ParaxialImageHeightField,
    RealImageHeightField,
)

from .utils.table_copy import TableCopySupport

if TYPE_CHECKING:
    from .optiland_connector import OptilandConnector

_FIELD_TYPE_MAP: dict[type, str] = {
    AngleField: "angle",
    ObjectHeightField: "object_height",
    ParaxialImageHeightField: "paraxial_image_height",
    RealImageHeightField: "real_image_height",
}

_APERTURE_DESCRIPTIONS: dict[str, str] = {
    "EPD": (
        "Sets the aperture by specifying the diameter of the entrance pupil — the "
        "apparent opening of the lens as seen from the object side. A larger diameter "
        "collects more light and can resolve finer detail, but increases aberrations. "
        "Use this when you want to work directly in physical units (mm). This is the "
        "most common aperture specification for camera lenses, telescopes, and general "
        "imaging optics."
    ),
    "imageFNO": (
        "The image-space F-number (F/#) is the ratio of focal length to entrance pupil "
        "diameter. A lower F/# (e.g. F/1.4) means a faster lens that collects more "
        "light; a higher F/# (e.g. F/16) gives greater depth of field but less "
        "throughput. F/# is scale-independent, making it easy to compare lenses of "
        "different sizes. It is the familiar 'f-stop' setting in photography."
    ),
    "objectNA": (
        "Numerical Aperture (NA) on the object side measures the cone of light "
        "accepted from the object: NA = n × sin(θ), where n is the refractive index "
        "and θ is the half-angle of the acceptance cone. Higher NA means finer "
        "resolution and more light collection. NA is the standard aperture "
        "specification for microscope objectives and is also used in fiber coupling "
        "and data storage optics."
    ),
    "float_by_stop_size": (
        "The aperture is defined by the physical size of the aperture stop surface "
        "itself. The entrance pupil diameter is then computed automatically by tracing "
        "a ray from the stop back to the entrance side. Use this when designing around "
        "a component with a fixed physical opening — such as a purchased iris or a "
        "lens barrel — rather than targeting a specific F/# or NA value."
    ),
}

_FIELD_TYPE_DESCRIPTIONS: dict[str, str] = {
    "Angle": (
        "Each field point is specified by the angle (in degrees) between the incoming "
        "chief ray and the optical axis. This is the natural choice for systems viewing "
        "distant or infinite objects — cameras, telescopes, and collimated-beam "
        "instruments — where you know the angular field of view (e.g. ±5°). Cannot be "
        "used when the object space is telecentric (chief rays must be parallel to the "
        "axis)."
    ),
    "Object Height": (
        "Each field point is specified by its physical distance (mm) from the optical "
        "axis at the object plane. Use this for finite-conjugate systems — microscopes, "
        "scanners, and machine-vision cameras — where you know the physical size of the "
        "object being imaged. Only valid when the object is at a finite (not infinite) "
        "distance."
    ),
    "Paraxial Image Height": (
        "Each field point is specified by its desired height at the image plane, "
        "estimated using first-order (paraxial) optics. The system works backwards to "
        "find the object position that produces the target image height. Practical when "
        "you know your sensor size and want to fill it predictably. Faster than Real "
        "Image Height; accurate enough when distortion is small."
    ),
    "Real Image Height": (
        "Each field point is specified by the actual chief-ray height at the image "
        "plane, verified by real ray tracing. The system iteratively adjusts the object "
        "position until a traced ray lands at exactly the specified height. Use this "
        "when your design has significant distortion — wide-angle or fisheye lenses — "
        "and field positions must match actual image locations rather than the paraxial "
        "prediction. More accurate, but slower to compute."
    ),
}

_POLARIZATION_DESCRIPTIONS: dict[str, str] = {
    "Ignore": (
        "Polarization is not tracked. Rays carry only scalar intensity, and "
        "polarization-dependent effects such as coating reflectance variation or "
        "birefringence are ignored. This is the fastest option and is appropriate for "
        "most everyday design and analysis tasks — ray tracing, aberrations, MTF — "
        "where polarization is not a concern."
    ),
    "Unpolarized": (
        "Light is modelled as unpolarized — a statistical mixture of all polarization "
        "orientations with equal probability. The simulation averages "
        "polarization-dependent effects, so coating reflections and losses are "
        "computed realistically. Use this when your source has no preferred polarization "
        "direction, such as an LED, lamp, or natural light, and you want to check how "
        "coatings affect overall throughput."
    ),
    "Polarized": (
        "Light has a precisely defined polarization state described by the electric "
        "field amplitudes Ex and Ey and their phase difference. Use this when your "
        "source produces polarized light — a laser, a beam after a linear polarizer, "
        "or LCD illumination — or when analysing polarization-sensitive effects such "
        "as wave plates, stress birefringence, or contrast in polarimetric instruments."
    ),
}

_RAY_AIMING_DESCRIPTIONS: dict[str, str] = {
    "Paraxial": (
        "Rays are aimed through the entrance pupil using a fast first-order "
        "approximation: pupil position and size are estimated from a single paraxial "
        "trace and ray starting conditions are scaled accordingly. This works well for "
        "most standard imaging systems. It can fail for ring apertures (annular stops), "
        "very wide fields, or pupils that differ significantly from the paraxial "
        "estimate — try Iterative or Robust in those cases."
    ),
    "Iterative": (
        "Rays are aimed by iteratively adjusting their starting conditions until they "
        "actually pass through the correct position on the aperture stop, verified by "
        "real ray tracing. More accurate than Paraxial because real rays are used "
        "rather than a linear approximation. Works well for annular pupils, ring stops, "
        "and moderately complex systems. If some rays still fail to converge, try "
        "Robust mode."
    ),
    "Robust": (
        "The most reliable ray aiming mode. Starting from the paraxial solution, rays "
        "are guided toward the real solution in small incremental steps (homotopy "
        "continuation), enabling convergence even for severely distorted pupils or "
        "strongly oblique fields where direct iteration fails. Best for very wide-angle "
        "lenses, telecentric designs, or any system where Iterative mode gives "
        "incomplete results. Slowest of the three options."
    ),
}


class SystemPropertiesPanel(QWidget):
    """
    A widget that provides a user interface for editing system properties.

    This panel uses a QTreeWidget for navigation and a QStackedWidget to display
    the corresponding editor for each property (e.g., Aperture, Fields).

    Attributes:
        connector (OptilandConnector): The connector to the main application logic.
        navTree (QTreeWidget): The navigation tree for selecting property editors.
        stackedWidget (QStackedWidget): The widget that holds the different editor
        pages.
        apertureEditor (ApertureEditor): The editor for aperture settings.
        fieldsEditor (FieldsEditor): The editor for field settings.
        wavelengthsEditor (WavelengthsEditor): The editor for wavelength settings.
    """

    def __init__(self, connector: OptilandConnector, parent=None):
        """Initializes the SystemPropertiesPanel."""
        super().__init__(parent)
        self.connector = connector
        self.setWindowTitle("System Properties")

        self._init_ui()
        self._create_editor_pages()

        self.navTree.itemClicked.connect(self.on_nav_item_clicked)
        self.navTree.expandAll()
        if self.navTree.topLevelItemCount() > 0:
            self.navTree.setCurrentItem(self.navTree.topLevelItem(0))
            self.stackedWidget.setCurrentIndex(0)

        self.connector.opticLoaded.connect(self.load_properties)
        self.connector.opticChanged.connect(self.load_properties)

    def _init_ui(self):
        """Initializes the main layout, navigation tree,
        and stacked widget."""
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        self.navTree = QTreeWidget()
        self.navTree.setHeaderHidden(True)
        self.navTree.setMinimumWidth(120)
        main_layout.addWidget(self.navTree)

        self.stackedWidget = QStackedWidget()
        self.stackedWidget.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        main_layout.addWidget(self.stackedWidget)

    def _create_editor_pages(self):
        """Creates and adds all the property editor pages to the
        navigation tree and stacked widget."""
        self.metadataEditor = MetadataEditor(self.connector)
        self.apertureEditor = ApertureEditor(self.connector)
        self.fieldsEditor = FieldsEditor(self.connector)
        self.wavelengthsEditor = WavelengthsEditor(self.connector)
        self.polarizationEditor = PolarizationEditor(self.connector)
        self.rayAimingEditor = RayAimingEditor(self.connector)

        self.add_nav_item("Metadata", self.metadataEditor)
        self.add_nav_item("Aperture", self.apertureEditor)
        self.add_nav_item("Fields", self.fieldsEditor)
        self.add_nav_item("Wavelengths", self.wavelengthsEditor)
        self.add_nav_item("Polarization", self.polarizationEditor)
        self.add_nav_item("Ray Aiming", self.rayAimingEditor)

    def add_nav_item(self, name, widget):
        """
        Adds a navigation item and its corresponding widget editor.

        Args:
            name (str): The name to display in the navigation tree.
            widget (QWidget): The editor widget to add to the stacked layout.
        """
        item = QTreeWidgetItem(self.navTree, [name])
        index = self.stackedWidget.addWidget(widget)
        item.setData(0, Qt.ItemDataRole.UserRole, index)

    @Slot(QTreeWidgetItem, int)
    def on_nav_item_clicked(self, item, column):
        """
        Handles clicks on navigation tree items to switch editor pages.

        Args:
            item (QTreeWidgetItem): The clicked tree widget item.
            column (int): The column index that was clicked.
        """
        index = item.data(0, Qt.ItemDataRole.UserRole)
        if index is not None:
            self.stackedWidget.setCurrentIndex(index)

    @Slot()
    def load_properties(self):
        """Loads or reloads data into all property editors."""
        self.metadataEditor.load_data()
        self.apertureEditor.load_data()
        self.fieldsEditor.load_data()
        self.wavelengthsEditor.load_data()
        self.polarizationEditor.load_data()
        self.rayAimingEditor.load_data()


class PropertyEditorBase(QWidget):
    """
    Abstract base class for property editor widgets.

    Provides a common structure for editors, including an OptilandConnector,
    a loading flag to prevent recursive updates, and abstract methods for UI
    initialization and data loading.

    Attributes:
        connector (OptilandConnector): The connector to the main application logic.
        is_loading (bool): A flag to indicate if data is being loaded, to prevent
                           unwanted signal emissions.
    """

    def __init__(self, connector: OptilandConnector, parent=None):
        """
        Initializes the PropertyEditorBase.

        Args:
            connector (OptilandConnector): The connector to the main application logic.
            parent (QWidget, optional): The parent widget. Defaults to None.
        """
        super().__init__(parent)
        self.connector = connector
        self.is_loading = False
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.init_ui()
        self.connector.opticLoaded.connect(self.load_data)
        self.connector.opticChanged.connect(self.load_data)

    def init_ui(self):
        """
        Initializes the user interface of the editor.

        This method must be implemented by subclasses.
        """
        raise NotImplementedError

    def load_data(self):
        """
        Loads data from the optical system into the editor's widgets.

        This method must be implemented by subclasses.
        """
        raise NotImplementedError

    @staticmethod
    def _make_description_box() -> QTextEdit:
        """Create a read-only text box for displaying setting descriptions."""
        box = QTextEdit()
        box.setReadOnly(True)
        box.setFixedHeight(110)
        box.setStyleSheet(
            "QTextEdit {"
            "  border: 1px solid palette(mid);"
            "  border-radius: 3px;"
            "  padding: 4px;"
            "  font-size: 11px;"
            "}"
        )
        return box


class MetadataEditor(PropertyEditorBase):
    """Editor for the system name and description metadata."""

    def init_ui(self) -> None:
        """Initialises the metadata editor UI."""
        layout = QFormLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        self.txtName = QLineEdit()
        self.txtName.setPlaceholderText("Default System")
        layout.addRow("Name:", self.txtName)

        self.txtDescription = QTextEdit()
        self.txtDescription.setPlaceholderText("Enter a system description…")
        self.txtDescription.setMinimumHeight(120)
        layout.addRow("Description:", self.txtDescription)

        self.btnApply = QPushButton("Apply Metadata")
        layout.addRow(self.btnApply)

        self.btnApply.clicked.connect(self._apply_changes)

    @Slot()
    def _apply_changes(self) -> None:
        """Write the current name and description back to the optic."""
        if self.is_loading:
            return
        name = self.txtName.text().strip()
        description = self.txtDescription.toPlainText().strip()
        self.connector.set_metadata(name, description)

    @Slot()
    def load_data(self) -> None:
        """Load name and description from the optic into the UI."""
        self.is_loading = True
        name, description = self.connector.get_metadata()
        self.txtName.setText(name)
        self.txtDescription.setPlainText(description)
        self.is_loading = False


class ApertureEditor(PropertyEditorBase):
    """A widget for editing the aperture properties of the optical system."""

    def init_ui(self):
        """Initializes the UI for the aperture editor."""
        layout = QFormLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        self.cmbApertureType = QComboBox()
        self.cmbApertureType.addItems(self.connector.get_aperture_types())
        layout.addRow("Aperture Type:", self.cmbApertureType)

        self.descAperture = self._make_description_box()
        layout.addRow(self.descAperture)

        self.spnApertureValue = QDoubleSpinBox()
        self.spnApertureValue.setDecimals(4)
        self.spnApertureValue.setRange(-1e9, 1e9)
        self.spnApertureValue.setSingleStep(0.1)
        layout.addRow("Value:", self.spnApertureValue)

        self.btnApplyAperture = QPushButton("Apply Aperture Changes")
        layout.addRow(self.btnApplyAperture)

        self.cmbApertureType.currentTextChanged.connect(self._update_aperture_description)
        self.cmbApertureType.currentTextChanged.connect(self.apply_aperture_changes)
        self.spnApertureValue.valueChanged.connect(self.apply_aperture_changes)
        self.btnApplyAperture.clicked.connect(self.apply_aperture_changes)

        self._update_aperture_description(self.cmbApertureType.currentText())

    @Slot(str)
    def _update_aperture_description(self, key: str) -> None:
        """Update the description box when the aperture type selection changes."""
        self.descAperture.setPlainText(
            _APERTURE_DESCRIPTIONS.get(key, "No description available for this aperture type.")
        )

    @Slot()
    def load_data(self):
        """Loads aperture data from the current optical system into the UI."""
        self.is_loading = True
        optic = self.connector.get_optic()
        if optic and optic.aperture:
            self.cmbApertureType.setCurrentText(optic.aperture.ap_type)
            self.spnApertureValue.setValue(optic.aperture.value)
        else:
            self.cmbApertureType.setCurrentIndex(0)
            self.spnApertureValue.setValue(10.0)
        self.is_loading = False

    @Slot()
    def apply_aperture_changes(self):
        """Applies the UI settings to the optical system's aperture."""
        if self.is_loading:
            return
        optic = self.connector.get_optic()
        if optic:
            ap_type = self.cmbApertureType.currentText()
            ap_value = self.spnApertureValue.value()
            try:
                optic.set_aperture(ap_type, ap_value)
                self.connector.opticChanged.emit()
                print(f"Aperture updated: {ap_type}, {ap_value}")
            except ValueError as e:
                print(f"Aperture Error: {e}")
                self.load_data()


class FieldsEditor(PropertyEditorBase):
    """A widget for editing the field points of the optical system."""

    def init_ui(self):
        """Initializes the UI for the fields editor."""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)

        self._create_type_selector(main_layout)
        self._create_fields_table(main_layout)
        self._create_control_buttons(main_layout)

        self.cmbFieldType.currentTextChanged.connect(self._update_field_description)
        self.cmbFieldType.currentTextChanged.connect(self.apply_field_type_change)
        self.btnAddField.clicked.connect(self.add_field)
        self.btnRemoveField.clicked.connect(self.remove_field)
        self.btnApplyFields.clicked.connect(self.apply_table_field_changes)

        self._update_field_description(self.cmbFieldType.currentText())

    def _create_type_selector(self, parent_layout):
        """Creates the field type dropdown menu and its description box."""
        form_layout = QFormLayout()
        self.cmbFieldType = QComboBox()
        for _display, key in self.connector.get_field_types():
            self.cmbFieldType.addItem(_display, userData=key)
        form_layout.addRow("Field Type:", self.cmbFieldType)
        parent_layout.addLayout(form_layout)

        self.descFieldType = self._make_description_box()
        parent_layout.addWidget(self.descFieldType)

    def _create_fields_table(self, parent_layout):
        """Creates the table for editing field points."""
        self.tableFields = QTableWidget()
        self.tableFields.setColumnCount(4)
        self.tableFields.setHorizontalHeaderLabels(
            ["X-Field", "Y-Field", "Vignette X", "Vignette Y"]
        )
        self.tableFields.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self._table_fields_copy = TableCopySupport(self.tableFields)
        parent_layout.addWidget(self.tableFields)

    def _create_control_buttons(self, parent_layout):
        """Creates the Add, Remove, and Apply buttons."""
        button_layout = QHBoxLayout()
        self.btnAddField = QPushButton("Add Field")
        self.btnRemoveField = QPushButton("Remove Field")
        self.btnApplyFields = QPushButton("Apply Field Changes")
        button_layout.addWidget(self.btnAddField)
        button_layout.addWidget(self.btnRemoveField)
        button_layout.addWidget(self.btnApplyFields)
        parent_layout.addLayout(button_layout)

    @Slot(str)
    def _update_field_description(self, display_name: str) -> None:
        """Update the description box when the field type selection changes."""
        self.descFieldType.setPlainText(
            _FIELD_TYPE_DESCRIPTIONS.get(display_name, "No description available for this field type.")
        )

    @Slot()
    def load_data(self):
        """Loads field data from the current optical system into the table."""
        self.is_loading = True
        optic = self.connector.get_optic()
        if optic and optic.fields and optic.fields.field_definition:
            key = _FIELD_TYPE_MAP.get(type(optic.fields.field_definition))
            if key is not None:
                for i in range(self.cmbFieldType.count()):
                    if self.cmbFieldType.itemData(i) == key:
                        self.cmbFieldType.setCurrentIndex(i)
                        break

        self.tableFields.setRowCount(0)
        if optic and optic.fields:
            num_fields = optic.fields.num_fields
            self.tableFields.setRowCount(num_fields)
            for i, field_obj in enumerate(optic.fields.fields):
                self.tableFields.setVerticalHeaderItem(i, QTableWidgetItem(str(i)))
                self.tableFields.setItem(i, 0, QTableWidgetItem(str(field_obj.x)))
                self.tableFields.setItem(i, 1, QTableWidgetItem(str(field_obj.y)))
                self.tableFields.setItem(i, 2, QTableWidgetItem(str(field_obj.vx)))
                self.tableFields.setItem(i, 3, QTableWidgetItem(str(field_obj.vy)))
        self.is_loading = False

    @Slot()
    def apply_field_type_change(self):
        """Applies the selected field type to the optical system."""
        if self.is_loading:
            return
        optic = self.connector.get_optic()
        if optic:
            new_type = self.cmbFieldType.currentData()
            if new_type is None:
                return
            try:
                optic.fields.set_type(new_type)
                self.connector.opticChanged.emit()
                print(f"Field type changed to: {new_type}")
            except ValueError as e:
                print(f"Field Type Error: {e}")
                # Revert UI to match model state
                self.load_data()

    @Slot()
    def add_field(self):
        """Adds a new field point to the optical system."""
        optic = self.connector.get_optic()
        if optic:
            y_val = (
                optic.fields.max_y_field * 0.5
                if optic.fields.num_fields > 0 and optic.fields.max_y_field > 0
                else 1.0
                if optic.fields.num_fields == 0
                else 0.0
            )

            optic.fields.add(y=y_val)
            self.load_data()
            self.connector.opticChanged.emit()
            print("Field added.")

    @Slot()
    def remove_field(self):
        """Removes the selected field point from the optical system."""
        optic = self.connector.get_optic()
        current_row = self.tableFields.currentRow()
        if optic and current_row != -1 and optic.fields.num_fields > current_row:
            del optic.fields.fields[current_row]
            self.load_data()
            self.connector.opticChanged.emit()
            print(f"Field at row {current_row} removed.")

    def _update_field_from_row(self, row_index):
        """Reads data from a table row and updates the corresponding field object.
        Returns True if a change was made."""
        try:
            x = float(self.tableFields.item(row_index, 0).text())
            y = float(self.tableFields.item(row_index, 1).text())
            vx = float(self.tableFields.item(row_index, 2).text())
            vy = float(self.tableFields.item(row_index, 3).text())

            field_obj = self.connector.get_optic().fields.fields[row_index]
            if (
                field_obj.x != x
                or field_obj.y != y
                or field_obj.vx != vx
                or field_obj.vy != vy
            ):
                field_obj.x, field_obj.y, field_obj.vx, field_obj.vy = x, y, vx, vy
                return True
        except (ValueError, AttributeError) as e:
            print(f"Invalid data in fields table row {row_index + 1}: {e}")
            # Re-raise the exception to be handled by the caller
            raise ValueError(f"Invalid data in row {row_index + 1}") from e
        return False

    @Slot()
    def apply_table_field_changes(self):
        """Applies changes from the fields table to the optical system."""
        optic = self.connector.get_optic()
        if not (optic and optic.fields):
            return

        if self.tableFields.rowCount() != optic.fields.num_fields:
            self.load_data()  # Mismatch, so reload to be safe
            return

        any_changed = False
        try:
            for i in range(self.tableFields.rowCount()):
                if self._update_field_from_row(i):
                    any_changed = True
        except ValueError:
            self.load_data()  # Reload table on error to show original valid data
            return

        if any_changed:
            self.connector.opticChanged.emit()
            print("Field table changes applied.")


class WavelengthsEditor(PropertyEditorBase):
    """A widget for editing the wavelengths of the optical system."""

    def init_ui(self):
        """Initializes the UI for the wavelengths editor."""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)

        self._create_wavelengths_table(main_layout)
        self._create_control_buttons(main_layout)

        self.btnAddWavelength.clicked.connect(self.add_wavelength)
        self.btnRemoveWavelength.clicked.connect(self.remove_wavelength)
        self.btnSetPrimary.clicked.connect(self.set_primary_wavelength)
        self.btnApplyWavelengths.clicked.connect(self.apply_table_wavelength_changes)

    def _create_wavelengths_table(self, parent_layout):
        """Creates the table for editing wavelengths."""
        self.tableWavelengths = QTableWidget()
        self.tableWavelengths.setColumnCount(3)
        self.tableWavelengths.setHorizontalHeaderLabels(
            ["Value (µm)", "Unit", "Primary"]
        )
        self.tableWavelengths.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.tableWavelengths.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.tableWavelengths.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self._table_wavelengths_copy = TableCopySupport(self.tableWavelengths)
        parent_layout.addWidget(self.tableWavelengths)

    def _create_control_buttons(self, parent_layout):
        """Creates the control buttons for managing wavelengths."""
        button_layout = QHBoxLayout()
        self.btnAddWavelength = QPushButton("Add Wavelength")
        self.btnRemoveWavelength = QPushButton("Remove Wavelength")
        self.btnSetPrimary = QPushButton("Set Selected as Primary")
        self.btnApplyWavelengths = QPushButton("Apply Wavelength Changes")
        button_layout.addWidget(self.btnAddWavelength)
        button_layout.addWidget(self.btnRemoveWavelength)
        button_layout.addWidget(self.btnSetPrimary)
        button_layout.addWidget(self.btnApplyWavelengths)
        parent_layout.addLayout(button_layout)

    @Slot()
    def load_data(self):
        """Loads wavelength data from the current optical system into the table."""
        self.is_loading = True
        self.tableWavelengths.setRowCount(0)
        optic = self.connector.get_optic()
        if optic and optic.wavelengths:
            num_wl = optic.wavelengths.num_wavelengths
            self.tableWavelengths.setRowCount(num_wl)
            for i, wl_obj in enumerate(optic.wavelengths.wavelengths):
                self.tableWavelengths.setVerticalHeaderItem(i, QTableWidgetItem(str(i)))
                self.tableWavelengths.setItem(
                    i, 0, QTableWidgetItem(f"{wl_obj.value:.4f}")
                )
                item_unit = QTableWidgetItem(
                    wl_obj._unit if hasattr(wl_obj, "_unit") else "um"
                )
                item_unit.setFlags(item_unit.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.tableWavelengths.setItem(i, 1, item_unit)

                primary_item = QTableWidgetItem("Yes" if wl_obj.is_primary else "No")
                primary_item.setFlags(
                    primary_item.flags() & ~Qt.ItemFlag.ItemIsEditable
                )
                self.tableWavelengths.setItem(i, 2, primary_item)
        self.is_loading = False

    @Slot()
    def add_wavelength(self):
        """Adds a new wavelength to the optical system."""
        optic = self.connector.get_optic()
        if optic:
            is_new_primary = optic.wavelengths.num_wavelengths == 0
            optic.wavelengths.add(0.6328, is_primary=is_new_primary, unit="um")
            self.load_data()
            self.connector.opticChanged.emit()
            print("Wavelength added.")

    @Slot()
    def remove_wavelength(self):
        """Removes the selected wavelength from the optical system."""
        optic = self.connector.get_optic()
        current_row = self.tableWavelengths.currentRow()
        if (
            optic
            and current_row != -1
            and optic.wavelengths.num_wavelengths > current_row
        ):
            if optic.wavelengths.num_wavelengths == 1:
                print("Cannot remove the last wavelength.")
                return

            was_primary = optic.wavelengths.wavelengths[current_row].is_primary
            del optic.wavelengths.wavelengths[current_row]

            if was_primary and optic.wavelengths.num_wavelengths > 0:
                optic.wavelengths.wavelengths[0].is_primary = True

            self.load_data()
            self.connector.opticChanged.emit()
            print(f"Wavelength at row {current_row} removed.")

    @Slot()
    def set_primary_wavelength(self):
        """Sets the selected wavelength as the primary wavelength."""
        optic = self.connector.get_optic()
        current_row = self.tableWavelengths.currentRow()
        if (
            optic
            and current_row != -1
            and optic.wavelengths.num_wavelengths > current_row
        ):
            for i, wl_obj in enumerate(optic.wavelengths.wavelengths):
                wl_obj.is_primary = i == current_row
            self.load_data()
            self.connector.opticChanged.emit()
            print(f"Wavelength at row {current_row} set as primary.")

    @Slot()
    def apply_table_wavelength_changes(self):
        """Applies changes from the wavelengths table to the optical system."""
        optic = self.connector.get_optic()
        if self.is_loading or not optic or not optic.wavelengths:
            return

        changed = False
        if self.tableWavelengths.rowCount() == optic.wavelengths.num_wavelengths:
            for i in range(self.tableWavelengths.rowCount()):
                try:
                    new_val_um_str = self.tableWavelengths.item(i, 0).text()
                    new_val_um = float(new_val_um_str)

                    wl_obj = optic.wavelengths.wavelengths[i]
                    if wl_obj.value != new_val_um:
                        wl_obj._value = new_val_um
                        wl_obj._unit = "um"
                        wl_obj._value_in_um = new_val_um
                        changed = True
                except (ValueError, AttributeError):
                    print(f"Invalid numeric data in Wavelengths table row {i + 1}.")
                    self.load_data()
                    return
            if changed:
                self.connector.opticChanged.emit()
                print("Wavelength table changes applied.")
        else:
            self.load_data()


class PolarizationEditor(PropertyEditorBase):
    """A widget for configuring the polarization state of the optical system.

    Provides a combobox to select between Ignore, Unpolarized, or Polarized
    and four numeric inputs for Ex, Ey, Phase X, and Phase Y.
    Phase values are shown in degrees; they are converted to radians before
    being passed to the core.

    When mode is not "Polarized", all four spin boxes are disabled.
    Validation errors are shown via an inline error label instead of a dialog.
    """

    def init_ui(self) -> None:
        """Initializes the polarization editor UI."""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)

        layout_mode = QHBoxLayout()
        layout_mode.addWidget(QLabel("Mode:"))
        self.cmbMode = QComboBox()
        self.cmbMode.addItems(["Ignore", "Unpolarized", "Polarized"])
        layout_mode.addWidget(self.cmbMode)
        layout_mode.addStretch()
        main_layout.addLayout(layout_mode)

        self.descPolarization = self._make_description_box()
        main_layout.addWidget(self.descPolarization)

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(8)

        self.spnEx = self._make_spinbox()
        self.spnEy = self._make_spinbox()
        self.spnPhaseX = self._make_angle_spinbox()
        self.spnPhaseY = self._make_angle_spinbox()

        form.addRow("Ex:", self.spnEx)
        form.addRow("Ey:", self.spnEy)
        form.addRow("Phase X (°):", self.spnPhaseX)
        form.addRow("Phase Y (°):", self.spnPhaseY)
        main_layout.addLayout(form)

        self.lblError = QLabel()
        self.lblError.setWordWrap(True)
        self.lblError.setStyleSheet("color: red;")
        self.lblError.hide()
        main_layout.addWidget(self.lblError)

        self.btnApply = QPushButton("Apply Polarization")
        main_layout.addWidget(self.btnApply)
        main_layout.addStretch()

        self.cmbMode.currentIndexChanged.connect(self._on_mode_changed)
        self.btnApply.clicked.connect(self.apply_polarization)

        self._set_inputs_enabled(False)
        self._update_polarization_description(0)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _make_spinbox(self) -> QDoubleSpinBox:
        """Return a QDoubleSpinBox suitable for Ex / Ey amplitude."""
        spn = QDoubleSpinBox()
        spn.setDecimals(6)
        spn.setRange(-1e9, 1e9)
        spn.setSingleStep(0.1)
        return spn

    def _make_angle_spinbox(self) -> QDoubleSpinBox:
        """Return a QDoubleSpinBox suitable for phase angles in degrees."""
        spn = QDoubleSpinBox()
        spn.setDecimals(4)
        spn.setRange(-360.0, 360.0)
        spn.setSingleStep(1.0)
        spn.setSuffix(" °")
        return spn

    def _set_inputs_enabled(self, enabled: bool) -> None:
        """Enable or disable the four numeric spin boxes."""
        for spn in (self.spnEx, self.spnEy, self.spnPhaseX, self.spnPhaseY):
            spn.setEnabled(enabled)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    @Slot(int)
    def _on_mode_changed(self, index: int) -> None:
        """Enable/disable numeric inputs and refresh description when mode changes."""
        self._set_inputs_enabled(index == 2)
        self.lblError.hide()
        self._update_polarization_description(index)

    def _update_polarization_description(self, index: int) -> None:
        """Update the description box for the given polarization mode index."""
        modes = ["Ignore", "Unpolarized", "Polarized"]
        key = modes[index] if 0 <= index < len(modes) else ""
        self.descPolarization.setPlainText(
            _POLARIZATION_DESCRIPTIONS.get(key, "No description available.")
        )

    @Slot()
    def load_data(self) -> None:
        """Load the current polarization state from the optic into the UI."""
        self.is_loading = True
        optic = self.connector.get_optic()
        self.lblError.hide()

        if optic is None:
            self.cmbMode.setCurrentIndex(0)
            self._set_inputs_enabled(False)
            self.is_loading = False
            return

        pol = optic.polarization
        if pol == "ignore" or pol is None:
            self.cmbMode.setCurrentIndex(0)
            self._set_inputs_enabled(False)
            self.spnEx.setValue(0.0)
            self.spnEy.setValue(0.0)
            self.spnPhaseX.setValue(0.0)
            self.spnPhaseY.setValue(0.0)
        elif hasattr(pol, "is_polarized"):
            if pol.is_polarized:
                self.cmbMode.setCurrentIndex(2)
                self._set_inputs_enabled(True)
                # Ex / Ey may be backend tensors; convert to plain float
                self.spnEx.setValue(float(pol.Ex))
                self.spnEy.setValue(float(pol.Ey))
                self.spnPhaseX.setValue(math.degrees(float(pol.phase_x)))
                self.spnPhaseY.setValue(math.degrees(float(pol.phase_y)))
            else:
                self.cmbMode.setCurrentIndex(1)
                self._set_inputs_enabled(False)
                self.spnEx.setValue(0.0)
                self.spnEy.setValue(0.0)
                self.spnPhaseX.setValue(0.0)
                self.spnPhaseY.setValue(0.0)
        else:
            self.cmbMode.setCurrentIndex(0)
            self._set_inputs_enabled(False)
            self.spnEx.setValue(0.0)
            self.spnEy.setValue(0.0)
            self.spnPhaseX.setValue(0.0)
            self.spnPhaseY.setValue(0.0)

        self.is_loading = False

    @Slot()
    def apply_polarization(self) -> None:
        """Read the form and apply the polarization state to the optic."""
        if self.is_loading:
            return
        self.lblError.hide()

        mode_idx = self.cmbMode.currentIndex()
        if mode_idx == 0:
            mode = "ignore"
        elif mode_idx == 1:
            mode = "unpolarized"
        else:
            mode = "polarized"

        if mode == "polarized":
            Ex = self.spnEx.value()
            Ey = self.spnEy.value()
            phase_x_deg = self.spnPhaseX.value()
            phase_y_deg = self.spnPhaseY.value()
        else:
            Ex = Ey = phase_x_deg = phase_y_deg = None

        try:
            self.connector.set_polarization_state(
                mode, Ex, Ey, phase_x_deg, phase_y_deg
            )
            # Reload to display the normalized values the core computed
            self.load_data()
        except ValueError as exc:
            self.lblError.setText(str(exc))
            self.lblError.show()


class RayAimingEditor(PropertyEditorBase):
    """Editor for the ray aiming strategy used during ray tracing.

    Exposes the three available modes (Paraxial, Iterative, Robust) along with
    convergence controls (max iterations and tolerance) so the user can tune
    tracing behaviour without touching the Python API directly.

    This is particularly relevant for systems with annular or complex pupils
    (e.g. ring apertures) where paraxial ray aiming may block all rays.
    """

    _MODE_DISPLAY = ["Paraxial", "Iterative", "Robust"]
    _MODE_KEYS = ["paraxial", "iterative", "robust"]

    def init_ui(self) -> None:
        """Initialises the ray aiming editor UI."""
        layout = QFormLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        self.cmbMode = QComboBox()
        self.cmbMode.addItems(self._MODE_DISPLAY)
        layout.addRow("Mode:", self.cmbMode)

        self.descRayAiming = self._make_description_box()
        layout.addRow(self.descRayAiming)

        self.spnMaxIter = QSpinBox()
        self.spnMaxIter.setRange(1, 10000)
        self.spnMaxIter.setValue(10)
        layout.addRow("Max Iterations:", self.spnMaxIter)

        self.spnTol = QDoubleSpinBox()
        self.spnTol.setDecimals(10)
        self.spnTol.setRange(0.0, 1.0)
        self.spnTol.setValue(1e-6)
        self.spnTol.setStepType(QAbstractSpinBox.StepType.AdaptiveDecimalStepType)
        layout.addRow("Tolerance:", self.spnTol)

        self.btnApply = QPushButton("Apply Ray Aiming")
        layout.addRow(self.btnApply)

        self.cmbMode.currentTextChanged.connect(self._update_ray_aiming_description)
        self.btnApply.clicked.connect(self.apply_ray_aiming)

        self._update_ray_aiming_description(self.cmbMode.currentText())

    @Slot(str)
    def _update_ray_aiming_description(self, display_name: str) -> None:
        """Update the description box when the ray aiming mode selection changes."""
        self.descRayAiming.setPlainText(
            _RAY_AIMING_DESCRIPTIONS.get(display_name, "No description available.")
        )

    @Slot()
    def load_data(self) -> None:
        """Load the current ray aiming config from the optic into the UI."""
        self.is_loading = True
        optic = self.connector.get_optic()
        if optic is not None and hasattr(optic, "ray_tracer"):
            cfg = optic.ray_tracer.ray_aiming_config
            mode = cfg.get("mode", "paraxial")
            if mode in self._MODE_KEYS:
                self.cmbMode.setCurrentIndex(self._MODE_KEYS.index(mode))
            self.spnMaxIter.setValue(int(cfg.get("max_iter", 10)))
            self.spnTol.setValue(float(cfg.get("tol", 1e-6)))
        self.is_loading = False

    @Slot()
    def apply_ray_aiming(self) -> None:
        """Apply the UI settings to the optic's ray tracer."""
        if self.is_loading:
            return
        optic = self.connector.get_optic()
        if optic is not None and hasattr(optic, "ray_tracer"):
            old_state = self.connector._capture_optic_state()
            mode = self._MODE_KEYS[self.cmbMode.currentIndex()]
            max_iter = self.spnMaxIter.value()
            tol = self.spnTol.value()
            optic.ray_tracer.set_aiming(mode, max_iter=max_iter, tol=tol)
            self.connector._undo_redo_manager.add_state(old_state)
            self.connector.opticChanged.emit()
            print(f"Ray aiming updated: mode={mode}, max_iter={max_iter}, tol={tol}")
