"""Defines the LensEditor widget for displaying and editing optical system data.

This module contains the `LensEditor` class, a QWidget that provides a spreadsheet-like
interface (QTableWidget) for modifying the properties of an optical system's surfaces,
such as radius, thickness, and material.

Author: Manuel Fragata Mendes, 2025
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, QSize, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QBrush, QColor, QIcon, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemDelegate,
    QAbstractItemView,
    QCompleter,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from shiboken6 import isValid

from optiland.materials.material import Material

if TYPE_CHECKING:
    from .optiland_connector import OptilandConnector


class SurfacePropertiesWidget(QWidget):
    """A widget to display and edit specific parameters of a surface geometry."""

    def __init__(self, row, connector, parent=None):
        super().__init__(parent)
        self.row = row
        self.connector = connector
        self.setObjectName("SurfacePropertiesWidget")
        self.setMinimumWidth(750)
        self.setMinimumHeight(100)
        self.setMaximumHeight(200)

        self.input_widgets = {}
        self._populate_properties_form()

    def _create_parameter_input(self, name, value):
        """Creates a configured QLineEdit for a given surface parameter."""
        line_edit = QLineEdit()
        line_edit.setMaximumWidth(60)

        if isinstance(value, (list | tuple)) or hasattr(value, "tolist"):
            list_val = value.tolist() if hasattr(value, "tolist") else value
            line_edit.setText(str(list_val))
            line_edit.setPlaceholderText("e.g., [0.1, -0.2]")
        else:
            line_edit.setText(f"{value:.6f}")

        line_edit.editingFinished.connect(self.apply_changes)
        self.input_widgets[name] = line_edit
        return line_edit

    def _populate_properties_form(self):
        """Creates and populates the form layout with surface parameter widgets."""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(15, 8, 15, 8)
        columns_layout = QHBoxLayout()
        columns_layout.setSpacing(20)
        main_layout.addLayout(columns_layout)

        params = self.connector.get_surface_geometry_params(self.row)

        if not params:
            form_layout = QFormLayout()
            form_layout.addRow(
                QLabel("No additional properties for this surface type.")
            )
            columns_layout.addLayout(form_layout)
            return

        items_per_column = 2
        param_items = list(params.items())
        num_columns = (len(param_items) + items_per_column - 1) // items_per_column

        for col in range(num_columns):
            form_layout = QFormLayout()
            form_layout.setHorizontalSpacing(15)
            form_layout.setVerticalSpacing(5)

            start_idx = col * items_per_column
            end_idx = min((col + 1) * items_per_column, len(param_items))

            for i in range(start_idx, end_idx):
                name, value = param_items[i]
                label_text = name + ":"
                line_edit = self._create_parameter_input(name, value)
                form_layout.addRow(label_text, line_edit)

            columns_layout.addLayout(form_layout)

        columns_layout.addStretch(1)

    @Slot()
    def apply_changes(self):
        """Collects data from input fields and sends it to the connector."""
        params_to_set = {}
        for name, widget in self.input_widgets.items():
            params_to_set[name] = widget.text()
        self.connector.set_surface_geometry_params(self.row, params_to_set)


class SurfaceTypeWidget(QWidget):
    """A custom widget for the 'Type' column, allowing text edit and dropdown."""

    surfaceTypeChanged = Signal(str)
    propertiesIconClicked = Signal()

    def __init__(self, row, current_type_info, connector, parent=None):
        super().__init__(parent)
        self.row = row
        self.connector = connector
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(2, 0, 2, 0)
        self.layout.setSpacing(4)
        self.type_button = QToolButton()
        self.type_button.setObjectName("SurfaceTypeButton")
        self.type_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.type_button.setFixedSize(18, 18)
        self.type_button.setAutoRaise(True)
        self.type_button.setArrowType(Qt.DownArrow)

        # properties button
        self.props_button = QToolButton()
        self.props_button.setObjectName("PropertiesButton")
        self.props_button.setIcon(QIcon(":/icons/dark/tool.svg"))
        self.props_button.setFixedSize(20, 20)
        self.props_button.setIconSize(QSize(16, 16))
        self.props_button.setToolTip("Show/Hide Surface Properties")
        self.props_button.clicked.connect(self.propertiesIconClicked.emit)
        self.layout.addWidget(self.props_button)

        # hide the button if there are no properties to show
        if not current_type_info.get("has_extra_params", False):
            self.props_button.hide()

        self.type_edit = QLineEdit(current_type_info["display_text"])
        self.type_edit.setObjectName("SurfaceTypeLineEdit")
        self.type_edit.editingFinished.connect(self.text_changed)
        self.layout.addWidget(self.type_edit, 1)
        self.layout.addWidget(self.type_button)
        self.surface_menu = QMenu(self)
        self.surface_menu.setObjectName("SurfaceTypeMenu")
        for surf_type in self.connector.get_available_surface_types():
            action = self.surface_menu.addAction(surf_type.title())
            action.triggered.connect(
                lambda checked=False, t=surf_type: self.type_selected(t)
            )
        self.type_button.setMenu(self.surface_menu)
        is_editable = current_type_info["is_changeable"]
        self.type_button.setEnabled(is_editable)
        self.type_button.setVisible(is_editable)
        self.type_edit.setReadOnly(not is_editable)

        # Badge label shown when non-standard variable types are registered
        self._var_badge = QLabel("V")
        self._var_badge.setObjectName("VariableBadge")
        self._var_badge.setFixedSize(16, 16)
        self._var_badge.setAlignment(Qt.AlignCenter)
        self._var_badge.setStyleSheet(
            "QLabel#VariableBadge {"
            "  background-color: #6488ea;"
            "  color: #ffffff;"
            "  border-radius: 3px;"
            "  font-size: 9px;"
            "  font-weight: bold;"
            "}"
        )
        self._var_badge.setVisible(False)
        self.layout.insertWidget(0, self._var_badge)

    def setHasVariables(self, types: list[str]) -> None:
        """Show or hide the variable badge for non-standard variable types.

        Args:
            types: List of non-standard variable type strings registered for
                this surface (e.g. ``["asphere_coeff", "index"]``).
        """
        if types:
            self._var_badge.setToolTip("Optimization variables: " + ", ".join(types))
            self._var_badge.setVisible(True)
        else:
            self._var_badge.setVisible(False)

    def type_selected(self, new_type):
        self.type_edit.setText(new_type.title())
        self.surfaceTypeChanged.emit(new_type)

    def text_changed(self):
        new_type = self.type_edit.text()
        if new_type.lower().strip() in self.connector.get_available_surface_types():
            self.surfaceTypeChanged.emit(new_type)
        else:
            type_info = self.connector.get_surface_type_info(self.row)
            self.type_edit.setText(type_info["display_text"])


class _AccentFocusDelegate(QStyledItemDelegate):
    """Item delegate that draws an accent-coloured border around the focused cell.

    Replaces Qt's default dotted focus rectangle with a clean 1.5 px accent
    border so the active cell is clearly visible without visual noise.
    """

    _ACCENT = QColor("#007ACC")

    def __init__(self, owner, parent=None):
        super().__init__(parent)
        self._owner = owner

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index,
    ) -> None:
        super().paint(painter, option, index)
        from PySide6.QtWidgets import QStyle

        if option.state & QStyle.State_HasFocus:
            painter.save()
            pen = QPen(self._ACCENT, 1.5)
            painter.setPen(pen)
            painter.drawRect(option.rect.adjusted(1, 1, -1, -1))
            painter.restore()

    def createEditor(self, parent, option, index):  # noqa: ANN001
        """Install custom tab navigation on transient table editors."""
        editor = super().createEditor(parent, option, index)
        if editor is not None:
            editor.setProperty("lens_row", index.row())
            editor.setProperty("lens_col", index.column())
            editor.setProperty("lens_table_editor", True)
            editor.installEventFilter(self._owner)
        return editor


class _MaterialSearchDelegate(_AccentFocusDelegate):
    """Editable material delegate with match-as-you-type search suggestions."""

    def __init__(self, owner, material_names: list[str], parent=None):
        super().__init__(owner, parent)
        self._material_names = material_names

    def createEditor(self, parent, option, index):  # noqa: ANN001
        editor = QLineEdit(parent)
        editor.setObjectName("MaterialSearchEditor")
        editor.setFrame(False)
        editor.setStyleSheet(
            "QLineEdit#MaterialSearchEditor {"
            "  border: none;"
            "  padding: 0px 2px;"
            "  margin: 0px;"
            "  background-color: palette(window);"
            "  color: palette(window-text);"
            "  selection-background-color: palette(highlight);"
            "  selection-color: palette(highlighted-text);"
            "}"
        )
        editor.setProperty("lens_row", index.row())
        editor.setProperty("lens_col", index.column())
        editor.setProperty("lens_table_editor", True)
        editor.installEventFilter(self._owner)
        editor.setTextMargins(2, 0, 2, 0)

        completer = QCompleter(self._material_names, editor)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setFilterMode(Qt.MatchContains)
        completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        editor.setCompleter(completer)
        editor.textEdited.connect(
            lambda _=None, e=editor: self._show_editor_completer(e)
        )
        completer.activated.connect(
            lambda text, e=editor: self._owner._accept_material_completion(e, text)
        )

        return editor

    @staticmethod
    def _show_editor_completer(editor: QLineEdit) -> None:
        """Anchor the suggestions popup directly below the active editor field."""
        if not isValid(editor):
            return
        completer = editor.completer()
        if completer is None or not isValid(completer):
            return
        popup_rect = editor.rect()
        popup_rect.moveTop(editor.height() + 2)
        popup_rect.setWidth(max(popup_rect.width(), 220))
        completer.complete(popup_rect)

    def setEditorData(self, editor, index) -> None:  # noqa: ANN001
        value = index.data(Qt.ItemDataRole.EditRole) or "Air"
        editor.setText(str(value))
        editor.selectAll()

    def setModelData(self, editor, model, index) -> None:  # noqa: ANN001
        material_name = editor.text().strip() or "Air"
        model.setData(index, material_name, Qt.ItemDataRole.EditRole)


class LensEditor(QWidget):
    """A widget for editing the properties of an optical system's surfaces."""

    _material_names_cache: list[str] | None = None

    def __init__(self, connector: OptilandConnector, parent=None):
        super().__init__(parent)
        self.connector = connector
        self.setWindowTitle("Lens Editor")
        self.open_prop_source_row = -1
        self._pending_insert_surface_index: int | None = None
        self._pending_insert_ui_row: int | None = None

        self._init_ui()
        self.setup_table()
        self.load_data()
        self.connect_signals()

    @classmethod
    def _get_material_names(cls) -> list[str]:
        """Return material names for the search delegate, keeping Air first."""
        if cls._material_names_cache is None:
            df = Material._load_dataframe()
            names = {
                str(name).strip()
                for name in df["filename_no_ext"].dropna().tolist()
                if str(name).strip()
            }
            names.discard("Air")
            cls._material_names_cache = ["Air", *sorted(names, key=str.casefold)]
        return cls._material_names_cache

    def _init_ui(self):
        """Initializes the main UI components of the editor."""
        self.layout = QVBoxLayout(self)
        self.tableWidget = QTableWidget()
        self.tableWidget.installEventFilter(self)
        self.tableWidget.setContextMenuPolicy(Qt.CustomContextMenu)

        # ScrollPerPixel for smooth scrolling (SPEC §4.6)
        self.tableWidget.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.tableWidget.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.tableWidget.setTabKeyNavigation(False)

        # Accent focus delegate (SPEC §4.1)
        self._focus_delegate = _AccentFocusDelegate(self, self.tableWidget)
        self.tableWidget.setItemDelegate(self._focus_delegate)
        self._material_delegate = _MaterialSearchDelegate(
            self,
            self._get_material_names(),
            self.tableWidget,
        )
        self.tableWidget.setItemDelegateForColumn(
            self.connector.COL_MATERIAL, self._material_delegate
        )

        self.layout.addWidget(self.tableWidget)

        self.buttonLayout = QHBoxLayout()
        self.btnAddSurface = QPushButton("Add Surface")
        self.btnAddSurface.setToolTip(
            "Add a new surface after the current selection (Insert)"
        )
        self.btnRemoveSurface = QPushButton("Remove Surface")
        self.btnRemoveSurface.setToolTip(
            "Remove the currently selected surface (Delete)"
        )
        self.buttonLayout.addWidget(self.btnAddSurface)
        self.buttonLayout.addWidget(self.btnRemoveSurface)
        self.layout.addLayout(self.buttonLayout)

    def connect_signals(self):
        self.btnAddSurface.clicked.connect(self.add_surface_handler)
        self.btnRemoveSurface.clicked.connect(self.remove_surface_handler)
        self.tableWidget.itemChanged.connect(self.on_item_changed_handler)
        self.tableWidget.customContextMenuRequested.connect(self.show_context_menu)
        self.tableWidget.itemSelectionChanged.connect(self.update_headers_on_selection)
        self.connector.opticLoaded.connect(self.full_refresh_from_optic)
        self.connector.opticChanged.connect(self.full_refresh_from_optic)
        self.connector.optimizationVariablesChanged.connect(
            self.full_refresh_from_optic
        )

    def setup_table(self):
        self.tableWidget.blockSignals(True)
        self.tableWidget.setColumnCount(len(self.connector.get_column_headers()))
        self.tableWidget.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        # Prevent excessive column resizing
        self.tableWidget.horizontalHeader().setMinimumSectionSize(60)
        self.tableWidget.horizontalHeader().setMaximumSectionSize(200)
        self.tableWidget.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Interactive
        )

        # Prevent excessive row resizing
        self.tableWidget.verticalHeader().setMinimumSectionSize(30)
        self.tableWidget.verticalHeader().setMaximumSectionSize(70)
        self.tableWidget.verticalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Interactive
        )
        self.tableWidget.verticalHeader().setDefaultSectionSize(30)
        self.tableWidget.blockSignals(False)

    def eventFilter(self, source, event):
        if event.type() == QEvent.KeyPress:
            is_shift_tab = event.key() == Qt.Key_Tab and bool(
                event.modifiers() & Qt.ShiftModifier
            )
            is_table_editor = bool(
                hasattr(source, "property")
                and source.property("lens_table_editor")
            )
            if source is self.tableWidget and event.key() == Qt.Key_Insert:
                self.add_surface_handler()
                return True
            if source is self.tableWidget and event.key() == Qt.Key_Delete:
                self.remove_surface_handler()
                return True
            if source is self.tableWidget and event.key() == Qt.Key_V and event.modifiers() == (
                Qt.ControlModifier | Qt.ShiftModifier
            ):
                self._request_add_optimization_variable()
                return True
            if is_table_editor and event.key() in (Qt.Key_Return, Qt.Key_Enter):
                if self._handle_tab_navigation(source, backwards=False):
                    return True
            if event.key() == Qt.Key_Backtab or event.key() == Qt.Key_Tab:
                backwards = event.key() == Qt.Key_Backtab or is_shift_tab
                if self._handle_tab_navigation(source, backwards):
                    return True
        return super().eventFilter(source, event)

    def _handle_tab_navigation(self, source, backwards: bool) -> bool:
        """Move through editable cells in a predictable row-major order."""
        if self.tableWidget.rowCount() == 0:
            return False

        if self._pending_insert_ui_row is not None and not backwards:
            target = self._first_editable_in_row(self._pending_insert_ui_row)
            self._pending_insert_ui_row = None
            if target is not None:
                self._commit_editor_if_needed(source)
                self._focus_cell_for_editing(*target)
                return True

        row, col = self._get_navigation_origin(source)
        target = self._next_editable_cell(row, col, backwards=backwards)
        if target is None:
            return False

        self._commit_editor_if_needed(source)
        self._focus_cell_for_editing(*target)
        return True

    def _accept_material_completion(self, editor, text: str) -> None:  # noqa: ANN001
        """Accept a material completer choice and continue like a confirmed edit."""
        if not isValid(editor):
            return
        editor.setText(text.strip() or "Air")
        QTimer.singleShot(0, lambda e=editor: self._handle_tab_navigation(e, False))

    def _commit_editor_if_needed(self, source) -> None:  # noqa: ANN001
        """Commit an in-progress edit before moving focus."""
        if hasattr(source, "property") and source.property("lens_table_editor"):
            editor = source.property("lens_parent_editor") or source
            if not isValid(editor):
                return
            row, col = self._get_navigation_origin(source)
            item = self.tableWidget.item(row, col)
            editor_text = editor.text().strip() if hasattr(editor, "text") else None
            fallback_text = (
                (editor_text or "Air")
                if col == self.connector.COL_MATERIAL
                else editor_text
            )
            if item is not None and editor_text is not None:
                if not editor.parent() is self.tableWidget.viewport():
                    item.setText(fallback_text)
                    return
            try:
                self.tableWidget.commitData(editor)
                self.tableWidget.closeEditor(
                    editor, QAbstractItemDelegate.EndEditHint.NoHint
                )
            except (RuntimeError, TypeError):
                if item is not None and editor_text is not None:
                    item.setText(fallback_text)
                return
        elif hasattr(source, "editingFinished"):
            source.editingFinished.emit()

    def _get_navigation_origin(self, source) -> tuple[int, int]:  # noqa: ANN001
        """Return the logical table position to advance from."""
        if hasattr(source, "property"):
            row = source.property("lens_row")
            col = source.property("lens_col")
            if isinstance(row, int) and isinstance(col, int):
                return row, col
        return self.tableWidget.currentRow(), self.tableWidget.currentColumn()

    def _is_properties_row(self, row: int) -> bool:
        return self.open_prop_source_row != -1 and row == self.open_prop_source_row + 1

    def _iter_editable_positions(self) -> list[tuple[int, int]]:
        """Return editable cells from Comment onward, skipping properties rows."""
        positions: list[tuple[int, int]] = []
        for row in range(self.tableWidget.rowCount()):
            if self._is_properties_row(row):
                continue
            for col in range(self.connector.COL_COMMENT, self.tableWidget.columnCount()):
                item = self.tableWidget.item(row, col)
                if item and item.flags() & Qt.ItemFlag.ItemIsEditable:
                    positions.append((row, col))
        return positions

    def _first_editable_in_row(self, row: int) -> tuple[int, int] | None:
        """Return the first editable cell in *row*, preferring Comment."""
        for col in range(self.connector.COL_COMMENT, self.tableWidget.columnCount()):
            item = self.tableWidget.item(row, col)
            if item and item.flags() & Qt.ItemFlag.ItemIsEditable:
                return row, col
        return None

    def _next_editable_cell(
        self, row: int, col: int, backwards: bool = False
    ) -> tuple[int, int] | None:
        """Return the next editable cell and wrap across the whole table."""
        positions = self._iter_editable_positions()
        if not positions:
            return None
        if backwards:
            for position in reversed(positions):
                if position < (row, col):
                    return position
            return positions[-1]

        for position in positions:
            if position > (row, col):
                return position
        return positions[0]

    def _focus_cell_for_editing(self, row: int, col: int) -> None:
        """Focus and open a table cell for editing."""
        item = self.tableWidget.item(row, col)
        if item is None:
            return
        self.tableWidget.setFocus()
        self.tableWidget.setCurrentCell(row, col)
        self.tableWidget.scrollToItem(item, QAbstractItemView.PositionAtCenter)
        self.tableWidget.editItem(item)

    def _request_add_optimization_variable(self) -> None:
        """Emit requestAddOptimizationVariable for the currently focused cell."""
        ui_row = self.tableWidget.currentRow()
        ui_col = self.tableWidget.currentColumn()
        if ui_row < 0:
            return
        surface_index = self.map_ui_row_to_surface_index(ui_row)
        _col_var_type = {
            self.connector.COL_RADIUS: "radius",
            self.connector.COL_THICKNESS: "thickness",
            self.connector.COL_CONIC: "conic",
        }
        suggested_type = _col_var_type.get(ui_col, "radius")
        self.connector.requestAddOptimizationVariable.emit(
            surface_index, suggested_type
        )

    def map_ui_row_to_surface_index(self, ui_row):
        if self.open_prop_source_row != -1 and ui_row > self.open_prop_source_row:
            return ui_row - 1
        return ui_row

    def map_surface_index_to_ui_row(self, surface_index):
        if (
            self.open_prop_source_row != -1
            and surface_index > self.open_prop_source_row
        ):
            return surface_index + 1
        return surface_index

    @Slot()
    def full_refresh_from_optic(self):
        self.load_data()
        self.update_headers_on_selection()
        if self._pending_insert_surface_index is not None:
            self._pending_insert_ui_row = self.map_surface_index_to_ui_row(
                self._pending_insert_surface_index
            )
            self._pending_insert_surface_index = None
            self.tableWidget.setFocus()
            self.tableWidget.setCurrentCell(
                self._pending_insert_ui_row, self.connector.COL_TYPE
            )
            target = self._first_editable_in_row(self._pending_insert_ui_row)
            if target is not None:
                item = self.tableWidget.item(*target)
                if item is not None:
                    self.tableWidget.scrollToItem(
                        item, QAbstractItemView.PositionAtCenter
                    )

    def _process_table_cell(self, row, col_idx, header):
        """Creates and configures the appropriate widget or item for a
        single table cell."""
        if col_idx == self.connector.COL_TYPE:
            type_info = self.connector.get_surface_type_info(row)
            params = self.connector.get_surface_geometry_params(row)
            type_info["has_extra_params"] = bool(params)

            widget = SurfaceTypeWidget(row, type_info, self.connector)
            widget.surfaceTypeChanged.connect(
                lambda nt, r=row: self.connector.set_surface_type(r, nt)
            )
            widget.propertiesIconClicked.connect(
                lambda r=row: self.toggle_properties_widget(r)
            )
            widget.type_edit.setProperty("lens_row", row)
            widget.type_edit.setProperty("lens_col", col_idx)
            widget.type_edit.installEventFilter(self)
            self.tableWidget.setCellWidget(row, col_idx, widget)

            # Badge for non-standard variable types (asphere_coeff, index, …)
            _standard_types = {"radius", "thickness", "conic"}
            extra_var_types = [
                vd["type"]
                for vd in self.connector.get_optimization_variables()
                if vd.get("surface_number") == row
                and vd.get("type") not in _standard_types
            ]
            widget.setHasVariables(extra_var_types)
        else:
            item_data = self.connector.get_surface_data(row, col_idx)
            item = QTableWidgetItem(str(item_data) if item_data is not None else "")

            # Determine if the cell should be editable
            num_surfaces = self.connector.get_surface_count()
            is_obj_or_img = row == 0 or row == num_surfaces - 1
            is_non_editable_header = header in [
                "Radius",
                "Thickness",
                "Material",
                "Conic",
                "Semi-Diameter",
            ]
            is_last_thickness = row == num_surfaces - 1 and header == "Thickness"

            if (is_obj_or_img and is_non_editable_header) or is_last_thickness:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)

            # Highlight cells that are registered optimization variables
            _col_var_type = {
                self.connector.COL_RADIUS: "radius",
                self.connector.COL_THICKNESS: "thickness",
                self.connector.COL_CONIC: "conic",
            }
            if col_idx in _col_var_type:
                vtype = _col_var_type[col_idx]
                for vd in self.connector.get_optimization_variables():
                    if vd.get("surface_number") == row and vd.get("type") == vtype:
                        item.setBackground(QBrush(QColor(100, 150, 255, 80)))
                        item.setToolTip(
                            f"Variable: min={vd.get('min_val')}, "
                            f"max={vd.get('max_val')}"
                        )
                        break

            self.tableWidget.setItem(row, col_idx, item)

    def _process_table_row(self, row_index):
        """Populates a single row in the lens data editor table."""
        self.tableWidget.setVerticalHeaderItem(
            row_index, QTableWidgetItem(str(row_index))
        )
        for col_idx, header in enumerate(self.connector.get_column_headers()):
            self._process_table_cell(row_index, col_idx, header)

    @Slot()
    def load_data(self):
        self.tableWidget.blockSignals(True)
        self.tableWidget.setRowCount(0)
        num_surfaces = self.connector.get_surface_count()
        self.tableWidget.setRowCount(num_surfaces)

        for r in range(num_surfaces):
            self._process_table_row(r)

        if self.open_prop_source_row != -1 and self.open_prop_source_row < num_surfaces:
            self._insert_properties_widget(self.open_prop_source_row)

        self.tableWidget.blockSignals(False)

    def _insert_properties_widget(self, source_row):
        prop_row_index = source_row + 1
        self.tableWidget.insertRow(prop_row_index)
        self.tableWidget.setVerticalHeaderItem(prop_row_index, QTableWidgetItem(""))
        prop_widget = SurfacePropertiesWidget(source_row, self.connector)
        self.tableWidget.setCellWidget(prop_row_index, 0, prop_widget)
        self.tableWidget.setSpan(prop_row_index, 0, 1, self.tableWidget.columnCount())
        default_props_height = 150
        self.tableWidget.setRowHeight(prop_row_index, default_props_height)
        self.tableWidget.verticalHeader().setSectionResizeMode(
            prop_row_index, QHeaderView.ResizeMode.Fixed
        )

    @Slot()
    def update_headers_on_selection(self):
        selected_items = self.tableWidget.selectedItems()
        row = (
            self.tableWidget.currentRow()
            if not selected_items
            else selected_items[0].row()
        )
        surface_index = self.map_ui_row_to_surface_index(row)
        headers = self.connector.get_column_headers(surface_index)
        self.tableWidget.setHorizontalHeaderLabels(headers)

    def _flash_cell(
        self, row: int, col: int, valid: bool, duration_ms: int = 300
    ) -> None:
        """Briefly flash a cell green (valid) or red (invalid) after an edit.

        Args:
            row: Table row index.
            col: Table column index.
            valid: If ``True`` flash green, else red.
            duration_ms: How long the flash lasts in milliseconds.
        """
        item = self.tableWidget.item(row, col)
        if item is None:
            return
        flash_color = QColor(76, 175, 80, 120) if valid else QColor(244, 67, 54, 120)
        original_bg = item.background()

        def set_bg(color):
            self.tableWidget.blockSignals(True)
            item.setBackground(QBrush(color))
            self.tableWidget.blockSignals(False)

        set_bg(flash_color)
        QTimer.singleShot(duration_ms, lambda: set_bg(original_bg))

    @Slot(QTableWidgetItem)
    def on_item_changed_handler(self, item: QTableWidgetItem):
        if not self.tableWidget.signalsBlocked():
            row = item.row()
            col = item.column()
            text = item.text()
            surface_index = self.map_ui_row_to_surface_index(row)
            try:
                self.connector.set_surface_data(surface_index, col, text)
                self._flash_cell(row, col, valid=True)
            except Exception:
                self._flash_cell(row, col, valid=False)

    @Slot()
    def add_surface_handler(self, surface_index_to_add_before=None):
        if surface_index_to_add_before is not None and not isinstance(
            surface_index_to_add_before, bool
        ):
            self._pending_insert_surface_index = surface_index_to_add_before
            self.connector.add_surface(index=surface_index_to_add_before)
        else:
            ui_row = self.tableWidget.currentRow()
            surface_index = self.map_ui_row_to_surface_index(ui_row)
            insert_pos = (
                surface_index + 1
                if ui_row != -1
                else self.connector.get_surface_count() - 1
            )
            self._pending_insert_surface_index = insert_pos
            self.connector.add_surface(index=insert_pos)

    @Slot()
    def remove_surface_handler(self, surface_index_to_remove=None):
        if surface_index_to_remove is None:
            ui_row = self.tableWidget.currentRow()
            if ui_row == -1:
                return
            surface_index_to_remove = self.map_ui_row_to_surface_index(ui_row)

        if self.open_prop_source_row == surface_index_to_remove:
            self.open_prop_source_row = -1  # Close properties if its owner is removed

        self.connector.remove_surface(surface_index_to_remove)

    @Slot()
    def toggle_properties_widget(self, source_row):
        # Check if we're closing the currently open properties
        if self.open_prop_source_row == source_row:
            # Restore interactive resize mode for the rows that were fixed
            if self.open_prop_source_row >= 0:
                # Get the row indices to restore
                row_above = self.open_prop_source_row
                row_below = (
                    self.open_prop_source_row + 2
                )  # +2 because +1 is the properties row

                # Check if these rows exist before changing their mode
                if row_above >= 0 and row_above < self.tableWidget.rowCount():
                    self.tableWidget.verticalHeader().setSectionResizeMode(
                        row_above, QHeaderView.ResizeMode.Interactive
                    )

                if row_below < self.tableWidget.rowCount():
                    self.tableWidget.verticalHeader().setSectionResizeMode(
                        row_below, QHeaderView.ResizeMode.Interactive
                    )

            # close properties widget
            self.open_prop_source_row = -1
        else:
            # open properties widget
            self.open_prop_source_row = source_row

        # Refresh the table
        self.load_data()

        # If opening properties, set the rows around it to fixed mode
        if self.open_prop_source_row >= 0:
            # The row above is the surface row itself
            row_above = self.open_prop_source_row
            # The row below is after the properties row
            row_below = self.open_prop_source_row + 2

            # Set the resize mode to Fixed for these rows
            if row_above >= 0 and row_above < self.tableWidget.rowCount():
                self.tableWidget.verticalHeader().setSectionResizeMode(
                    row_above, QHeaderView.ResizeMode.Fixed
                )

            if row_below < self.tableWidget.rowCount():
                self.tableWidget.verticalHeader().setSectionResizeMode(
                    row_below, QHeaderView.ResizeMode.Fixed
                )

    @Slot("QPoint")
    def show_context_menu(self, pos):
        ui_row = self.tableWidget.rowAt(pos.y())
        if ui_row < 0:
            return

        is_prop_widget_row = (
            self.open_prop_source_row != -1 and ui_row == self.open_prop_source_row + 1
        )

        surface_index = self.map_ui_row_to_surface_index(ui_row)

        menu = QMenu(self)
        menu.setObjectName("LDEContextMenu")

        if not is_prop_widget_row:
            add_above = menu.addAction("Add Surface Above")
            add_above.triggered.connect(lambda: self.add_surface_handler(surface_index))
            remove_action = menu.addAction("Remove Current Surface")
            remove_action.triggered.connect(
                lambda: self.remove_surface_handler(surface_index)
            )
            menu.addSeparator()
            props_action = menu.addAction("Surface Properties")
            props_action.triggered.connect(
                lambda: self.toggle_properties_widget(surface_index)
            )
            editor_action = menu.addAction("Surface Editor (WIP)")
            editor_action.setEnabled(False)

            is_obj_or_img = (surface_index == 0) or (
                surface_index == self.connector.get_surface_count() - 1
            )

            menu.addSeparator()
            make_stop_action = menu.addAction("Make Stop Surface")
            make_stop_action.triggered.connect(
                lambda _=False, si=surface_index: self.connector.set_stop_surface(si)
            )

            if is_obj_or_img:
                if surface_index == 0:
                    add_above.setEnabled(False)
                remove_action.setEnabled(False)
                props_action.setEnabled(False)
                make_stop_action.setEnabled(False)

            menu.addSeparator()
            ui_col = self.tableWidget.columnAt(pos.x())
            _col_var_type = {
                self.connector.COL_RADIUS: "radius",
                self.connector.COL_THICKNESS: "thickness",
                self.connector.COL_CONIC: "conic",
            }
            suggested_type = _col_var_type.get(ui_col, "radius")
            add_var_action = menu.addAction(
                "Add as Optimization Variable...  Ctrl+Shift+V"
            )
            add_var_action.triggered.connect(
                lambda _=False, si=surface_index, st=suggested_type: (
                    self.connector.requestAddOptimizationVariable.emit(si, st)
                )
            )
            if is_obj_or_img:
                add_var_action.setEnabled(False)

        menu.exec(self.tableWidget.viewport().mapToGlobal(pos))
