"""Dockable stock-lens catalog browser panel."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QComboBox,
)

if TYPE_CHECKING:
    from .main_window import MainWindow
    from .optiland_connector import OptilandConnector


class CatalogBrowserPanel(QWidget):
    """Search, inspect, import, and insert stock-lens catalog records."""

    RESULT_COLUMNS = [
        "Manufacturer",
        "Part No.",
        "Name",
        "Category",
        "EFL",
        "Diameter",
    ]

    def __init__(self, connector: OptilandConnector, parent=None) -> None:
        super().__init__(parent)
        self.connector = connector
        self._current_results: list[dict] = []
        self._build_ui()
        self._wire_signals()
        self.refresh()

    def _build_ui(self) -> None:
        self.setObjectName("CatalogBrowserPanel")
        layout = QVBoxLayout(self)

        import_row = QHBoxLayout()
        self.import_edmund_button = QPushButton("Import Edmund Catalog")
        self.import_thorlabs_button = QPushButton("Import Thorlabs Catalog")
        import_row.addWidget(self.import_edmund_button)
        import_row.addWidget(self.import_thorlabs_button)
        import_row.addStretch(1)
        layout.addLayout(import_row)

        filters_box = QGroupBox("Search Filters")
        filters_layout = QGridLayout(filters_box)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search by part number, name, material...")
        self.manufacturer_combo = QComboBox()
        self.manufacturer_combo.addItem("All Manufacturers", "")
        self.category_edit = QLineEdit()
        self.category_edit.setPlaceholderText("e.g. achromat, plano-convex")
        self.efl_min_edit = QLineEdit()
        self.efl_max_edit = QLineEdit()
        self.diameter_min_edit = QLineEdit()
        self.diameter_max_edit = QLineEdit()
        self.material_edit = QLineEdit()
        self.coating_edit = QLineEdit()

        filters_layout.addWidget(QLabel("Search"), 0, 0)
        filters_layout.addWidget(self.search_edit, 0, 1, 1, 3)
        filters_layout.addWidget(QLabel("Manufacturer"), 1, 0)
        filters_layout.addWidget(self.manufacturer_combo, 1, 1)
        filters_layout.addWidget(QLabel("Category"), 1, 2)
        filters_layout.addWidget(self.category_edit, 1, 3)
        filters_layout.addWidget(QLabel("EFL Min"), 2, 0)
        filters_layout.addWidget(self.efl_min_edit, 2, 1)
        filters_layout.addWidget(QLabel("EFL Max"), 2, 2)
        filters_layout.addWidget(self.efl_max_edit, 2, 3)
        filters_layout.addWidget(QLabel("Diameter Min"), 3, 0)
        filters_layout.addWidget(self.diameter_min_edit, 3, 1)
        filters_layout.addWidget(QLabel("Diameter Max"), 3, 2)
        filters_layout.addWidget(self.diameter_max_edit, 3, 3)
        filters_layout.addWidget(QLabel("Material"), 4, 0)
        filters_layout.addWidget(self.material_edit, 4, 1)
        filters_layout.addWidget(QLabel("Coating"), 4, 2)
        filters_layout.addWidget(self.coating_edit, 4, 3)
        layout.addWidget(filters_box)

        self.results_table = QTableWidget(0, len(self.RESULT_COLUMNS))
        self.results_table.setHorizontalHeaderLabels(self.RESULT_COLUMNS)
        self.results_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.results_table.setSelectionMode(QTableWidget.SingleSelection)
        self.results_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.results_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.results_table, 1)

        self.status_label = QLabel("No catalog entries loaded.")
        layout.addWidget(self.status_label)

        details_box = QGroupBox("Selection Details")
        details_layout = QVBoxLayout(details_box)
        self.details_text = QTextEdit()
        self.details_text.setReadOnly(True)
        self.details_text.setMinimumHeight(180)
        details_layout.addWidget(self.details_text)

        insert_row = QHBoxLayout()
        self.insert_before_button = QPushButton("Insert Before Selected Surface")
        self.insert_after_button = QPushButton("Insert After Selected Surface")
        insert_row.addWidget(self.insert_before_button)
        insert_row.addWidget(self.insert_after_button)
        details_layout.addLayout(insert_row)
        layout.addWidget(details_box)

    def _wire_signals(self) -> None:
        self.import_edmund_button.clicked.connect(
            lambda: self._import_catalog("Edmund")
        )
        self.import_thorlabs_button.clicked.connect(
            lambda: self._import_catalog("Thorlabs")
        )
        for widget in (
            self.search_edit,
            self.category_edit,
            self.efl_min_edit,
            self.efl_max_edit,
            self.diameter_min_edit,
            self.diameter_max_edit,
            self.material_edit,
            self.coating_edit,
        ):
            widget.textChanged.connect(self.refresh)
        self.manufacturer_combo.currentIndexChanged.connect(self.refresh)
        self.results_table.itemSelectionChanged.connect(self._update_details)
        self.insert_before_button.clicked.connect(lambda: self._insert_selected("before"))
        self.insert_after_button.clicked.connect(lambda: self._insert_selected("after"))
        self.connector.catalogChanged.connect(self.refresh)

    @Slot()
    def refresh(self) -> None:
        self._refresh_manufacturers()
        query = {
            "text": self.search_edit.text(),
            "manufacturer": self.manufacturer_combo.currentData() or "",
            "category": self.category_edit.text(),
            "efl_min": self.efl_min_edit.text(),
            "efl_max": self.efl_max_edit.text(),
            "diameter_min": self.diameter_min_edit.text(),
            "diameter_max": self.diameter_max_edit.text(),
            "material_text": self.material_edit.text(),
            "coating_text": self.coating_edit.text(),
        }
        self._current_results = self.connector.search_catalog_lenses(query)
        self.results_table.setRowCount(len(self._current_results))
        for row, record in enumerate(self._current_results):
            values = [
                record.get("manufacturer", ""),
                record.get("part_number", ""),
                record.get("product_name", ""),
                record.get("category", ""),
                _fmt_float(record.get("efl_mm")),
                _fmt_float(record.get("diameter_mm")),
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, record.get("catalog_id"))
                self.results_table.setItem(row, col, item)

        count = len(self._current_results)
        self.status_label.setText(
            "No catalog entries loaded." if count == 0 else f"{count} catalog entries found."
        )
        if count == 0:
            self.details_text.clear()
        else:
            self.results_table.selectRow(0)
            self._update_details()

    def _refresh_manufacturers(self) -> None:
        current_value = self.manufacturer_combo.currentData()
        manufacturers = self.connector.get_catalog_manufacturers()
        self.manufacturer_combo.blockSignals(True)
        self.manufacturer_combo.clear()
        self.manufacturer_combo.addItem("All Manufacturers", "")
        for manufacturer in manufacturers:
            self.manufacturer_combo.addItem(manufacturer, manufacturer)
        current_index = max(self.manufacturer_combo.findData(current_value), 0)
        self.manufacturer_combo.setCurrentIndex(current_index)
        self.manufacturer_combo.blockSignals(False)

    def _update_details(self) -> None:
        catalog_id = self._selected_catalog_id()
        if not catalog_id:
            self.details_text.clear()
            return
        details = self.connector.get_catalog_lens_details(catalog_id)
        if not details:
            self.details_text.clear()
            return
        source = details.get("source", {}) if isinstance(details.get("source"), dict) else {}
        lines = [
            f"<b>{details.get('manufacturer', '')} {details.get('part_number', '')}</b>",
            details.get("product_name", ""),
            "",
            f"Category: {details.get('category', '')}",
            f"EFL: {_fmt_float(details.get('efl_mm'))} mm",
            f"Diameter: {_fmt_float(details.get('diameter_mm'))} mm",
            f"Material: {details.get('material_summary') or '-'}",
            f"Coating: {details.get('coating') or '-'}",
            f"Surfaces: {len(details.get('surfaces', []))}",
            "",
            f"Source: {source.get('source_type', '-')}",
            f"Imported: {source.get('imported_at', '-')}",
            f"URL: {details.get('url') or '-'}",
        ]
        self.details_text.setHtml("<br>".join(lines))

    def _import_catalog(self, manufacturer: str) -> None:
        filepaths, _ = QFileDialog.getOpenFileNames(
            self,
            f"Import {manufacturer} Catalog",
            "",
            "Catalog Files (*.zmx *.json);;Zemax Files (*.zmx);;Normalized Catalog JSON (*.json);;All Files (*)",
        )
        if not filepaths:
            return
        try:
            count = self.connector.import_catalog_file(manufacturer, filepaths)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(
                self,
                "Catalog Import Failed",
                str(exc),
            )
            return
        self._notify(f"Imported {count} {manufacturer} catalog entries.", "success")

    def _insert_selected(self, mode: str) -> None:
        catalog_id = self._selected_catalog_id()
        if not catalog_id:
            self._notify("Select a catalog entry first.", "warning")
            return
        main_window = self.window()
        if not hasattr(main_window, "panel_manager"):
            self._notify("Main window context not available.", "warning")
            return
        lens_editor = main_window.panel_manager.lens_editor
        ui_row = lens_editor.tableWidget.currentRow()
        if ui_row < 0:
            self._notify("Select a target surface in the Lens Data Editor first.", "info")
            return
        surface_index = lens_editor.map_ui_row_to_surface_index(ui_row)
        try:
            self.connector.insert_catalog_lens(catalog_id, surface_index, mode)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Catalog Insertion Failed", str(exc))
            return
        self._notify("Catalog lens inserted into the system.", "success")

    def _selected_catalog_id(self) -> str:
        selected = self.results_table.selectedItems()
        if not selected:
            return ""
        return str(selected[0].data(Qt.UserRole) or "")

    def _notify(self, message: str, level: str) -> None:
        main_window = self.window()
        toast_manager = getattr(main_window, "toast_manager", None)
        if toast_manager is not None:
            toast_manager.notify(message, level)


def _fmt_float(value) -> str:  # noqa: ANN001
    if value in (None, ""):
        return "-"
    try:
        return f"{float(value):.3f}"
    except (TypeError, ValueError):
        return str(value)
