"""Dialog for saving the selected lens element as a stock-catalog entry.

Opened from the Lens Data Editor context menu ("Add Element to Stock
Catalog..."). The dialog shows the extracted surface data read-only, lets the
user pick or type a manufacturer (new manufacturers create a new local catalog
cache), and persists the record through the connector's catalog service.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

_SURFACE_COLUMNS = ["Type", "Radius", "Thickness", "Material", "Conic", "Semi-Dia."]


class AddToCatalogDialog(QDialog):
    """Collect catalog metadata for a lens element extracted from the design."""

    def __init__(self, connector, draft: dict, parent=None) -> None:  # noqa: ANN001
        super().__init__(parent)
        self.connector = connector
        self._draft = draft
        self.saved_catalog_id: str | None = None

        self.setWindowTitle("Add Element to Stock Catalog")
        self.setObjectName("AddToCatalogDialog")
        self.setMinimumWidth(480)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        self.manufacturer_combo = QComboBox()
        self.manufacturer_combo.setEditable(True)
        self.manufacturer_combo.addItems(self._known_manufacturers())
        self.manufacturer_combo.setCurrentText("")
        self.manufacturer_combo.lineEdit().setPlaceholderText(
            "Existing or new manufacturer"
        )
        form.addRow("&Manufacturer:", self.manufacturer_combo)

        self.part_number_edit = QLineEdit()
        self.part_number_edit.setPlaceholderText("e.g. MV-100")
        form.addRow("&Part number:", self.part_number_edit)

        self.product_name_edit = QLineEdit(str(draft.get("product_name") or ""))
        self.product_name_edit.setPlaceholderText("Defaults to the part number")
        form.addRow("Product &name:", self.product_name_edit)

        self.category_edit = QLineEdit()
        self.category_edit.setPlaceholderText("e.g. achromat, singlet, mirror")
        form.addRow("&Category:", self.category_edit)

        layout.addLayout(form)

        summary_bits = []
        if draft.get("efl_mm") is not None:
            summary_bits.append(f"EFL {draft['efl_mm']:g} mm")
        if draft.get("diameter_mm") is not None:
            summary_bits.append(f"⌀ {draft['diameter_mm']:g} mm")
        if draft.get("center_thickness_mm") is not None:
            summary_bits.append(f"CT {draft['center_thickness_mm']:g} mm")
        if draft.get("material_summary"):
            summary_bits.append(str(draft["material_summary"]))
        summary = QLabel(
            f"{len(draft.get('surfaces', []))} surface(s)"
            + (" — " + ", ".join(summary_bits) if summary_bits else "")
        )
        summary.setWordWrap(True)
        layout.addWidget(summary)

        layout.addWidget(self._build_surface_preview(draft.get("surfaces", [])))

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        layout.addWidget(self._buttons)

        self.manufacturer_combo.editTextChanged.connect(self._update_save_enabled)
        self.part_number_edit.textChanged.connect(self._update_save_enabled)
        self._update_save_enabled()

    # ------------------------------------------------------------------
    # UI helpers
    # ------------------------------------------------------------------

    def _known_manufacturers(self) -> list[str]:
        try:
            return list(self.connector.get_catalog_manufacturers())
        except Exception:  # noqa: BLE001 - manufacturer prefill is optional
            return []

    def _build_surface_preview(self, surfaces: list[dict]) -> QTableWidget:
        table = QTableWidget(len(surfaces), len(_SURFACE_COLUMNS))
        table.setObjectName("CatalogSurfacePreviewTable")
        table.setHorizontalHeaderLabels(_SURFACE_COLUMNS)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        for row, spec in enumerate(surfaces):
            values = [
                str(spec.get("surface_type", "standard")),
                _format_number(spec.get("radius")),
                _format_number(spec.get("thickness")),
                str(spec.get("material", "")),
                _format_number(spec.get("conic")),
                _format_number(spec.get("semi_diameter"), empty="Auto"),
            ]
            for col, value in enumerate(values):
                table.setItem(row, col, QTableWidgetItem(value))
        table.resizeColumnsToContents()
        table.setMaximumHeight(
            table.horizontalHeader().height()
            + table.rowHeight(0) * max(1, min(len(surfaces), 6))
            + 8
        )
        return table

    def _update_save_enabled(self) -> None:
        save_button = self._buttons.button(QDialogButtonBox.StandardButton.Save)
        save_button.setEnabled(
            bool(self.manufacturer_combo.currentText().strip())
            and bool(self.part_number_edit.text().strip())
        )

    # ------------------------------------------------------------------
    # Result
    # ------------------------------------------------------------------

    def build_record_data(self) -> dict:
        """Merge the extracted draft with the user-entered metadata."""
        manufacturer = self.manufacturer_combo.currentText().strip()
        part_number = self.part_number_edit.text().strip()
        return {
            "manufacturer": manufacturer,
            "part_number": part_number,
            "product_name": self.product_name_edit.text().strip() or part_number,
            "category": self.category_edit.text().strip(),
            "efl_mm": self._draft.get("efl_mm"),
            "diameter_mm": self._draft.get("diameter_mm"),
            "center_thickness_mm": self._draft.get("center_thickness_mm"),
            "material_summary": self._draft.get("material_summary"),
            "surfaces": self._draft.get("surfaces", []),
            "stop_surface_offset": self._draft.get("stop_surface_offset"),
        }

    def accept(self) -> None:  # noqa: D102 - QDialog override
        try:
            self.saved_catalog_id = self.connector.add_catalog_record(
                self.build_record_data()
            )
        except Exception as exc:  # noqa: BLE001 - surfaced to the user instead
            self._notify(f"Could not save catalog entry: {exc}", "error")
            return
        super().accept()

    def _notify(self, message: str, level: str) -> None:
        toast_manager = getattr(self.window(), "toast_manager", None)
        if toast_manager is None:
            parent = self.parentWidget()
            while parent is not None and toast_manager is None:
                toast_manager = getattr(parent.window(), "toast_manager", None)
                parent = parent.parentWidget()
        if toast_manager is not None:
            toast_manager.notify(message, level)


def _format_number(value, empty: str = "") -> str:  # noqa: ANN001
    if value is None or value == "":
        return empty
    if isinstance(value, str):
        return value
    return f"{float(value):g}"
