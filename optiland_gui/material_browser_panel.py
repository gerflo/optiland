"""Dockable material database browser panel."""

from __future__ import annotations

from typing import Callable, TYPE_CHECKING

from PySide6.QtCore import QObject, QSize, Qt, QThread, QTimer, Signal, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QComboBox,
)
from PySide6.QtCore import QUrl

if TYPE_CHECKING:
    from .optiland_connector import OptilandConnector


class _MaterialTaskWorker(QObject):
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
    def __init__(self, height: int, parent=None) -> None:
        super().__init__(parent)
        self._row_height = height

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(0, self._row_height)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(0, self._row_height)


class MaterialBrowserPanel(QWidget):
    """Browse the local material database and import WinLens materials."""

    _task_finished = Signal(object, object)

    RESULT_COLUMNS = [
        "Mark",
        "Reference",
        "Name",
        "Category",
        "Source",
        "Min λ",
        "Max λ",
        "File",
    ]

    def __init__(self, connector: OptilandConnector, parent=None) -> None:
        super().__init__(parent)
        self.connector = connector
        self._current_results: list[dict] = []
        self._filter_widgets_ready = False
        self._filter_row_height = 30
        self._task_thread: QThread | None = None
        self._task_worker: _MaterialTaskWorker | None = None
        self._task_success_handler: Callable[[object], None] | None = None
        self._task_error_title = ""
        self._marked_material_ids: set[str] = set()
        self._updating_mark_column = False
        self._busy_frames = ["|", "/", "-", "\\"]
        self._busy_frame_index = 0
        self._busy_timer = QTimer(self)
        self._busy_timer.setInterval(120)
        self._busy_timer.timeout.connect(self._advance_busy_indicator)
        self._build_ui()
        self._wire_signals()
        self.refresh()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        controls_box = QGroupBox("Material Tools")
        controls_layout = QHBoxLayout(controls_box)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search by reference, glass name, category...")
        controls_layout.addWidget(QLabel("Search"))
        controls_layout.addWidget(self.search_edit, 1)

        self.reset_filters_button = QPushButton("↻")
        self.reset_filters_button.setToolTip("Reset all material filters")
        self.reset_filters_button.setObjectName("MaterialResetFiltersButton")
        self.reset_filters_button.setFixedWidth(42)
        controls_layout.addWidget(self.reset_filters_button)

        self.mark_filtered_button = QPushButton("Mark Filtered")
        self.clear_marks_button = QPushButton("Clear Marks")
        self.delete_marked_button = QPushButton("Delete Marked")
        controls_layout.addWidget(self.mark_filtered_button)
        controls_layout.addWidget(self.clear_marks_button)
        controls_layout.addWidget(self.delete_marked_button)

        self.import_winlens_button = QPushButton("Import WinLens Materials...")
        controls_layout.addWidget(self.import_winlens_button)

        self.import_busy_indicator = QLabel("")
        self.import_busy_indicator.setVisible(False)
        self.import_busy_indicator.setFixedWidth(16)
        self.import_busy_indicator.setAlignment(Qt.AlignmentFlag.AlignCenter)
        controls_layout.addWidget(self.import_busy_indicator)
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
        self.table_view_layout = QVBoxLayout(self.table_view_content)
        self.table_view_layout.setContentsMargins(0, 0, 0, 0)
        self.table_view_layout.setSpacing(0)

        self.filter_row_container = _PinnedFilterRow(self._filter_row_height)
        self.filter_row_container.setFixedHeight(self._filter_row_height)
        self.filter_row_container.setMinimumWidth(0)
        self.filter_row_container.setSizePolicy(
            QSizePolicy.Policy.MinimumExpanding,
            QSizePolicy.Policy.Fixed,
        )
        self.table_view_layout.addWidget(self.filter_row_container)

        self.results_table = QTableWidget(0, len(self.RESULT_COLUMNS))
        self.results_table.setHorizontalHeaderLabels(self.RESULT_COLUMNS)
        self.results_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.results_table.setSelectionMode(QTableWidget.SingleSelection)
        self.results_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.results_table.itemChanged.connect(self._handle_results_item_changed)
        self.results_table.verticalHeader().setVisible(False)
        header = self.results_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(False)
        header.setSectionsMovable(True)
        self.results_table.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.table_view_layout.addWidget(self.results_table, 1)
        self.table_view_scroll.setWidget(self.table_view_content)
        layout.addWidget(self.table_view_scroll, 1)

        self.status_label = QLabel("No materials loaded.")
        layout.addWidget(self.status_label)

        details_box = QGroupBox("Selection Details")
        details_layout = QVBoxLayout(details_box)
        self.details_text = QLabel()
        self.details_text.setWordWrap(True)
        self.details_text.setTextFormat(Qt.TextFormat.RichText)
        self.details_text.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.details_text.setMinimumHeight(72)
        details_layout.addWidget(self.details_text)
        details_actions = QHBoxLayout()
        self.open_material_file_button = QPushButton("Open Material File")
        details_actions.addWidget(self.open_material_file_button)
        details_actions.addStretch(1)
        details_layout.addLayout(details_actions)
        layout.addWidget(details_box)

    def _wire_signals(self) -> None:
        self.search_edit.textChanged.connect(self.refresh)
        self.reset_filters_button.clicked.connect(self._reset_filters)
        self.mark_filtered_button.clicked.connect(self._mark_filtered_results)
        self.clear_marks_button.clicked.connect(self._clear_marked_results)
        self.delete_marked_button.clicked.connect(self._delete_marked_results)
        self.import_winlens_button.clicked.connect(self._import_winlens_materials)
        self.open_material_file_button.clicked.connect(self._open_selected_material_file)
        self.results_table.itemSelectionChanged.connect(self._update_details)
        header = self.results_table.horizontalHeader()
        header.sectionResized.connect(self._sync_filter_row_geometry)
        header.sectionMoved.connect(self._sync_filter_row_geometry)
        self.connector.materialsChanged.connect(self.refresh)
        self._task_finished.connect(self._handle_task_finished, Qt.ConnectionType.QueuedConnection)

    @Slot()
    def refresh(self) -> None:
        self._ensure_filter_row()
        query = {
            "text": self.search_edit.text(),
            "reference": self.reference_filter.currentData() or "",
            "name": self.name_filter.text(),
            "category": self.category_filter.text(),
            "source": self.source_filter.currentData() or "",
            "min_wavelength": self.min_wavelength_filter.text(),
            "max_wavelength": self.max_wavelength_filter.text(),
        }
        self._current_results = self.connector.search_materials(query)
        self._refresh_reference_filter()
        self._populate_results()

    def _populate_results(self) -> None:
        self.results_table.clearContents()
        self.results_table.setRowCount(len(self._current_results))
        self._updating_mark_column = True
        for row, record in enumerate(self._current_results):
            mark_item = QTableWidgetItem("")
            material_id = str(record.get("material_id", ""))
            mark_item.setData(Qt.UserRole, material_id)
            mark_item.setFlags(
                Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsUserCheckable
            )
            mark_item.setCheckState(
                Qt.CheckState.Checked
                if material_id in self._marked_material_ids
                else Qt.CheckState.Unchecked
            )
            if not record.get("is_local_import"):
                mark_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self.results_table.setItem(row, 0, mark_item)
            values = [
                record.get("reference", ""),
                record.get("name", ""),
                record.get("category", ""),
                record.get("source", ""),
                _fmt_float(record.get("min_wavelength"), 3),
                _fmt_float(record.get("max_wavelength"), 3),
                record.get("filename", ""),
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, material_id)
                if col in (4, 5):
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    )
                self.results_table.setItem(row, col + 1, item)
        self._updating_mark_column = False

        self._sync_filter_row_geometry()
        count = len(self._current_results)
        self.status_label.setText(f"{count} material entries found." if count else "No materials found.")
        if count:
            self.results_table.selectRow(0)
            self._update_details()
        else:
            self.details_text.clear()

    def _ensure_filter_row(self) -> None:
        if self._filter_widgets_ready:
            return
        self.reference_filter = QComboBox(self.filter_row_container)
        self.reference_filter.addItem("All", "")
        self.name_filter = QLineEdit(self.filter_row_container)
        self.category_filter = QLineEdit(self.filter_row_container)
        self.source_filter = QComboBox(self.filter_row_container)
        self.source_filter.addItem("All", "")
        self.source_filter.addItem("Built-in Glass", "Built-in Glass")
        self.source_filter.addItem("RefractiveIndex.info", "RefractiveIndex.info")
        self.source_filter.addItem("WinLens Import", "WinLens Import")
        self.min_wavelength_filter = QLineEdit(self.filter_row_container)
        self.max_wavelength_filter = QLineEdit(self.filter_row_container)
        self.file_filter = QLineEdit(self.filter_row_container)
        self.file_filter.setVisible(False)

        self.name_filter.setPlaceholderText("filter")
        self.category_filter.setPlaceholderText("filter")
        self.min_wavelength_filter.setPlaceholderText("0.4")
        self.max_wavelength_filter.setPlaceholderText("1.0")

        for widget in (
            self.name_filter,
            self.category_filter,
            self.min_wavelength_filter,
            self.max_wavelength_filter,
        ):
            widget.setMinimumWidth(0)
            widget.textChanged.connect(self.refresh)
        self.reference_filter.currentIndexChanged.connect(self.refresh)
        self.source_filter.currentIndexChanged.connect(self.refresh)
        self._filter_widgets_ready = True
        self._sync_filter_row_geometry()

    def _refresh_reference_filter(self) -> None:
        current_value = self.reference_filter.currentData()
        references = self.connector.get_material_references()
        self.reference_filter.blockSignals(True)
        self.reference_filter.clear()
        self.reference_filter.addItem("All", "")
        for reference in references:
            self.reference_filter.addItem(reference, reference)
        index = self.reference_filter.findData(current_value)
        self.reference_filter.setCurrentIndex(index if index >= 0 else 0)
        self.reference_filter.blockSignals(False)

    def _reset_filters(self) -> None:
        self.search_edit.clear()
        if self._filter_widgets_ready:
            self.reference_filter.setCurrentIndex(0)
            self.name_filter.clear()
            self.category_filter.clear()
            self.source_filter.setCurrentIndex(0)
            self.min_wavelength_filter.clear()
            self.max_wavelength_filter.clear()
        self.refresh()

    def _selected_material_id(self) -> str:
        selected = self.results_table.selectedItems()
        if not selected:
            return ""
        return str(selected[0].data(Qt.UserRole) or "")

    def _selected_material_details(self) -> dict | None:
        material_id = self._selected_material_id()
        if not material_id:
            return None
        return self.connector.get_material_details(material_id)

    def _update_details(self) -> None:
        details = self._selected_material_details()
        if not details:
            self.details_text.clear()
            self.open_material_file_button.setEnabled(False)
            return
        self.details_text.setText(
            "<br>".join(
                [
                    f"<b>{details.get('name', '-')}</b>",
                    f"Reference: {details.get('reference', '-')}",
                    f"Category: {details.get('category_full', details.get('category', '-'))}",
                    f"Source: {details.get('source', '-')}",
                    (
                        "Wavelength range: "
                        f"{_fmt_float(details.get('min_wavelength'), 3)} - "
                        f"{_fmt_float(details.get('max_wavelength'), 3)} um"
                    ),
                    f"File: {details.get('filename', '-')}",
                ]
            )
        )
        self.open_material_file_button.setEnabled(bool(details.get("absolute_filename")))

    def _import_winlens_materials(self) -> None:
        folder_path = QFileDialog.getExistingDirectory(
            self,
            "Import WinLens Material Database Folder",
            "",
        )
        if not folder_path:
            return
        self._run_task(
            lambda: self.connector.import_winlens_materials(folder_path),
            success_handler=self._handle_import_success,
            error_title="WinLens Material Import Failed",
        )

    def _handle_import_success(self, result) -> None:  # noqa: ANN001
        self.refresh()
        self._notify(result.message, "success" if result.imported_count else "info")

    def _handle_results_item_changed(self, item: QTableWidgetItem) -> None:
        if self._updating_mark_column or item.column() != 0:
            return
        material_id = str(item.data(Qt.UserRole) or "")
        if not material_id:
            return
        if item.checkState() == Qt.CheckState.Checked:
            self._marked_material_ids.add(material_id)
        else:
            self._marked_material_ids.discard(material_id)

    def _mark_filtered_results(self) -> None:
        for record in self._current_results:
            if record.get("is_local_import"):
                self._marked_material_ids.add(str(record.get("material_id", "")))
        self.refresh()

    def _clear_marked_results(self) -> None:
        self._marked_material_ids.clear()
        self.refresh()

    def _delete_marked_results(self) -> None:
        if not self._marked_material_ids:
            self._notify("No marked imported materials selected.", "info")
            return
        if (
            QMessageBox.question(
                self,
                "Delete Marked Materials",
                "Delete the marked local imported material entries?",
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        deleted = self.connector.delete_materials(sorted(self._marked_material_ids))
        deleted_ids = {
            str(record.get("material_id", ""))
            for record in self._current_results
            if str(record.get("material_id", "")) in self._marked_material_ids
            and record.get("is_local_import")
        }
        self._marked_material_ids.difference_update(deleted_ids)
        self.refresh()
        self._notify(
            f"Deleted {deleted} imported material(s)." if deleted else "No imported materials were deleted.",
            "success" if deleted else "info",
        )

    def _open_selected_material_file(self) -> None:
        details = self._selected_material_details()
        if not details:
            self._notify("Select a material entry first.", "info")
            return
        filename = str(details.get("absolute_filename", "")).strip()
        if not filename:
            self._notify("No local material file available for this entry.", "warning")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(filename))

    def _run_task(
        self,
        task: Callable[[], object],
        *,
        success_handler: Callable[[object], None],
        error_title: str,
    ) -> None:
        if self._task_thread is not None:
            self._notify("A material import is already running.", "info")
            return
        self._set_task_busy(True)
        self._task_success_handler = success_handler
        self._task_error_title = error_title
        self._task_thread = QThread()
        self._task_worker = _MaterialTaskWorker(task)
        self._task_worker.moveToThread(self._task_thread)
        self._task_thread.started.connect(self._task_worker.run)
        self._task_worker.finished.connect(self._task_finished.emit)
        self._task_worker.finished.connect(self._task_thread.quit)
        self._task_thread.finished.connect(self._task_thread.deleteLater)
        self._task_thread.finished.connect(self._task_worker.deleteLater)
        self._task_thread.start()

    @Slot(object, object)
    def _handle_task_finished(self, result: object, error: object) -> None:
        self._set_task_busy(False)
        thread = self._task_thread
        success_handler = self._task_success_handler
        error_title = self._task_error_title

        self._task_worker = None
        self._task_thread = None
        self._task_success_handler = None
        self._task_error_title = ""

        if thread is not None and thread.isRunning():
            thread.quit()
            thread.wait(5000)

        if error is not None:
            QMessageBox.warning(self, error_title, str(error))
            return
        if success_handler is not None:
            success_handler(result)

    def _set_task_busy(self, busy: bool) -> None:
        self.import_winlens_button.setEnabled(not busy)
        self.reset_filters_button.setEnabled(not busy)
        self.mark_filtered_button.setEnabled(not busy)
        self.clear_marks_button.setEnabled(not busy)
        self.delete_marked_button.setEnabled(not busy)
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
        self._busy_frame_index = (self._busy_frame_index + 1) % len(self._busy_frames)
        self.import_busy_indicator.setText(self._busy_frames[self._busy_frame_index])

    def _sync_filter_row_geometry(self, *args) -> None:  # noqa: ANN002
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
            self.reference_filter,
            self.name_filter,
            self.category_filter,
            self.source_filter,
            self.min_wavelength_filter,
            self.max_wavelength_filter,
            self.file_filter,
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


def _fmt_float(value, precision: int = 2) -> str:  # noqa: ANN001
    if value in (None, ""):
        return "-"
    try:
        return f"{float(value):.{precision}f}"
    except (TypeError, ValueError):
        return str(value)
