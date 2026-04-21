"""Dockable stock-lens catalog browser panel."""

from __future__ import annotations

import re
from typing import Callable
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QSettings, Qt, QThread, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHeaderView,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QComboBox,
    QMenu,
    QToolButton,
)

if TYPE_CHECKING:
    from .main_window import MainWindow
    from .optiland_connector import OptilandConnector

from .config import APPLICATION_NAME, ORGANIZATION_NAME
from .services.catalog_service import EDMUND_ZEMAX_PAGE_URL, THORLABS_ZEMAX_PAGE_URL


class _CatalogTaskWorker(QObject):
    """Run a blocking catalog task off the GUI thread."""

    finished = Signal(object, object)

    def __init__(self, task: Callable[[], object]) -> None:
        super().__init__()
        self._task = task

    @Slot()
    def run(self) -> None:
        try:
            result = self._task()
        except Exception as exc:  # noqa: BLE001
            self.finished.emit(None, exc)
            return
        self.finished.emit(result, None)


class CatalogBrowserPanel(QWidget):
    """Search, inspect, import, and insert stock-lens catalog records."""

    _task_finished = Signal(object, object)

    RESULT_COLUMNS = [
        "Manufacturer",
        "Part No.",
        "Name",
        "Category",
        "EFL",
        "Diameter",
        "Material",
        "Coating",
    ]
    TABLE_SETTINGS_PREFIX = "CatalogBrowser/Table"

    def __init__(self, connector: OptilandConnector, parent=None) -> None:
        super().__init__(parent)
        self.connector = connector
        self.settings = QSettings(ORGANIZATION_NAME, APPLICATION_NAME)
        self._current_results: list[dict] = []
        self._restoring_table_state = False
        self._task_thread: QThread | None = None
        self._task_worker: _CatalogTaskWorker | None = None
        self._task_success_handler: Callable[[object], None] | None = None
        self._task_error_title = ""
        self._task_error_handler: Callable[[str], None] | None = None
        self._busy_frames = ["|", "/", "-", "\\"]
        self._busy_frame_index = 0
        self._filter_widgets_ready = False
        self._busy_timer = QTimer(self)
        self._busy_timer.setInterval(120)
        self._busy_timer.timeout.connect(self._advance_busy_indicator)
        self._build_ui()
        self._wire_signals()
        self._restore_table_state()
        self.refresh()

    def _build_ui(self) -> None:
        self.setObjectName("CatalogBrowserPanel")
        layout = QVBoxLayout(self)

        controls_box = QGroupBox("Catalog Tools")
        controls_layout = QHBoxLayout(controls_box)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search by part number, name, material...")
        controls_layout.addWidget(QLabel("Search"))
        controls_layout.addWidget(self.search_edit, 1)

        self.reset_filters_button = QPushButton("↻")
        self.reset_filters_button.setToolTip("Reset all search filters")
        self.reset_filters_button.setObjectName("CatalogResetFiltersButton")
        self.reset_filters_button.setFixedWidth(42)
        controls_layout.addWidget(self.reset_filters_button)

        self.download_catalog_button = QToolButton()
        self.download_catalog_button.setText("Download online catalog...")
        self.download_catalog_button.setPopupMode(
            QToolButton.ToolButtonPopupMode.InstantPopup
        )
        self.download_catalog_button.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextOnly
        )
        self.import_busy_indicator = QLabel("")
        self.import_busy_indicator.setVisible(False)
        self.import_busy_indicator.setFixedWidth(16)
        self.import_busy_indicator.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._build_catalog_menus()
        controls_layout.addWidget(self.download_catalog_button)
        controls_layout.addWidget(self.import_busy_indicator)
        layout.addWidget(controls_box)

        self.results_table = QTableWidget(0, len(self.RESULT_COLUMNS))
        self.results_table.setHorizontalHeaderLabels(self.RESULT_COLUMNS)
        self.results_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.results_table.setSelectionMode(QTableWidget.SingleSelection)
        self.results_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.results_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.results_table.verticalHeader().setVisible(False)
        header = self.results_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(False)
        header.setSectionsMovable(True)
        header.setSortIndicatorShown(True)
        self.results_table.setSortingEnabled(False)
        self.copy_cell_shortcut = QShortcut(QKeySequence("Ctrl+C"), self.results_table)
        self.copy_insert_shortcut = QShortcut(QKeySequence("Ctrl+Insert"), self.results_table)
        layout.addWidget(self.results_table, 1)

        self.status_label = QLabel("No catalog entries loaded.")
        layout.addWidget(self.status_label)

        details_box = QGroupBox("Selection Details")
        details_layout = QVBoxLayout(details_box)
        self.details_text = QLabel()
        self.details_text.setWordWrap(True)
        self.details_text.setTextFormat(Qt.TextFormat.RichText)
        self.details_text.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.details_text.setMinimumHeight(64)
        self.details_text.setMaximumHeight(96)
        details_layout.addWidget(self.details_text)

        insert_row = QHBoxLayout()
        self.insert_before_button = QPushButton("Insert Before Selected Surface")
        self.insert_after_button = QPushButton("Insert After Selected Surface")
        insert_row.addWidget(self.insert_before_button)
        insert_row.addWidget(self.insert_after_button)
        details_layout.addLayout(insert_row)
        layout.addWidget(details_box)

    def _wire_signals(self) -> None:
        self.search_edit.textChanged.connect(self.refresh)
        self.reset_filters_button.clicked.connect(self._reset_filters)
        self.results_table.itemSelectionChanged.connect(self._update_details)
        self.results_table.customContextMenuRequested.connect(self._show_results_context_menu)
        header = self.results_table.horizontalHeader()
        header.sectionClicked.connect(self._toggle_sort_column)
        header.sectionMoved.connect(self._save_table_state)
        header.sectionResized.connect(self._sync_filter_row_geometry)
        header.sortIndicatorChanged.connect(self._save_table_state)
        header.sortIndicatorChanged.connect(lambda *_args: self.refresh())
        self.copy_cell_shortcut.activated.connect(self._copy_current_cell_to_clipboard)
        self.copy_insert_shortcut.activated.connect(self._copy_current_cell_to_clipboard)
        self.insert_before_button.clicked.connect(lambda: self._insert_selected("before"))
        self.insert_after_button.clicked.connect(lambda: self._insert_selected("after"))
        self.connector.catalogChanged.connect(self.refresh)
        self._task_finished.connect(self._handle_task_finished, Qt.ConnectionType.QueuedConnection)

    def _build_catalog_menus(self) -> None:
        """Build the online-download dropdown menu."""
        download_menu = QMenu(self.download_catalog_button)
        download_menu.addAction(
            "Edmund Optics...",
            self._download_edmund_catalog,
        )
        download_menu.addAction(
            "Thorlabs...",
            self._download_thorlabs_catalog,
        )
        self.download_catalog_button.setMenu(download_menu)

    @Slot()
    def refresh(self) -> None:
        self._ensure_filter_row()
        query = {
            "text": self.search_edit.text(),
            "manufacturer": self.manufacturer_filter.currentData() or "",
            "part_number": self.part_number_filter.text(),
            "product_name": self.name_filter.text(),
            "category": self.category_filter.text(),
            "efl_min": self._numeric_filter_bounds(self.efl_filter.text())[0],
            "efl_max": self._numeric_filter_bounds(self.efl_filter.text())[1],
            "diameter_min": self._numeric_filter_bounds(self.diameter_filter.text())[0],
            "diameter_max": self._numeric_filter_bounds(self.diameter_filter.text())[1],
            "material_text": self.material_filter.text(),
            "coating_text": self.coating_filter.text(),
        }
        self._current_results = self.connector.search_catalog_lenses(query)
        self._sort_current_results()
        self._refresh_manufacturer_filter()
        self.results_table.setRowCount(len(self._current_results) + 1)
        for row, record in enumerate(self._current_results):
            values = [
                record.get("manufacturer", ""),
                record.get("part_number", ""),
                record.get("product_name", ""),
                record.get("category", ""),
                _fmt_float(record.get("efl_mm")),
                _fmt_float(record.get("diameter_mm")),
                record.get("material_summary", "") or "",
                record.get("coating", "") or "",
            ]
            table_row = row + 1
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, record.get("catalog_id"))
                if col in (4, 5):
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    )
                self.results_table.setItem(table_row, col, item)
        self.results_table.setRowHeight(0, 30)
        self._sync_filter_row_geometry()

        count = len(self._current_results)
        self.status_label.setText(
            "No catalog entries loaded." if count == 0 else f"{count} catalog entries found."
        )
        if count == 0:
            self.details_text.clear()
        else:
            self.results_table.selectRow(1)
            self._update_details()

    def _ensure_filter_row(self) -> None:
        """Create the embedded filter row once and attach it to the first table row."""
        if self._filter_widgets_ready:
            return
        if self.results_table.rowCount() == 0:
            self.results_table.setRowCount(1)
        self.manufacturer_filter = QComboBox(self.results_table)
        self.manufacturer_filter.addItem("All", "")
        self.part_number_filter = QLineEdit(self.results_table)
        self.name_filter = QLineEdit(self.results_table)
        self.category_filter = QLineEdit(self.results_table)
        self.efl_filter = QLineEdit(self.results_table)
        self.diameter_filter = QLineEdit(self.results_table)
        self.material_filter = QLineEdit(self.results_table)
        self.coating_filter = QLineEdit(self.results_table)

        self.part_number_filter.setPlaceholderText("filter")
        self.name_filter.setPlaceholderText("filter")
        self.category_filter.setPlaceholderText("filter")
        self.efl_filter.setPlaceholderText("10-20")
        self.diameter_filter.setPlaceholderText("5-25")
        self.material_filter.setPlaceholderText("filter")
        self.coating_filter.setPlaceholderText("filter")

        for widget in (
            self.part_number_filter,
            self.name_filter,
            self.category_filter,
            self.efl_filter,
            self.diameter_filter,
            self.material_filter,
            self.coating_filter,
        ):
            widget.textChanged.connect(self.refresh)
        self.manufacturer_filter.currentIndexChanged.connect(self.refresh)

        self.results_table.setCellWidget(0, 0, self.manufacturer_filter)
        self.results_table.setCellWidget(0, 1, self.part_number_filter)
        self.results_table.setCellWidget(0, 2, self.name_filter)
        self.results_table.setCellWidget(0, 3, self.category_filter)
        self.results_table.setCellWidget(0, 4, self.efl_filter)
        self.results_table.setCellWidget(0, 5, self.diameter_filter)
        self.results_table.setCellWidget(0, 6, self.material_filter)
        self.results_table.setCellWidget(0, 7, self.coating_filter)
        self._filter_widgets_ready = True

    def _refresh_manufacturer_filter(self) -> None:
        """Refresh the manufacturer combo used inside the table filter row."""
        if not self._filter_widgets_ready:
            return
        current_value = self.manufacturer_filter.currentData()
        manufacturers = self.connector.get_catalog_manufacturers()
        self.manufacturer_filter.blockSignals(True)
        self.manufacturer_filter.clear()
        self.manufacturer_filter.addItem("All", "")
        for manufacturer in manufacturers:
            self.manufacturer_filter.addItem(manufacturer, manufacturer)
        current_index = max(self.manufacturer_filter.findData(current_value), 0)
        self.manufacturer_filter.setCurrentIndex(current_index)
        self.manufacturer_filter.blockSignals(False)

    def _sort_current_results(self) -> None:
        """Sort current search results using the persisted header sort state."""
        header = self.results_table.horizontalHeader()
        column = header.sortIndicatorSection()
        reverse = header.sortIndicatorOrder() == Qt.SortOrder.DescendingOrder
        key_funcs = {
            0: lambda record: str(record.get("manufacturer", "")).casefold(),
            1: lambda record: str(record.get("part_number", "")).casefold(),
            2: lambda record: str(record.get("product_name", "")).casefold(),
            3: lambda record: str(record.get("category", "")).casefold(),
            4: lambda record: _sortable_number(record.get("efl_mm")),
            5: lambda record: _sortable_number(record.get("diameter_mm")),
            6: lambda record: str(record.get("material_summary", "") or "").casefold(),
            7: lambda record: str(record.get("coating", "") or "").casefold(),
        }
        key_func = key_funcs.get(column, key_funcs[0])
        self._current_results.sort(key=key_func, reverse=reverse)

    def _toggle_sort_column(self, column: int) -> None:
        """Toggle the active sort column/order when the user clicks a header."""
        header = self.results_table.horizontalHeader()
        current_column = header.sortIndicatorSection()
        current_order = header.sortIndicatorOrder()
        next_order = (
            Qt.SortOrder.DescendingOrder
            if current_column == column and current_order == Qt.SortOrder.AscendingOrder
            else Qt.SortOrder.AscendingOrder
        )
        header.setSortIndicator(column, next_order)

    def _numeric_filter_bounds(self, text: str) -> tuple[float | None, float | None]:
        """Parse a numeric filter string like `10-20`, `10`, or `10 to 20`."""
        cleaned = text.strip().replace(",", ".")
        if not cleaned:
            return None, None
        match = re.match(
            r"^\s*(-?\d+(?:\.\d+)?)\s*(?:-|to|:)\s*(-?\d+(?:\.\d+)?)\s*$",
            cleaned,
            re.IGNORECASE,
        )
        if match:
            first = float(match.group(1))
            second = float(match.group(2))
            return (min(first, second), max(first, second))
        try:
            value = float(cleaned)
        except ValueError:
            return None, None
        return value, value

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
        imported_at = str(source.get("imported_at", "-")).replace("T", " ")
        lines = [
            (
                f"<b>{details.get('manufacturer', '')} {details.get('part_number', '')}</b>"
                f" | {details.get('product_name', '')}"
            ),
            (
                f"Cat: {details.get('category', '-') or '-'} | "
                f"EFL: {_fmt_float(details.get('efl_mm'))} mm | "
                f"Dia: {_fmt_float(details.get('diameter_mm'))} mm | "
                f"Surf: {len(details.get('surfaces', []))}"
            ),
            (
                f"Mat: {details.get('material_summary') or '-'} | "
                f"Coating: {details.get('coating') or '-'} | "
                f"Source: {source.get('source_type', '-')}"
            ),
            f"<small>Imported: {imported_at}</small>",
        ]
        self.details_text.setTextFormat(Qt.TextFormat.RichText)
        self.details_text.setText("<br>".join(lines))

    def _reset_filters(self) -> None:
        """Reset all catalog search filters to their default state."""
        self.search_edit.clear()
        if self._filter_widgets_ready:
            self.part_number_filter.clear()
            self.name_filter.clear()
            self.category_filter.clear()
            self.efl_filter.clear()
            self.diameter_filter.clear()
            self.material_filter.clear()
            self.coating_filter.clear()
            self.manufacturer_filter.setCurrentIndex(0)
        self.refresh()

    def _settings_key(self, suffix: str) -> str:
        return f"{self.TABLE_SETTINGS_PREFIX}/{suffix}"

    def _restore_table_state(self) -> None:
        """Restore saved column widths and sort state."""
        self._restoring_table_state = True
        try:
            header = self.results_table.horizontalHeader()
            header_state = self.settings.value(self._settings_key("HeaderState"))
            if isinstance(header_state, bytes):
                header.restoreState(header_state)
            elif header_state is not None and hasattr(header_state, "data"):
                header.restoreState(header_state)
            else:
                default_widths = [130, 110, 260, 120, 90, 90, 140, 140]
                for column, default_width in enumerate(default_widths):
                    self.results_table.setColumnWidth(column, default_width)

            sort_column = self.settings.value(
                self._settings_key("SortColumn"),
                0,
                type=int,
            )
            sort_order = self.settings.value(
                self._settings_key("SortOrder"),
                Qt.SortOrder.AscendingOrder.value,
                type=int,
            )
            header.setSortIndicator(
                sort_column,
                Qt.SortOrder(sort_order),
            )
        finally:
            self._restoring_table_state = False

    def _apply_saved_sort(self) -> None:
        """Apply the persisted sort order to the current result table."""
        header = self.results_table.horizontalHeader()
        header.setSortIndicator(header.sortIndicatorSection(), header.sortIndicatorOrder())

    def _save_table_state(self, *args) -> None:  # noqa: ANN002
        """Persist current column widths and sort state."""
        if self._restoring_table_state:
            return
        header = self.results_table.horizontalHeader()
        self.settings.setValue(self._settings_key("HeaderState"), header.saveState())
        self.settings.setValue(
            self._settings_key("SortColumn"),
            header.sortIndicatorSection(),
        )
        self.settings.setValue(
            self._settings_key("SortOrder"),
            header.sortIndicatorOrder().value,
        )

    def _import_catalog_files(self, manufacturer: str) -> None:
        """Import one or more local catalog files for *manufacturer*."""
        filepaths, _ = QFileDialog.getOpenFileNames(
            self,
            f"Import {manufacturer} Catalog",
            "",
            "Catalog Files (*.zip *.zmx *.zmf *.json);;Catalog Archives (*.zip);;Zemax Files (*.zmx);;Zemax Catalog Files (*.zmf);;Normalized Catalog JSON (*.json);;All Files (*)",
        )
        if not filepaths:
            return
        self._import_catalog_paths(manufacturer, filepaths)

    def _import_catalog_folder(self, manufacturer: str) -> None:
        """Import catalog files recursively from a folder for *manufacturer*."""
        folder_path = QFileDialog.getExistingDirectory(
            self,
            f"Import {manufacturer} Catalog Folder",
            "",
        )
        if not folder_path:
            return
        self._import_catalog_paths(manufacturer, [folder_path])

    def _import_catalog_paths(self, manufacturer: str, paths: list[str]) -> None:
        """Import catalog files or folders for *manufacturer*."""
        self._run_catalog_task(
            lambda: self.connector.import_catalog_file(manufacturer, paths),
            success_handler=lambda count: self._notify(
                f"Imported {count} {manufacturer} catalog entries.",
                "success",
            ),
            error_title="Catalog Import Failed",
        )

    def _download_edmund_catalog(self) -> None:
        self._run_catalog_task(
            self.connector.download_edmund_catalog,
            success_handler=lambda result: self._notify(
                result.message,
                "success" if result.imported_count else "info",
            ),
            error_title="Edmund Catalog Download Failed",
            error_handler=self._show_edmund_download_help,
        )

    def _download_thorlabs_catalog(self) -> None:
        self._run_catalog_task(
            self.connector.download_thorlabs_catalog,
            success_handler=lambda result: self._notify(
                result.message,
                "success" if result.imported_count else "info",
            ),
            error_title="Thorlabs Catalog Download Failed",
            error_handler=self._show_thorlabs_download_help,
        )

    def _show_edmund_download_help(self, error_text: str) -> None:
        """Show a guided fallback dialog when Edmund blocks auto-download."""
        dialog = QMessageBox(self)
        dialog.setIcon(QMessageBox.Icon.Warning)
        dialog.setWindowTitle("Edmund Catalog Download Failed")
        dialog.setText("Automatic download was blocked by Edmund.")
        dialog.setInformativeText(
            "Open the official Edmund Zemax Catalog page in your browser, download the "
            "archive manually, and then import the downloaded ZIP, ZMX, or ZMF file."
        )
        dialog.setDetailedText(error_text)
        open_button = dialog.addButton(
            "Open Download Page",
            QMessageBox.ButtonRole.ActionRole,
        )
        import_button = dialog.addButton(
            "Import Downloaded File...",
            QMessageBox.ButtonRole.ActionRole,
        )
        dialog.addButton(QMessageBox.StandardButton.Close)
        dialog.exec()

        clicked = dialog.clickedButton()
        if clicked == open_button:
            QDesktopServices.openUrl(QUrl(EDMUND_ZEMAX_PAGE_URL))
        elif clicked == import_button:
            self._import_catalog_files("Edmund")

    def _show_thorlabs_download_help(self, error_text: str) -> None:
        """Show a guided fallback dialog when Thorlabs auto-download fails."""
        dialog = QMessageBox(self)
        dialog.setIcon(QMessageBox.Icon.Warning)
        dialog.setWindowTitle("Thorlabs Catalog Download Failed")
        dialog.setText("Automatic download was not available from Thorlabs.")
        dialog.setInformativeText(
            "Open the official Thorlabs Zemax page in your browser, download the "
            "catalog package manually, and then import the downloaded ZIP, ZMX, or ZMF file."
        )
        dialog.setDetailedText(error_text)
        open_button = dialog.addButton(
            "Open Download Page",
            QMessageBox.ButtonRole.ActionRole,
        )
        import_button = dialog.addButton(
            "Import Downloaded File...",
            QMessageBox.ButtonRole.ActionRole,
        )
        dialog.addButton(QMessageBox.StandardButton.Close)
        dialog.exec()

        clicked = dialog.clickedButton()
        if clicked == open_button:
            QDesktopServices.openUrl(QUrl(THORLABS_ZEMAX_PAGE_URL))
        elif clicked == import_button:
            self._import_catalog_files("Thorlabs")

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
        if selected[0].row() == 0:
            return ""
        return str(selected[0].data(Qt.UserRole) or "")

    def _selected_catalog_details(self) -> dict | None:
        """Return the full details dict for the currently selected catalog entry."""
        catalog_id = self._selected_catalog_id()
        if not catalog_id:
            return None
        return self.connector.get_catalog_lens_details(catalog_id)

    def _copy_current_cell_to_clipboard(self) -> None:
        """Copy the currently focused result cell to the clipboard."""
        item = self.results_table.currentItem()
        if item is None or item.row() <= 0:
            return
        QApplication.clipboard().setText(item.text())
        self._notify("Copied cell value.", "info")

    def _copy_selected_row_to_clipboard(self) -> None:
        """Copy the selected result row as a tab-separated line."""
        row = self.results_table.currentRow()
        if row <= 0:
            return
        values = []
        header = self.results_table.horizontalHeader()
        for visual_column in range(self.results_table.columnCount()):
            column = header.logicalIndex(visual_column)
            item = self.results_table.item(row, column)
            values.append("" if item is None else item.text())
        QApplication.clipboard().setText("\t".join(values))
        self._notify("Copied row.", "info")

    def _open_selected_catalog_url(self) -> None:
        """Open the selected catalog entry on the vendor website when available."""
        catalog_id = self._selected_catalog_id()
        if not catalog_id:
            return
        url = self.connector.resolve_catalog_product_url(catalog_id)
        if not url:
            self._notify("No product URL available for this catalog entry.", "warning")
            return
        QDesktopServices.openUrl(QUrl(str(url)))

    def _show_results_context_menu(self, pos) -> None:  # noqa: ANN001
        """Show a context menu with copy and product-link actions for the result table."""
        item = self.results_table.itemAt(pos)
        if item is not None:
            self.results_table.setCurrentItem(item)
            self.results_table.selectRow(item.row())

        menu = QMenu(self.results_table)
        copy_cell_action = menu.addAction("Copy Cell")
        copy_row_action = menu.addAction("Copy Row")
        menu.addSeparator()
        open_url_action = menu.addAction("Open Product Webpage")

        current_item = self.results_table.currentItem()
        has_item = current_item is not None and current_item.row() > 0
        copy_cell_action.setEnabled(has_item)
        copy_row_action.setEnabled(has_item)
        open_url_action.setEnabled(has_item)

        chosen = menu.exec(self.results_table.viewport().mapToGlobal(pos))
        if chosen == copy_cell_action:
            self._copy_current_cell_to_clipboard()
        elif chosen == copy_row_action:
            self._copy_selected_row_to_clipboard()
        elif chosen == open_url_action:
            self._open_selected_catalog_url()

    def _sync_filter_row_geometry(self, *args) -> None:  # noqa: ANN002
        """Keep the embedded filter row sized sensibly after header changes."""
        if not self._filter_widgets_ready:
            return
        self.results_table.setRowHeight(0, 30)

    def _notify(self, message: str, level: str) -> None:
        toast_manager = None
        widget = self
        while widget is not None:
            toast_manager = getattr(widget, "toast_manager", None)
            if toast_manager is not None:
                break
            widget = widget.parentWidget()
        if toast_manager is None:
            main_window = self.window()
            toast_manager = getattr(main_window, "toast_manager", None)
        if toast_manager is not None:
            toast_manager.notify(message, level)

    def _run_catalog_task(
        self,
        task: Callable[[], object],
        *,
        success_handler: Callable[[object], None],
        error_title: str,
        error_handler: Callable[[str], None] | None = None,
    ) -> None:
        """Run a catalog task in a worker thread and update the busy indicator."""
        if self._task_thread is not None:
            self._notify("A catalog task is already running.", "info")
            return

        self._set_task_busy(True)
        self._task_success_handler = success_handler
        self._task_error_title = error_title
        self._task_error_handler = error_handler
        self._task_thread = QThread()
        self._task_worker = _CatalogTaskWorker(task)
        self._task_worker.moveToThread(self._task_thread)
        self._task_thread.started.connect(self._task_worker.run)
        self._task_worker.finished.connect(self._task_finished.emit)
        self._task_worker.finished.connect(self._task_thread.quit)
        self._task_thread.finished.connect(self._task_thread.deleteLater)
        self._task_thread.finished.connect(self._task_worker.deleteLater)
        self._task_thread.start()

    @Slot(object, object)
    def _handle_task_finished(self, result: object, error: object) -> None:
        """Finalize a worker-thread catalog task."""
        self._set_task_busy(False)
        thread = self._task_thread
        success_handler = self._task_success_handler
        error_title = self._task_error_title
        error_handler = self._task_error_handler

        self._task_worker = None
        self._task_thread = None
        self._task_success_handler = None
        self._task_error_title = ""
        self._task_error_handler = None

        if thread is not None and thread.isRunning():
            thread.quit()
            thread.wait(5000)

        if error is not None:
            error_text = str(error)
            if error_handler is not None:
                error_handler(error_text)
            else:
                QMessageBox.warning(self, error_title, error_text)
            return

        if success_handler is not None:
            success_handler(result)

    def _set_task_busy(self, busy: bool) -> None:
        """Toggle the animated busy indicator beside the import button."""
        self.download_catalog_button.setEnabled(not busy)
        self.reset_filters_button.setEnabled(not busy)
        if busy:
            self._busy_frame_index = 0
            self.import_busy_indicator.setText(self._busy_frames[self._busy_frame_index])
            self.import_busy_indicator.setVisible(True)
            self._busy_timer.start()
            return
        self._busy_timer.stop()
        self.import_busy_indicator.clear()
        self.import_busy_indicator.setVisible(False)

    def _advance_busy_indicator(self) -> None:
        """Advance the spinner frame shown beside the import button."""
        self._busy_frame_index = (self._busy_frame_index + 1) % len(self._busy_frames)
        self.import_busy_indicator.setText(self._busy_frames[self._busy_frame_index])

    def closeEvent(self, event) -> None:  # noqa: ANN001, N802
        """Shut down any running catalog task cleanly before the panel closes."""
        self._set_task_busy(False)
        thread = self._task_thread
        if thread is not None and thread.isRunning() and thread != QThread.currentThread():
            thread.quit()
            thread.wait(5000)
        super().closeEvent(event)


def _fmt_float(value) -> str:  # noqa: ANN001
    if value in (None, ""):
        return "-"
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return str(value)


def _sortable_number(value) -> tuple[int, float]:  # noqa: ANN001
    """Return a stable sort key for optional numeric values."""
    if value in (None, ""):
        return (1, 0.0)
    try:
        return (0, float(value))
    except (TypeError, ValueError):
        return (1, 0.0)
