"""Dockable stock-lens catalog browser panel."""

from __future__ import annotations

import re
from typing import Callable
from typing import TYPE_CHECKING

from PySide6.QtCore import (
    QEvent,
    QObject,
    QSettings,
    QSize,
    Qt,
    QThread,
    QTimer,
    QUrl,
    Signal,
    Slot,
)
from PySide6.QtGui import QDesktopServices, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QHeaderView,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStyle,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
    QComboBox,
    QMenu,
)

if TYPE_CHECKING:
    from .main_window import MainWindow
    from .optiland_connector import OptilandConnector

from .config import APPLICATION_NAME, ORGANIZATION_NAME
from .services.catalog_service import EDMUND_ZEMAX_PAGE_URL, THORLABS_ZEMAX_PAGE_URL
from .theme_manager import get_icon_theme_id
from .utils.table_copy import TableCopySupport


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


class _PinnedFilterRow(QWidget):
    """A fixed-height row that should not impose a large minimum width."""

    def __init__(self, height: int, parent=None) -> None:
        super().__init__(parent)
        self._row_height = height

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(0, self._row_height)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(0, self._row_height)


class CatalogBrowserPanel(QWidget):
    """Search, inspect, import, and insert stock-lens catalog records."""

    _task_finished = Signal(object, object)

    RESULT_COLUMNS = [
        "Mark",
        "Manufacturer",
        "Part No.",
        "Name",
        "Category",
        "EFL",
        "Diameter",
        "Material",
        "Coating",
        "Status",
        "Match",
    ]
    HEADER_LABELS = [
        "☑",
        "Manufacturer",
        "Part No.",
        "Name",
        "Category",
        "EFL",
        "Diameter",
        "Material",
        "Coating",
        "Status",
        "Match",
    ]
    _SORT_ASC_ARROW = "↑"
    _SORT_DESC_ARROW = "↓"
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
        self._marked_catalog_ids: set[str] = set()
        self._updating_mark_column = False
        self._updating_review_tree_checks = False
        self._busy_frames = ["|", "/", "-", "\\"]
        self._busy_frame_index = 0
        self._filter_widgets_ready = False
        self._filter_row_height = 30
        self._busy_timer = QTimer(self)
        self._busy_timer.setInterval(120)
        self._busy_timer.timeout.connect(self._advance_busy_indicator)
        self._result_batch_size = 250
        self._result_population_timer = QTimer(self)
        self._result_population_timer.setSingleShot(True)
        self._result_population_timer.timeout.connect(self._continue_results_population)
        self._result_population_index = 0
        self._build_ui()
        self._wire_signals()
        self._restore_table_state()
        self.refresh()

    def _build_ui(self) -> None:
        self.setObjectName("CatalogBrowserPanel")
        layout = QVBoxLayout(self)

        controls_box = QGroupBox("Catalog Tools")
        controls_box_layout = QVBoxLayout(controls_box)
        controls_box_layout.setSpacing(6)

        insert_controls_layout = QHBoxLayout()
        self.insert_before_button = QPushButton("Insert Before Selected Surface")
        self.insert_after_button = QPushButton("Insert After Selected Surface")
        insert_controls_layout.addWidget(self.insert_before_button)
        insert_controls_layout.addWidget(self.insert_after_button)
        controls_box_layout.addLayout(insert_controls_layout)

        controls_layout = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search by part number, name, material...")
        controls_layout.addWidget(QLabel("Search"))
        controls_layout.addWidget(self.search_edit, 1)

        self.reset_filters_button = QPushButton("↻")
        self.reset_filters_button.setToolTip("Reset all search filters")
        self.reset_filters_button.setObjectName("CatalogResetFiltersButton")
        self.reset_filters_button.setFixedWidth(42)
        controls_layout.addWidget(self.reset_filters_button)

        self.insertable_only_button = QPushButton("Insertable")
        self.insertable_only_button.setCheckable(True)
        self.insertable_only_button.setChecked(True)
        self.insertable_only_button.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self._update_insertable_only_button_state()
        controls_layout.addWidget(self.insertable_only_button)

        self.mark_filtered_button = QPushButton("")
        self.clear_marks_button = QPushButton("")
        self.delete_marked_button = QPushButton("")
        self._configure_toolbar_action_button(
            self.mark_filtered_button, "mark_all.svg", "Mark Filtered"
        )
        self._configure_toolbar_action_button(
            self.clear_marks_button, "clear_marks.svg", "Clear Marks"
        )
        self._configure_toolbar_action_button(
            self.delete_marked_button, "delete_marks.svg", "Delete Marked"
        )
        controls_layout.addWidget(self.mark_filtered_button)
        controls_layout.addWidget(self.clear_marks_button)
        controls_layout.addWidget(self.delete_marked_button)

        self.download_catalog_button = QPushButton("Download online catalog...")
        self.download_catalog_button.setText("Download online catalog...")
        self.download_catalog_button.setObjectName("CatalogDownloadButton")
        self.download_catalog_button.setSizePolicy(
            QSizePolicy.Policy.Fixed,
            QSizePolicy.Policy.Fixed,
        )
        self.import_busy_indicator = QLabel("")
        self.import_busy_indicator.setVisible(False)
        self.import_busy_indicator.setFixedWidth(16)
        self.import_busy_indicator.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._build_catalog_menus()
        self.download_catalog_button.setMinimumWidth(
            self.download_catalog_button.sizeHint().width() + 8
        )
        controls_layout.addWidget(self.download_catalog_button)
        controls_layout.addWidget(self.import_busy_indicator)
        controls_box_layout.addLayout(controls_layout)
        layout.addWidget(controls_box)

        self.table_view_scroll = QScrollArea()
        self.table_view_scroll.setWidgetResizable(True)
        self.table_view_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.table_view_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.table_view_scroll.setFrameShape(QScrollArea.Shape.NoFrame)

        self.table_view_content = QWidget()
        self.table_view_content.setObjectName("CatalogTableViewContent")
        self.table_view_layout = QVBoxLayout(self.table_view_content)
        self.table_view_layout.setContentsMargins(0, 0, 0, 0)
        self.table_view_layout.setSpacing(0)

        self.filter_row_container = _PinnedFilterRow(self._filter_row_height)
        self.filter_row_container.setObjectName("CatalogFilterRowContainer")
        self.filter_row_container.setFixedHeight(self._filter_row_height)
        self.filter_row_container.setMinimumWidth(0)
        self.filter_row_container.setSizePolicy(
            QSizePolicy.Policy.MinimumExpanding,
            QSizePolicy.Policy.Fixed,
        )
        self.table_view_layout.addWidget(self.filter_row_container)

        self.results_table = QTableWidget(0, len(self.RESULT_COLUMNS))
        self.results_table.setHorizontalHeaderLabels(self.HEADER_LABELS)
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
        self.results_table.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._results_table_copy = TableCopySupport(
            self.results_table, enable_context_menu=False
        )
        self.copy_cell_shortcut = QShortcut(QKeySequence("Ctrl+C"), self.results_table)
        self.copy_insert_shortcut = QShortcut(QKeySequence("Ctrl+Insert"), self.results_table)
        self.copy_cell_shortcut.setContext(
            Qt.ShortcutContext.WidgetWithChildrenShortcut
        )
        self.copy_insert_shortcut.setContext(
            Qt.ShortcutContext.WidgetWithChildrenShortcut
        )
        self.table_view_layout.addWidget(self.results_table, 1)
        self.table_view_scroll.setWidget(self.table_view_content)
        layout.addWidget(self.table_view_scroll, 1)

        self.status_label = QLabel("No catalog entries loaded.")
        layout.addWidget(self.status_label)

        self.details_toggle_button = QToolButton()
        self.details_toggle_button.setObjectName("CatalogDetailsToggleButton")
        self.details_toggle_button.setText("Selection Details")
        self.details_toggle_button.setCheckable(True)
        self.details_toggle_button.setChecked(True)
        self.details_toggle_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.details_toggle_button.setArrowType(Qt.ArrowType.DownArrow)
        layout.addWidget(self.details_toggle_button)

        self.details_box = QFrame()
        self.details_box.setObjectName("CatalogSelectionDetailsBox")
        details_layout = QVBoxLayout(self.details_box)
        details_layout.setContentsMargins(0, 0, 0, 0)
        self.details_text = QLabel()
        self.details_text.setWordWrap(True)
        self.details_text.setTextFormat(Qt.TextFormat.RichText)
        self.details_text.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.details_text.setMinimumHeight(64)
        self.details_text.setMaximumHeight(96)
        details_layout.addWidget(self.details_text)
        layout.addWidget(self.details_box)

    def _configure_toolbar_action_button(
        self, button: QPushButton, icon_name: str, tooltip: str
    ) -> None:
        """Apply compact icon-only styling for catalog action buttons."""
        icon_theme = self._icon_theme()
        button.setIcon(QIcon(f":/icons/{icon_theme}/{icon_name}"))
        button.setIconSize(QSize(16, 16))
        button.setText("")
        button.setToolTip(tooltip)
        button.setAccessibleName(tooltip)
        button.setFixedWidth(32)

    def _update_insertable_only_button_state(self) -> None:
        """Refresh the insertable filter button to make its state obvious."""
        icon_theme = self._icon_theme()
        checked = self.insertable_only_button.isChecked()
        icon_name = "check_apply.svg" if checked else "dash.svg"
        tooltip = (
            "Showing only catalog entries with usable optical surface data"
            if checked
            else "Showing all catalog entries, including metadata-only rows"
        )
        icon = QIcon(f":/icons/{icon_theme}/{icon_name}")
        if icon.isNull():
            fallback = (
                QStyle.StandardPixmap.SP_DialogApplyButton
                if checked
                else QStyle.StandardPixmap.SP_TitleBarShadeButton
            )
            icon = self.style().standardIcon(fallback)
        self.insertable_only_button.setIcon(icon)
        self.insertable_only_button.setIconSize(QSize(14, 14))
        self.insertable_only_button.setToolTip(tooltip)
        self.insertable_only_button.setAccessibleName(
            f"Insertable filter {'on' if checked else 'off'}"
        )

    def _icon_theme(self, theme_name: str | None = None) -> str:
        """Resolve the light/dark icon family for the active theme."""
        if theme_name in {"dark", "light"}:
            return theme_name
        theme = self.settings.value("Appearance/ThemeId", "dark", type=str) or "dark"
        return get_icon_theme_id(theme)

    def update_theme(self, theme_name: str) -> None:
        """Refresh toolbar icons after an application theme change."""
        self._configure_toolbar_action_button(
            self.mark_filtered_button, "mark_all.svg", self.mark_filtered_button.toolTip()
        )
        self._configure_toolbar_action_button(
            self.clear_marks_button, "clear_marks.svg", self.clear_marks_button.toolTip()
        )
        self._configure_toolbar_action_button(
            self.delete_marked_button, "delete_marks.svg", self.delete_marked_button.toolTip()
        )
        icon_theme = self._icon_theme(theme_name)
        checked = self.insertable_only_button.isChecked()
        icon_name = "check_apply.svg" if checked else "dash.svg"
        icon = QIcon(f":/icons/{icon_theme}/{icon_name}")
        if icon.isNull():
            fallback = (
                QStyle.StandardPixmap.SP_DialogApplyButton
                if checked
                else QStyle.StandardPixmap.SP_TitleBarShadeButton
            )
            icon = self.style().standardIcon(fallback)
        self.insertable_only_button.setIcon(icon)
        self._update_insertable_only_button_state()

    def _set_details_expanded(self, expanded: bool) -> None:
        """Show or hide the selection details section."""
        self.details_box.setVisible(expanded)
        self.details_toggle_button.setArrowType(
            Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow
        )

    def _wire_signals(self) -> None:
        self.search_edit.textChanged.connect(self.refresh)
        self.reset_filters_button.clicked.connect(self._reset_filters)
        self.details_toggle_button.toggled.connect(self._set_details_expanded)
        self.insertable_only_button.toggled.connect(
            lambda _checked: self._update_insertable_only_button_state()
        )
        self.insertable_only_button.toggled.connect(self.refresh)
        self.results_table.itemSelectionChanged.connect(self._update_details)
        self.results_table.customContextMenuRequested.connect(self._show_results_context_menu)
        self.results_table.itemChanged.connect(self._handle_results_item_changed)
        header = self.results_table.horizontalHeader()
        header.sectionClicked.connect(self._toggle_sort_column)
        header.sectionMoved.connect(self._save_table_state)
        header.sectionResized.connect(self._sync_filter_row_geometry)
        header.sectionMoved.connect(self._sync_filter_row_geometry)
        header.sortIndicatorChanged.connect(self._save_table_state)
        header.sortIndicatorChanged.connect(self._update_sort_header_labels)
        header.sortIndicatorChanged.connect(lambda *_args: self.refresh())
        self.results_table.installEventFilter(self)
        self.copy_cell_shortcut.activated.connect(self._copy_current_cell_to_clipboard)
        self.copy_insert_shortcut.activated.connect(self._copy_current_cell_to_clipboard)
        self.insert_before_button.clicked.connect(lambda: self._insert_selected("before"))
        self.insert_after_button.clicked.connect(lambda: self._insert_selected("after"))
        self.mark_filtered_button.clicked.connect(self._mark_filtered_results)
        self.clear_marks_button.clicked.connect(self._clear_marked_results)
        self.delete_marked_button.clicked.connect(self._delete_marked_results)
        self.connector.catalogChanged.connect(self.refresh)
        self._task_finished.connect(self._handle_task_finished, Qt.ConnectionType.QueuedConnection)

    def _build_catalog_menus(self) -> None:
        """Build the online-download dropdown menu."""
        download_menu = QMenu(self.download_catalog_button)
        download_menu.addAction(
            "Excelitas / LINOS...",
            self._download_excelitas_catalog,
        )
        download_menu.addAction(
            "Edmund Optics...",
            self._download_edmund_catalog,
        )
        download_menu.addAction(
            "Thorlabs...",
            self._download_thorlabs_catalog,
        )
        download_menu.addSeparator()
        download_menu.addAction(
            "Import WinLens Library...",
            self._import_winlens_library,
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
            "availability_text": self.status_filter.text(),
            "match_type_text": self.match_filter.text(),
        }
        self._current_results = self.connector.search_catalog_lenses(query)
        if self.insertable_only_button.isChecked():
            self._current_results = [
                record
                for record in self._current_results
                if record.get("insertable_surface_count") is None
                or int(record.get("insertable_surface_count", 0) or 0) > 0
            ]
        self._sort_current_results()
        self._refresh_manufacturer_filter()
        self._begin_results_population()
        self._update_mark_button_label()

    def _begin_results_population(self) -> None:
        """Populate result rows in small batches so the UI stays responsive."""
        self._result_population_timer.stop()
        self._result_population_index = 0
        self.results_table.clearContents()
        self.results_table.clearSelection()
        self.results_table.setCurrentCell(-1, -1)
        self.results_table.setRowCount(len(self._current_results))
        self._sync_filter_row_geometry()

        count = len(self._current_results)
        if count == 0:
            self.status_label.setText("No catalog entries loaded.")
            self.details_text.clear()
            return

        self.status_label.setText(f"Loading catalog entries... 0/{count}")
        self._continue_results_population()

    @Slot()
    def _continue_results_population(self) -> None:
        """Append the next chunk of search results to the table widget."""
        count = len(self._current_results)
        if self._result_population_index >= count:
            self.status_label.setText(f"{count} catalog entries found.")
            if count > 0 and self.results_table.currentRow() < 0:
                self.results_table.selectRow(0)
                self._update_details()
            return

        end_index = min(self._result_population_index + self._result_batch_size, count)
        self.results_table.setUpdatesEnabled(False)
        try:
            self._updating_mark_column = True
            for row in range(self._result_population_index, end_index):
                record = self._current_results[row]
                catalog_id = str(record.get("catalog_id", ""))
                mark_item = QTableWidgetItem("")
                mark_item.setData(Qt.UserRole, catalog_id)
                mark_item.setFlags(
                    Qt.ItemFlag.ItemIsEnabled
                    | Qt.ItemFlag.ItemIsSelectable
                    | Qt.ItemFlag.ItemIsUserCheckable
                )
                mark_item.setCheckState(
                    Qt.CheckState.Checked
                    if catalog_id in self._marked_catalog_ids
                    else Qt.CheckState.Unchecked
                )
                self.results_table.setItem(row, 0, mark_item)
                values = [
                    record.get("manufacturer", ""),
                    record.get("part_number", ""),
                    record.get("product_name", ""),
                    record.get("category", ""),
                    _fmt_float(record.get("efl_mm")),
                    _fmt_float(record.get("diameter_mm")),
                    record.get("material_summary", "") or "",
                    record.get("coating", "") or "",
                    record.get("availability_status", "") or "",
                    record.get("match_type", "") or "",
                ]
                for col, value in enumerate(values):
                    item = QTableWidgetItem(value)
                    item.setData(Qt.UserRole, catalog_id)
                    if col in (4, 5):
                        item.setTextAlignment(
                            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                        )
                    self.results_table.setItem(row, col + 1, item)
        finally:
            self._updating_mark_column = False
            self.results_table.setUpdatesEnabled(True)

        self._result_population_index = end_index
        self._sync_filter_row_geometry()

        if self._result_population_index >= count:
            self.status_label.setText(f"{count} catalog entries found.")
            if self.results_table.currentRow() < 0:
                self.results_table.selectRow(0)
                self._update_details()
            return

        self.status_label.setText(
            f"Loading catalog entries... {self._result_population_index}/{count}"
        )
        self._result_population_timer.start(0)

    def _ensure_filter_row(self) -> None:
        """Create a pinned filter row that stays under the table header."""
        if self._filter_widgets_ready:
            return
        self.manufacturer_filter = QComboBox(self.filter_row_container)
        self.manufacturer_filter.addItem("All", "")
        self.part_number_filter = QLineEdit(self.filter_row_container)
        self.name_filter = QLineEdit(self.filter_row_container)
        self.category_filter = QLineEdit(self.filter_row_container)
        self.efl_filter = QLineEdit(self.filter_row_container)
        self.diameter_filter = QLineEdit(self.filter_row_container)
        self.material_filter = QLineEdit(self.filter_row_container)
        self.coating_filter = QLineEdit(self.filter_row_container)
        self.status_filter = QLineEdit(self.filter_row_container)
        self.match_filter = QLineEdit(self.filter_row_container)

        self.part_number_filter.setPlaceholderText("filter")
        self.name_filter.setPlaceholderText("filter")
        self.category_filter.setPlaceholderText("filter")
        self.efl_filter.setPlaceholderText("10-20")
        self.diameter_filter.setPlaceholderText("5-25")
        self.material_filter.setPlaceholderText("filter")
        self.coating_filter.setPlaceholderText("filter")
        self.status_filter.setPlaceholderText("legacy")
        self.match_filter.setPlaceholderText("confirmed")

        self.manufacturer_filter.setMinimumWidth(0)
        for widget in (
            self.part_number_filter,
            self.name_filter,
            self.category_filter,
            self.efl_filter,
            self.diameter_filter,
            self.material_filter,
            self.coating_filter,
            self.status_filter,
            self.match_filter,
        ):
            widget.setMinimumWidth(0)

        for widget in (
            self.part_number_filter,
            self.name_filter,
            self.category_filter,
            self.efl_filter,
            self.diameter_filter,
            self.material_filter,
            self.coating_filter,
            self.status_filter,
            self.match_filter,
        ):
            widget.textChanged.connect(self.refresh)
        self.manufacturer_filter.currentIndexChanged.connect(self.refresh)

        self._filter_widgets_ready = True
        self._sync_filter_row_geometry()

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
        default_priority = lambda record: (
            -int(record.get("insertable_surface_count", 0) or 0),
            -int(record.get("surface_count", 0) or 0),
            str(record.get("catalog_id", "")).casefold(),
        )
        key_funcs = {
            0: default_priority,
            1: lambda record: str(record.get("manufacturer", "")).casefold(),
            2: lambda record: str(record.get("part_number", "")).casefold(),
            3: lambda record: str(record.get("product_name", "")).casefold(),
            4: lambda record: str(record.get("category", "")).casefold(),
            5: lambda record: _sortable_number(record.get("efl_mm")),
            6: lambda record: _sortable_number(record.get("diameter_mm")),
            7: lambda record: str(record.get("material_summary", "") or "").casefold(),
            8: lambda record: str(record.get("coating", "") or "").casefold(),
            9: lambda record: str(record.get("availability_status", "") or "").casefold(),
            10: lambda record: str(record.get("match_type", "") or "").casefold(),
        }
        key_func = key_funcs.get(column, key_funcs[0])
        self._current_results.sort(key=key_func, reverse=reverse)

    @Slot(int, Qt.SortOrder)
    def _update_sort_header_labels(self, column: int, order: Qt.SortOrder) -> None:
        """Append a small arrow to the actively sorted column label."""
        for index, base_label in enumerate(self.RESULT_COLUMNS):
            label = self.HEADER_LABELS[index]
            if index == column:
                arrow = (
                    self._SORT_DESC_ARROW
                    if order == Qt.SortOrder.DescendingOrder
                    else self._SORT_ASC_ARROW
                )
                label = f"{label} {arrow}"
            item = self.results_table.horizontalHeaderItem(index)
            if item is None:
                self.results_table.setHorizontalHeaderItem(index, QTableWidgetItem(label))
            else:
                item.setText(label)

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
        self._update_mark_button_label()
        if not catalog_id:
            self.details_text.clear()
            return
        details = self.connector.get_catalog_lens_details(catalog_id)
        if not details:
            self.details_text.clear()
            return
        source = details.get("source", {}) if isinstance(details.get("source"), dict) else {}
        imported_at = str(source.get("imported_at", "-")).replace("T", " ")
        links = self.connector.get_catalog_record_links(catalog_id)
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
                f"Status: {details.get('availability_status') or '-'} | "
                f"Source: {source.get('source_type', '-')}"
            ),
            f"<small>Imported: {imported_at}</small>",
        ]
        if links:
            top_link = links[0]
            lines.append(
                "<small>"
                f"Top link: {top_link.get('manufacturer', '-')} {top_link.get('part_number', '-')}"
                f" [{top_link.get('match_type', 'candidate')}]"
                f" (score {top_link.get('score', 0)})"
                "</small>"
            )
        elif str(source.get("source_type", "")).casefold().startswith("winlens_"):
            lines.append("<small>Top link: no current catalog match suggestion.</small>")
        self.details_text.setTextFormat(Qt.TextFormat.RichText)
        self.details_text.setText("<br>".join(lines))

    def _update_mark_button_label(self) -> None:
        """Reflect whether the current table state has an active row selection."""
        has_selection = self.results_table.currentRow() >= 0
        label = "Mark Filtered" if has_selection else "Mark All"
        self.mark_filtered_button.setToolTip(label)
        self.mark_filtered_button.setAccessibleName(label)

    def _handle_results_item_changed(self, item: QTableWidgetItem) -> None:
        if self._updating_mark_column or item.column() != 0:
            return
        catalog_id = str(item.data(Qt.UserRole) or "")
        if not catalog_id:
            return
        if item.checkState() == Qt.CheckState.Checked:
            self._marked_catalog_ids.add(catalog_id)
        else:
            self._marked_catalog_ids.discard(catalog_id)

    def _mark_filtered_results(self) -> None:
        self._marked_catalog_ids.update(
            str(record.get("catalog_id", ""))
            for record in self._current_results
            if str(record.get("catalog_id", "")).strip()
        )
        self.refresh()

    def _clear_marked_results(self) -> None:
        self._marked_catalog_ids.clear()
        self.refresh()

    def _delete_marked_results(self) -> None:
        marked = sorted(self._marked_catalog_ids)
        if not marked:
            self._notify("No marked catalog entries to delete.", "info")
            return
        answer = QMessageBox.question(
            self,
            "Delete Marked Catalog Entries",
            f"Delete {len(marked)} marked catalog entries from the local cache?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        removed = self.connector.delete_catalog_records(marked)
        self._marked_catalog_ids.clear()
        self._notify(f"Deleted {removed} catalog entries.", "success" if removed else "info")

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
            self.status_filter.clear()
            self.match_filter.clear()
            self.manufacturer_filter.setCurrentIndex(0)
        self.insertable_only_button.setChecked(True)
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
                default_widths = [54, 130, 110, 260, 120, 90, 90, 140, 140, 100, 100]
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
            self._update_sort_header_labels(sort_column, Qt.SortOrder(sort_order))
        finally:
            self._restoring_table_state = False

    def _apply_saved_sort(self) -> None:
        """Apply the persisted sort order to the current result table."""
        header = self.results_table.horizontalHeader()
        header.setSortIndicator(header.sortIndicatorSection(), header.sortIndicatorOrder())
        self._update_sort_header_labels(
            header.sortIndicatorSection(),
            header.sortIndicatorOrder(),
        )

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

    def _import_winlens_library(self) -> None:
        """Import a local WinLens 2002 SPD library tree."""
        folder_path = QFileDialog.getExistingDirectory(
            self,
            "Import WinLens Library 2002 Folder",
            "",
        )
        if not folder_path:
            return
        self._run_catalog_task(
            lambda: self.connector.import_winlens_library(folder_path),
            success_handler=self._handle_winlens_import_success,
            error_title="WinLens Import Failed",
        )

    def _handle_winlens_import_success(self, result) -> None:  # noqa: ANN001
        self._notify(
            result.message,
            "success" if result.imported_count else "info",
        )
        review_rows = self.connector.get_winlens_review_candidates(76)
        if review_rows:
            self._show_winlens_review_dialog(review_rows)

    def _show_winlens_review_dialog(self, review_rows: list[dict[str, object]]) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("Review Strong WinLens Candidates")
        dialog.resize(1120, 420)
        layout = QVBoxLayout(dialog)
        layout.addWidget(
            QLabel(
                "These WinLens candidate matches exceed the review threshold. "
                "Keep 'Apply' checked for links you want to confirm."
            )
        )
        tree = QTreeWidget(dialog)
        tree.setColumnCount(10)
        tree.setHeaderLabels(
            [
                "Apply",
                "Family",
                "WinLens Part",
                "Name",
                "Status",
                "Target",
                "Confidence",
                "Score",
                "Preview",
                "Reasons",
            ]
        )
        tree.header().setStretchLastSection(True)
        family_items: dict[str, QTreeWidgetItem] = {}
        for item in review_rows:
            family_key = str(item.get("family_key", "")) or "-"
            parent_item = family_items.get(family_key)
            if parent_item is None:
                parent_item = QTreeWidgetItem(tree)
                parent_item.setFlags(
                    parent_item.flags()
                    | Qt.ItemFlag.ItemIsUserCheckable
                    | Qt.ItemFlag.ItemIsSelectable
                    | Qt.ItemFlag.ItemIsEnabled
                )
                parent_item.setCheckState(0, Qt.CheckState.Checked)
                parent_item.setText(1, family_key)
                parent_item.setText(3, f"Family {family_key}")
                parent_item.setText(8, "Apply or clear this whole family")
                parent_item.setExpanded(True)
                family_items[family_key] = parent_item

            child = QTreeWidgetItem(parent_item)
            child.setFlags(
                child.flags()
                | Qt.ItemFlag.ItemIsUserCheckable
                | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsEnabled
            )
            child.setCheckState(0, Qt.CheckState.Checked)
            child.setData(0, Qt.ItemDataRole.UserRole, item)
            child.setText(1, family_key)
            child.setText(2, str(item.get("winlens_part_number", "")))
            child.setText(3, str(item.get("winlens_name", "")))
            child.setText(4, str(item.get("status", "")))
            child.setText(5, str(item.get("target_part_number", "")))
            child.setText(6, f"{int(item.get('confidence_percent', 0))}%")
            child.setText(7, str(item.get("score", "")))
            child.setText(8, str(item.get("preview", "")))
            child.setText(9, ", ".join(item.get("reasons", [])))
        tree.itemChanged.connect(self._handle_review_tree_item_changed)
        layout.addWidget(tree, 1)
        select_all = QCheckBox("Apply all shown", dialog)
        select_all.setChecked(True)
        select_all.toggled.connect(
            lambda checked: self._set_review_tree_checked(tree, checked)
        )
        layout.addWidget(select_all)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=dialog,
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        selections: list[dict[str, str]] = []
        root = tree.invisibleRootItem()
        for parent_index in range(root.childCount()):
            parent_item = root.child(parent_index)
            for child_index in range(parent_item.childCount()):
                child = parent_item.child(child_index)
                if child.checkState(0) != Qt.CheckState.Checked:
                    continue
                payload = child.data(0, Qt.ItemDataRole.UserRole)
                if not isinstance(payload, dict):
                    continue
                selections.append(
                    {
                        "winlens_catalog_id": str(payload.get("winlens_catalog_id", "")),
                        "target_catalog_id": str(payload.get("target_catalog_id", "")),
                    }
                )
        if not selections:
            return
        confirmed = self.connector.confirm_winlens_links(selections)
        self._notify(f"Confirmed {confirmed} WinLens link(s).", "success" if confirmed else "info")

    def _set_review_tree_checked(self, tree: QTreeWidget, checked: bool) -> None:
        self._updating_review_tree_checks = True
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        root = tree.invisibleRootItem()
        for parent_index in range(root.childCount()):
            parent_item = root.child(parent_index)
            parent_item.setCheckState(0, state)
            for child_index in range(parent_item.childCount()):
                parent_item.child(child_index).setCheckState(0, state)
        self._updating_review_tree_checks = False

    def _handle_review_tree_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if column != 0 or self._updating_review_tree_checks:
            return
        self._updating_review_tree_checks = True
        try:
            if item.childCount() > 0:
                for child_index in range(item.childCount()):
                    item.child(child_index).setCheckState(0, item.checkState(0))
            else:
                parent = item.parent()
                if parent is not None:
                    checked = 0
                    unchecked = 0
                    for child_index in range(parent.childCount()):
                        child_state = parent.child(child_index).checkState(0)
                        if child_state == Qt.CheckState.Checked:
                            checked += 1
                        else:
                            unchecked += 1
                    if checked and unchecked:
                        parent.setCheckState(0, Qt.CheckState.PartiallyChecked)
                    elif checked:
                        parent.setCheckState(0, Qt.CheckState.Checked)
                    else:
                        parent.setCheckState(0, Qt.CheckState.Unchecked)
        finally:
            self._updating_review_tree_checks = False

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

    def _download_excelitas_catalog(self) -> None:
        self._run_catalog_task(
            self.connector.download_excelitas_catalog,
            success_handler=lambda result: self._notify(
                result.message,
                "success" if result.imported_count else "info",
            ),
            error_title="Excelitas / LINOS Catalog Download Failed",
            error_handler=self._show_excelitas_download_help,
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

    def _show_excelitas_download_help(self, error_text: str) -> None:
        """Show a guided fallback dialog when Excelitas auto-download is incomplete."""
        dialog = QMessageBox(self)
        dialog.setIcon(QMessageBox.Icon.Warning)
        dialog.setWindowTitle("Excelitas / LINOS Catalog Download Failed")
        dialog.setText("Automatic catalog download could not be completed.")
        dialog.setInformativeText(
            "Open the official LINOS / Excelitas product pages in your browser, "
            "download any available ZEMAX files manually, and then import the "
            "downloaded ZIP, ZMX, or ZMF file."
        )
        dialog.setDetailedText(error_text)
        open_button = dialog.addButton(
            "Open Product Pages",
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
            QDesktopServices.openUrl(QUrl("https://linosoptics.excelitas.com/en/"))
        elif clicked == import_button:
            self._import_catalog_files("Excelitas")

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
            if mode == "before":
                surface_index = lens_editor.connector.get_surface_count() - 1
            else:
                self._notify(
                    "Select a target surface in the Lens Data Editor first.", "info"
                )
                return
        else:
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

    def _selected_catalog_details(self) -> dict | None:
        """Return the full details dict for the currently selected catalog entry."""
        catalog_id = self._selected_catalog_id()
        if not catalog_id:
            return None
        return self.connector.get_catalog_lens_details(catalog_id)

    def _copy_current_cell_to_clipboard(self) -> None:
        """Copy the currently focused result cell to the clipboard."""
        row, col = self._results_table_copy.current_cell()
        if row < 0 or col < 0:
            return
        item = self.results_table.item(row, col)
        current_item = self.results_table.currentItem()
        if (
            (item is None or item.text() == "")
            and current_item is not None
            and current_item.text() != ""
        ):
            item = current_item
        if item is None:
            return
        QApplication.clipboard().setText(item.text())
        self._notify("Copied cell value.", "info")

    def _copy_selected_row_to_clipboard(self) -> None:
        """Copy the selected result row as a tab-separated line."""
        row, _col = self._results_table_copy.current_cell()
        if row < 0:
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

    def _open_selected_vendor_document(self) -> None:
        """Open the first cached official vendor document for the selected entry."""
        catalog_id = self._selected_catalog_id()
        if not catalog_id:
            return
        urls = self.connector.get_catalog_document_urls(catalog_id)
        if not urls:
            self._notify("No vendor document available for this catalog entry.", "warning")
            return
        QDesktopServices.openUrl(QUrl(urls[0]))

    def _open_vendor_document_url(self, url: str) -> None:
        """Open a specific vendor-document URL."""
        if not url:
            self._notify("No vendor document available for this catalog entry.", "warning")
            return
        QDesktopServices.openUrl(QUrl(url))

    def _populate_vendor_document_menu(self, menu: QMenu, document_urls: list[str]) -> None:
        """Populate *menu* with one action per vendor-document URL."""
        for index, url in enumerate(document_urls, start=1):
            label = f"Document {index}"
            if "/" in url:
                label = url.rsplit("/", 1)[-1] or label
            action = menu.addAction(label)
            action.triggered.connect(
                lambda _checked=False, value=url: self._open_vendor_document_url(value)
            )

    def _show_results_context_menu(self, pos) -> None:  # noqa: ANN001
        """Show a context menu with copy and product-link actions for the result table."""
        item = self.results_table.itemAt(pos)
        if item is not None:
            self.results_table.setCurrentItem(item)
            self.results_table.selectRow(item.row())

        menu = QMenu(self.results_table)
        insert_before_action = menu.addAction("Insert Before Selected Surface")
        insert_after_action = menu.addAction("Insert After Selected Surface")
        menu.addSeparator()
        copy_cell_action = menu.addAction("Copy Cell")
        copy_row_action = menu.addAction("Copy Row")
        menu.addSeparator()

        current_item = self.results_table.currentItem()
        has_item = current_item is not None and current_item.row() >= 0
        catalog_id = self._selected_catalog_id() if has_item else ""
        product_url = self.connector.resolve_catalog_product_url(catalog_id) if catalog_id else ""
        document_urls = self.connector.get_catalog_document_urls(catalog_id) if catalog_id else []
        insert_before_action.setEnabled(has_item)
        insert_after_action.setEnabled(has_item)
        copy_cell_action.setEnabled(has_item)
        copy_row_action.setEnabled(has_item)

        document_menu = None
        open_document_action = None
        if product_url:
            open_url_action = menu.addAction("Open Product Webpage")
        else:
            open_url_action = None
        if len(document_urls) == 1:
            open_document_action = menu.addAction("Open Vendor Document")
        elif len(document_urls) > 1:
            document_menu = menu.addMenu("Open Vendor Document")
            self._populate_vendor_document_menu(document_menu, document_urls)

        chosen = menu.exec(self.results_table.viewport().mapToGlobal(pos))
        if chosen == insert_before_action:
            self._insert_selected("before")
        elif chosen == insert_after_action:
            self._insert_selected("after")
        elif chosen == copy_cell_action:
            self._copy_current_cell_to_clipboard()
        elif chosen == copy_row_action:
            self._copy_selected_row_to_clipboard()
        elif open_url_action is not None and chosen == open_url_action:
            self._open_selected_catalog_url()
        elif open_document_action is not None and chosen == open_document_action:
            self._open_selected_vendor_document()

    def _sync_filter_row_geometry(self, *args) -> None:  # noqa: ANN002
        """Keep the filter row aligned with the table columns."""
        if not self._filter_widgets_ready:
            return
        header = self.results_table.horizontalHeader()
        total_width = sum(
            header.sectionSize(column) for column in range(self.results_table.columnCount())
        )
        frame_width = self.results_table.frameWidth() * 2
        vertical_scrollbar_width = self.results_table.verticalScrollBar().sizeHint().width()
        content_width = total_width + frame_width + vertical_scrollbar_width
        self.filter_row_container.setMinimumWidth(content_width)
        self.results_table.setMinimumWidth(content_width)
        widgets = (
            None,
            self.manufacturer_filter,
            self.part_number_filter,
            self.name_filter,
            self.category_filter,
            self.efl_filter,
            self.diameter_filter,
            self.material_filter,
            self.coating_filter,
            self.status_filter,
            self.match_filter,
        )
        margin = 2
        for column, widget in enumerate(widgets):
            if widget is None:
                continue
            widget.setGeometry(
                header.sectionViewportPosition(column) + margin,
                margin,
                max(40, header.sectionSize(column) - (margin * 2)),
                self._filter_row_height - (margin * 2),
            )
        self.filter_row_container.update()

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

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self.results_table and event.type() == QEvent.Type.Resize:
            self._sync_filter_row_geometry()
        return super().eventFilter(watched, event)

    def _advance_busy_indicator(self) -> None:
        """Advance the spinner frame shown beside the import button."""
        self._busy_frame_index = (self._busy_frame_index + 1) % len(self._busy_frames)
        self.import_busy_indicator.setText(self._busy_frames[self._busy_frame_index])

    def closeEvent(self, event) -> None:  # noqa: ANN001, N802
        """Shut down any running catalog task cleanly before the panel closes."""
        self._set_task_busy(False)
        self._result_population_timer.stop()
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
