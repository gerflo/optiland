"""Defines the LensEditor widget for displaying and editing optical system data.

This module contains the `LensEditor` class, a QWidget that provides a spreadsheet-like
interface (QTableWidget) for modifying the properties of an optical system's surfaces,
such as radius, thickness, and material.

Author: Manuel Fragata Mendes, 2025
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, QSettings, QSize, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QBrush, QColor, QIcon, QKeySequence, QPainter, QPen, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemDelegate,
    QAbstractItemView,
    QApplication,
    QComboBox,
    QCompleter,
    QFrame,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QSizePolicy,
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
from .config import APPLICATION_NAME, ORGANIZATION_NAME

if TYPE_CHECKING:
    from .optiland_connector import OptilandConnector


class SurfacePropertiesWidget(QWidget):
    """A widget to display and edit specific parameters of a surface geometry."""

    def __init__(self, row, connector, parent=None):
        super().__init__(parent)
        self.row = row
        self.connector = connector
        self.setObjectName("SurfacePropertiesWidget")
        self.setMinimumWidth(0)
        self.setMinimumHeight(0)
        self.setMaximumHeight(900)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setStyleSheet(
            "QWidget#SurfacePropertiesWidget {"
            "  background: rgba(255, 255, 255, 0.02);"
            "}"
            "QFrame[section='true'] {"
            "  border: 1px solid rgba(255, 255, 255, 0.12);"
            "  border-radius: 6px;"
            "  background: rgba(255, 255, 255, 0.03);"
            "}"
            "QLabel[sectionTitle='true'] {"
            "  font-weight: bold;"
            "}"
            "QLabel[hint='true'] {"
            "  color: rgba(255, 255, 255, 0.72);"
            "}"
        )

        self.input_widgets = {}
        self.aperture_type_combo: QComboBox | None = None
        self.aperture_inputs: dict[str, QLineEdit] = {}
        self._aperture_form_layout: QFormLayout | None = None
        self._aperture_labels: dict[str, QLabel] = {}
        self._populate_properties_form()

    def preferred_height_for_width(self, width: int) -> int:
        """Return the preferred widget height for a constrained width."""
        target_width = max(320, int(width))
        self.setFixedWidth(target_width)
        layout = self.layout()
        if layout is not None:
            layout.activate()
            hint = layout.sizeHint().height()
        else:
            hint = self.sizeHint().height()
        self.setMaximumWidth(target_width)
        return max(140, hint + 16)

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
        main_layout.setContentsMargins(12, 10, 12, 10)
        main_layout.setSpacing(10)
        self._add_aperture_form(main_layout)
        self._add_geometry_form(main_layout)

    def _create_aperture_input(self, value: float) -> QLineEdit:
        """Create a compact numeric line edit for aperture settings."""
        line_edit = QLineEdit()
        line_edit.setFixedWidth(90)
        line_edit.setText(f"{value:.4f}")
        line_edit.editingFinished.connect(self.apply_changes)
        return line_edit

    def _add_aperture_form(self, main_layout: QVBoxLayout) -> None:
        """Append physical aperture controls to the properties widget."""
        config = self.connector.get_surface_aperture_config(self.row)
        section = QFrame()
        section.setProperty("section", True)
        section_layout = QVBoxLayout(section)
        section_layout.setContentsMargins(12, 10, 12, 10)
        section_layout.setSpacing(6)

        title = QLabel("Physical Aperture")
        title.setProperty("sectionTitle", True)
        hint = QLabel(
            "Choose the aperture type and edit only the relevant dimensions."
        )
        hint.setProperty("hint", True)
        section_layout.addWidget(title)
        section_layout.addWidget(hint)

        self._aperture_form_layout = QFormLayout()
        self._aperture_form_layout.setHorizontalSpacing(12)
        self._aperture_form_layout.setVerticalSpacing(6)
        self._aperture_form_layout.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.FieldsStayAtSizeHint
        )
        self._aperture_form_layout.setFormAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )
        self._aperture_form_layout.setLabelAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        section_layout.addLayout(self._aperture_form_layout)

        self.aperture_type_combo = QComboBox()
        self.aperture_type_combo.setFixedWidth(180)
        self.aperture_type_combo.addItems(
            [
                "None",
                "Circular Aperture",
                "Circular Mask",
                "Annular Aperture",
                "Annular Mask",
            ]
        )
        type_map = {
            "none": "None",
            "circular": "Circular Aperture",
            "circular_aperture": "Circular Aperture",
            "annular": "Annular Aperture",
            "ring_aperture": "Annular Aperture",
            "circular_mask": "Circular Mask",
            "ring_mask": "Annular Mask",
        }
        self.aperture_type_combo.setCurrentText(
            type_map.get(str(config.get("type", "none")).lower(), "None")
        )
        self.aperture_type_combo.currentTextChanged.connect(self._refresh_aperture_ui)
        self.aperture_type_combo.currentTextChanged.connect(self._handle_aperture_type_changed)
        self._aperture_form_layout.addRow("Aperture Type:", self.aperture_type_combo)

        self.aperture_inputs = {
            "outer_radius": self._create_aperture_input(
                float(config.get("outer_radius", 0.0) or 0.0)
            ),
            "inner_radius": self._create_aperture_input(
                float(config.get("inner_radius", 0.0) or 0.0)
            ),
            "clear_radius": self._create_aperture_input(
                float(config.get("clear_radius", config.get("outer_radius", 0.0)) or 0.0)
            ),
        }
        for label_text, key in (
            ("Outer Radius:", "outer_radius"),
            ("Inner Radius:", "inner_radius"),
            ("Clear Radius:", "clear_radius"),
        ):
            label = QLabel(label_text)
            self._aperture_labels[key] = label
            self._aperture_form_layout.addRow(label, self.aperture_inputs[key])
        main_layout.addWidget(section)
        self._refresh_aperture_ui()

    def _add_geometry_form(self, main_layout: QVBoxLayout) -> None:
        """Append geometry-specific parameters below the aperture section."""
        section = QFrame()
        section.setProperty("section", True)
        section_layout = QVBoxLayout(section)
        section_layout.setContentsMargins(12, 10, 12, 10)
        section_layout.setSpacing(6)

        title = QLabel("Surface Geometry")
        title.setProperty("sectionTitle", True)
        section_layout.addWidget(title)

        params = self.connector.get_surface_geometry_params(self.row)
        if not params:
            hint = QLabel("This surface type has no additional geometry parameters.")
            hint.setProperty("hint", True)
            section_layout.addWidget(hint)
            main_layout.addWidget(section)
            return

        columns_layout = QHBoxLayout()
        columns_layout.setSpacing(16)
        columns_layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        items_per_column = 2
        param_items = list(params.items())
        num_columns = (len(param_items) + items_per_column - 1) // items_per_column

        for col in range(num_columns):
            form_layout = QFormLayout()
            form_layout.setHorizontalSpacing(12)
            form_layout.setVerticalSpacing(6)
            form_layout.setFieldGrowthPolicy(
                QFormLayout.FieldGrowthPolicy.FieldsStayAtSizeHint
            )
            form_layout.setFormAlignment(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
            )
            form_layout.setLabelAlignment(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            )

            start_idx = col * items_per_column
            end_idx = min((col + 1) * items_per_column, len(param_items))

            for i in range(start_idx, end_idx):
                name, value = param_items[i]
                label_text = name + ":"
                line_edit = self._create_parameter_input(name, value)
                form_layout.addRow(label_text, line_edit)

            columns_layout.addLayout(form_layout)

        columns_layout.addStretch(1)
        section_layout.addLayout(columns_layout)
        main_layout.addWidget(section)

    def _refresh_aperture_ui(self) -> None:
        """Show only the aperture fields relevant to the selected type."""
        if self.aperture_type_combo is None or self._aperture_form_layout is None:
            return
        aperture_type = self.aperture_type_combo.currentText()
        visible = {
            "outer_radius": aperture_type in {
                "Circular Aperture",
                "Circular Mask",
                "Annular Aperture",
                "Annular Mask",
            },
            "inner_radius": aperture_type in {"Annular Aperture", "Annular Mask"},
            "clear_radius": aperture_type in {"Circular Mask", "Annular Mask"},
        }
        label_texts = {
            "outer_radius": (
                "Radius:"
                if aperture_type == "Circular Aperture"
                else "Mask Radius:"
                if aperture_type == "Circular Mask"
                else "Outer Radius:"
            ),
            "inner_radius": "Inner Radius:",
            "clear_radius": "Clear Radius:",
        }
        for key, is_visible in visible.items():
            widget = self.aperture_inputs[key]
            widget.setVisible(is_visible)
            label = self._aperture_labels.get(key)
            if label is not None:
                label.setText(label_texts[key])
                label.setVisible(is_visible)

    def _handle_aperture_type_changed(self) -> None:
        """Seed sensible defaults before applying a newly selected aperture type."""
        if self.aperture_type_combo is None:
            return
        aperture_type = self.aperture_type_combo.currentText()
        outer_text = self.aperture_inputs["outer_radius"].text().strip()
        inner_text = self.aperture_inputs["inner_radius"].text().strip()
        clear_text = self.aperture_inputs["clear_radius"].text().strip()

        if aperture_type != "None":
            try:
                outer_value = float(outer_text or "0")
            except ValueError:
                outer_value = 0.0
            if outer_value <= 0:
                self.aperture_inputs["outer_radius"].setText("1.0000")

        if aperture_type in {"Annular Aperture", "Annular Mask"}:
            try:
                inner_value = float(inner_text or "0")
            except ValueError:
                inner_value = 0.0
            if inner_value <= 0:
                try:
                    outer_value = float(self.aperture_inputs["outer_radius"].text() or "1")
                except ValueError:
                    outer_value = 1.0
                seeded_inner = max(0.1, min(outer_value * 0.25, outer_value - 0.1))
                self.aperture_inputs["inner_radius"].setText(f"{seeded_inner:.4f}")
        else:
            self.aperture_inputs["inner_radius"].setText("0.0000")

        if aperture_type in {"Circular Mask", "Annular Mask"}:
            try:
                clear_value = float(clear_text or "0")
            except ValueError:
                clear_value = 0.0
            try:
                outer_value = float(self.aperture_inputs["outer_radius"].text() or "0")
            except ValueError:
                outer_value = 0.0
            if clear_value < outer_value or clear_value <= 0:
                seeded_clear = max(outer_value + 0.1, outer_value * 1.25, 1.0)
                self.aperture_inputs["clear_radius"].setText(f"{seeded_clear:.4f}")
        else:
            self.aperture_inputs["clear_radius"].setText(
                self.aperture_inputs["outer_radius"].text()
            )

        self.apply_changes()

    @Slot()
    def apply_changes(self):
        """Collects data from input fields and sends it to the connector."""
        if self.input_widgets:
            params_to_set = {}
            for name, widget in self.input_widgets.items():
                params_to_set[name] = widget.text()
            self.connector.set_surface_geometry_params(self.row, params_to_set)
        if self.aperture_type_combo is None:
            return
        reverse_type_map = {
            "None": "none",
            "Circular Aperture": "circular_aperture",
            "Circular Mask": "circular_mask",
            "Annular Aperture": "ring_aperture",
            "Annular Mask": "ring_mask",
        }
        selected_type = self.aperture_type_combo.currentText()
        if selected_type in {"Circular Aperture", "Annular Aperture"}:
            self.aperture_inputs["clear_radius"].setText(
                self.aperture_inputs["outer_radius"].text()
            )
        try:
            self.connector.set_surface_aperture_config(
                self.row,
                {
                    "type": reverse_type_map[selected_type],
                    "outer_radius": self.aperture_inputs["outer_radius"].text(),
                    "inner_radius": self.aperture_inputs["inner_radius"].text(),
                    "clear_radius": self.aperture_inputs["clear_radius"].text(),
                },
            )
        except ValueError:
            return


class SurfaceTypeWidget(QWidget):
    """A custom widget for the 'Type' column, allowing text edit and dropdown."""

    surfaceTypeChanged = Signal(str)
    propertiesIconClicked = Signal()

    def __init__(self, row, current_type_info, connector, parent=None):
        super().__init__(parent)
        self.row = row
        self.connector = connector
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(2)
        self.setObjectName("SurfaceTypeCell")
        self.setStyleSheet(
            "QWidget#SurfaceTypeCell {"
            "  border: 1px solid transparent;"
            "  border-radius: 3px;"
            "  background: transparent;"
            "}"
            "QWidget#SurfaceTypeCell[currentCell='true'] {"
            "  border: 2px solid #FFD166;"
            "  background: rgba(255, 209, 102, 0.22);"
            "}"
            "QLineEdit#SurfaceTypeLineEdit {"
            "  border: none;"
            "  margin: 0px;"
            "  padding: 0px 4px;"
            "  background: transparent;"
            "}"
            "QToolButton#SurfaceTypeButton {"
            "  border: none;"
            "  margin: 0px;"
            "  padding: 0px;"
            "}"
            "QToolButton#SurfaceTypeButton::menu-indicator {"
            "  image: none;"
            "  width: 0px;"
            "}"
        )
        self.type_button = QToolButton()
        self.type_button.setObjectName("SurfaceTypeButton")
        self.type_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.type_button.setAutoRaise(True)
        self.type_button.setArrowType(Qt.DownArrow)
        self.type_button.setContextMenuPolicy(Qt.PreventContextMenu)

        # properties button
        self.props_button = QToolButton()
        self.props_button.setObjectName("PropertiesButton")
        self.props_button.setIcon(QIcon(":/icons/dark/tool.svg"))
        self.props_button.setIconSize(QSize(16, 16))
        self.props_button.setToolTip("Show/Hide Surface Properties")
        self.props_button.clicked.connect(self.propertiesIconClicked.emit)
        self.props_button.setContextMenuPolicy(Qt.PreventContextMenu)
        self.layout.addWidget(self.props_button)

        # hide the button if there are no properties to show
        if not current_type_info.get("has_extra_params", False):
            self.props_button.hide()

        self.type_edit = QLineEdit(current_type_info["display_text"])
        self.type_edit.setObjectName("SurfaceTypeLineEdit")
        self.type_edit.setFrame(False)
        self.type_edit.setTextMargins(0, 0, 0, 0)
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

    def setCurrentCellState(self, active: bool) -> None:
        """Highlight this embedded widget when it is the active table cell."""
        self.setProperty("currentCell", active)
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

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

    _ACCENT = QColor("#FFD166")
    _FILL = QColor(255, 209, 102, 80)

    def __init__(self, owner, parent=None):
        super().__init__(parent)
        self._owner = owner

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index,
    ) -> None:
        active_row, active_col = self._owner._active_cell
        if active_row == index.row() and active_col == index.column():
            active_option = QStyleOptionViewItem(option)
            active_option.backgroundBrush = self._FILL
            super().paint(painter, active_option, index)
            painter.save()
            pen = QPen(self._ACCENT, 2)
            painter.setPen(pen)
            painter.drawRect(option.rect.adjusted(1, 1, -2, -2))
            painter.restore()
            return
        super().paint(painter, option, index)

    def createEditor(self, parent, option, index):  # noqa: ANN001
        """Install custom tab navigation on transient table editors."""
        editor = super().createEditor(parent, option, index)
        if editor is not None:
            editor.setProperty("lens_row", index.row())
            editor.setProperty("lens_col", index.column())
            editor.setProperty("lens_table_editor", True)
            if hasattr(editor, "setFrame"):
                editor.setFrame(False)
            if hasattr(editor, "setTextMargins"):
                editor.setTextMargins(0, 0, 0, 0)
            editor.installEventFilter(self._owner)
        return editor

    def updateEditorGeometry(self, editor, option, index) -> None:  # noqa: ANN001
        """Make inline editors fill the cell instead of sitting inset inside it."""
        del index
        editor.setGeometry(option.rect.adjusted(1, 1, -1, -1))


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
    TABLE_SETTINGS_PREFIX = "LensEditor/Table"

    def __init__(self, connector: OptilandConnector, parent=None):
        super().__init__(parent)
        self.connector = connector
        self.settings = QSettings(ORGANIZATION_NAME, APPLICATION_NAME)
        self.setWindowTitle("Lens Editor")
        self.open_prop_source_row = -1
        self._pending_insert_surface_index: int | None = None
        self._pending_insert_ui_row: int | None = None
        self._active_cell: tuple[int, int] = (-1, -1)
        self._restoring_table_state = False

        self._init_ui()
        self.setup_table()
        self._restore_table_state()
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
        self.tableWidget.viewport().installEventFilter(self)
        self.tableWidget.setContextMenuPolicy(Qt.CustomContextMenu)

        # ScrollPerPixel for smooth scrolling (SPEC §4.6)
        self.tableWidget.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.tableWidget.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.tableWidget.setTabKeyNavigation(False)
        self.copy_cell_shortcut = QShortcut(QKeySequence.Copy, self.tableWidget)
        self.copy_insert_shortcut = QShortcut(
            QKeySequence("Ctrl+Insert"), self.tableWidget
        )
        self.copy_insert_viewport_shortcut = QShortcut(
            QKeySequence("Ctrl+Insert"), self.tableWidget.viewport()
        )
        self.cut_shortcut = QShortcut(QKeySequence.Cut, self.tableWidget)
        self.paste_shortcut = QShortcut(QKeySequence.Paste, self.tableWidget)
        self.paste_insert_shortcut = QShortcut(
            QKeySequence("Shift+Insert"), self.tableWidget
        )
        self.paste_insert_viewport_shortcut = QShortcut(
            QKeySequence("Shift+Insert"), self.tableWidget.viewport()
        )
        self.copy_cell_shortcut.setContext(
            Qt.ShortcutContext.WidgetWithChildrenShortcut
        )
        self.copy_insert_shortcut.setContext(
            Qt.ShortcutContext.WidgetWithChildrenShortcut
        )
        self.copy_insert_viewport_shortcut.setContext(
            Qt.ShortcutContext.WidgetWithChildrenShortcut
        )
        self.cut_shortcut.setContext(
            Qt.ShortcutContext.WidgetWithChildrenShortcut
        )
        self.paste_shortcut.setContext(
            Qt.ShortcutContext.WidgetWithChildrenShortcut
        )
        self.paste_insert_shortcut.setContext(
            Qt.ShortcutContext.WidgetWithChildrenShortcut
        )
        self.paste_insert_viewport_shortcut.setContext(
            Qt.ShortcutContext.WidgetWithChildrenShortcut
        )

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
        self.copy_cell_shortcut.activated.connect(self._copy_current_cell_to_clipboard)
        self.copy_insert_shortcut.activated.connect(
            self._copy_current_cell_to_clipboard
        )
        self.copy_insert_viewport_shortcut.activated.connect(
            self._copy_current_cell_to_clipboard
        )
        self.cut_shortcut.activated.connect(self._cut_current_cell_to_clipboard)
        self.paste_shortcut.activated.connect(self._paste_clipboard_into_current_cell)
        self.paste_insert_shortcut.activated.connect(
            self._paste_clipboard_into_current_cell
        )
        self.paste_insert_viewport_shortcut.activated.connect(
            self._paste_clipboard_into_current_cell
        )
        self.tableWidget.itemChanged.connect(self.on_item_changed_handler)
        self.tableWidget.cellPressed.connect(self._remember_active_cell)
        self.tableWidget.cellClicked.connect(self._remember_active_cell)
        self.tableWidget.customContextMenuRequested.connect(self.show_context_menu)
        self.tableWidget.itemSelectionChanged.connect(self.update_headers_on_selection)
        self.tableWidget.currentCellChanged.connect(self._sync_current_cell_highlight)
        self.tableWidget.horizontalHeader().sectionResized.connect(self._save_table_state)
        self.tableWidget.horizontalHeader().sectionMoved.connect(self._save_table_state)
        app = QApplication.instance()
        if app is not None:
            app.focusChanged.connect(self._handle_application_focus_changed)
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
        # The properties expander lives inside a dedicated table row and may
        # need substantially more height than regular data rows.
        self.tableWidget.verticalHeader().setMaximumSectionSize(2000)
        self.tableWidget.verticalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Interactive
        )
        self.tableWidget.verticalHeader().setDefaultSectionSize(30)
        self.tableWidget.blockSignals(False)

    def _settings_key(self, suffix: str) -> str:
        """Build a stable settings key for persisted lens-editor table state."""
        return f"{self.TABLE_SETTINGS_PREFIX}/{suffix}"

    def _restore_table_state(self) -> None:
        """Restore saved lens-editor header widths/order when available."""
        self._restoring_table_state = True
        try:
            header = self.tableWidget.horizontalHeader()
            header_state = self.settings.value(self._settings_key("HeaderState"))
            if isinstance(header_state, bytes):
                header.restoreState(header_state)
            elif header_state is not None and hasattr(header_state, "data"):
                header.restoreState(header_state)
        finally:
            self._restoring_table_state = False

    def _save_table_state(self, *args) -> None:  # noqa: ANN002
        """Persist current lens-editor header widths/order."""
        if self._restoring_table_state:
            return
        header = self.tableWidget.horizontalHeader()
        self.settings.setValue(self._settings_key("HeaderState"), header.saveState())

    def eventFilter(self, source, event):
        if source is self.tableWidget.viewport() and event.type() == QEvent.Resize:
            self._update_properties_widget_geometry()
            return False
        if source is self.tableWidget.viewport() and event.type() == QEvent.MouseButtonPress:
            pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
            item = self.tableWidget.itemAt(pos)
            if item is not None:
                self.tableWidget.setCurrentItem(item)
                self._remember_active_cell(item.row(), item.column())
            return False
        if event.type() == QEvent.ContextMenu and hasattr(source, "property"):
            row = source.property("lens_row")
            col = source.property("lens_col")
            if isinstance(row, int) and isinstance(col, int):
                self.tableWidget.setCurrentCell(row, col)
                global_pos = event.globalPos()
                local_pos = self.tableWidget.viewport().mapFromGlobal(global_pos)
                self.show_context_menu(local_pos)
                return True
        if event.type() in (QEvent.KeyPress, QEvent.ShortcutOverride):
            is_key_press = event.type() == QEvent.KeyPress
            is_shift_tab = event.key() == Qt.Key_Tab and bool(
                event.modifiers() & Qt.ShiftModifier
            )
            has_ctrl = bool(event.modifiers() & Qt.ControlModifier)
            has_shift = bool(event.modifiers() & Qt.ShiftModifier)
            is_table_focus_target = self._is_within_table(source)
            is_table_editor = bool(
                hasattr(source, "property")
                and source.property("lens_table_editor")
            )
            is_text_input = isinstance(source, QLineEdit)
            if (
                is_text_input
                and (
                    (has_ctrl and event.key() in (Qt.Key_C, Qt.Key_V, Qt.Key_X, Qt.Key_Insert))
                    or (has_shift and event.key() == Qt.Key_Insert)
                )
            ):
                return False
            if (
                has_ctrl
                and event.key() in (Qt.Key_C, Qt.Key_Insert)
                and (
                    is_table_focus_target
                    or (is_table_editor and not is_text_input)
                    or isinstance(source, SurfaceTypeWidget)
                )
            ):
                self._copy_current_cell_to_clipboard()
                return True
            if (
                has_ctrl
                and event.key() == Qt.Key_X
                and (
                    is_table_focus_target
                    or (is_table_editor and not is_text_input)
                    or isinstance(source, SurfaceTypeWidget)
                )
            ):
                self._cut_current_cell_to_clipboard()
                return True
            if (
                (
                    event.key() == Qt.Key_V
                    and has_ctrl
                )
                or (
                    event.key() == Qt.Key_Insert
                    and has_shift
                )
            ) and (
                is_table_focus_target
                or (is_table_editor and not is_text_input)
                or isinstance(source, SurfaceTypeWidget)
            ):
                self._paste_clipboard_into_current_cell()
                return True
            if is_key_press and is_table_focus_target and event.key() == Qt.Key_Insert:
                self.add_surface_handler()
                return True
            if is_key_press and is_table_focus_target and event.key() == Qt.Key_Delete:
                self.remove_surface_handler()
                return True
            if is_key_press and is_table_focus_target and event.key() == Qt.Key_V and event.modifiers() == (
                Qt.ControlModifier | Qt.ShiftModifier
            ):
                self._request_add_optimization_variable()
                return True
            if is_key_press and is_table_editor and event.key() in (Qt.Key_Return, Qt.Key_Enter):
                if self._handle_tab_navigation(source, backwards=False):
                    return True
            if (
                is_key_press
                and
                not is_table_editor
                and event.key()
                in (
                    Qt.Key_Left,
                    Qt.Key_Right,
                    Qt.Key_Up,
                    Qt.Key_Down,
                    Qt.Key_Home,
                    Qt.Key_End,
                    Qt.Key_PageUp,
                    Qt.Key_PageDown,
                )
            ):
                if self._handle_directional_navigation(source, event.key()):
                    return True
            if is_key_press and (event.key() == Qt.Key_Backtab or event.key() == Qt.Key_Tab):
                backwards = event.key() == Qt.Key_Backtab or is_shift_tab
                if self._handle_tab_navigation(source, backwards):
                    return True
        return super().eventFilter(source, event)

    @Slot(int, int, int, int)
    def _sync_current_cell_highlight(
        self,
        current_row: int,
        current_col: int,
        previous_row: int,
        previous_col: int,
    ) -> None:
        """Keep widget-backed cells visually highlighted when they are current."""
        active_row, active_col = self._active_cell
        if active_row < 0 or active_col < 0:
            active_row, active_col = current_row, current_col
        for row, col in (
            (previous_row, previous_col),
            (current_row, current_col),
            (active_row, active_col),
        ):
            if row < 0 or col < 0:
                continue
            widget = self.tableWidget.cellWidget(row, col)
            if isinstance(widget, SurfaceTypeWidget):
                widget.setCurrentCellState(row == active_row and col == active_col)
        self.tableWidget.viewport().update()

    @Slot(int, int)
    def _remember_active_cell(self, row: int, col: int) -> None:
        """Remember the exact cell the user interacted with most recently."""
        if row >= 0 and col >= 0:
            self._active_cell = (row, col)
            self.tableWidget.viewport().update()

    def _is_within_table(self, widget) -> bool:  # noqa: ANN001
        """Return whether *widget* belongs to the lens table or one of its children."""
        current = widget
        while current is not None:
            if current is self.tableWidget:
                return True
            parent_getter = getattr(current, "parent", None)
            if not callable(parent_getter):
                break
            current = parent_getter()
        return False

    def _clear_active_cell_highlight(self) -> None:
        """Drop the persistent active-cell state and repaint affected widgets."""
        previous_row, previous_col = self._active_cell
        self._active_cell = (-1, -1)
        self._sync_current_cell_highlight(-1, -1, previous_row, previous_col)

    def _handle_application_focus_changed(self, old, new) -> None:  # noqa: ANN001
        """Keep the current-cell highlight until focus truly leaves the table."""
        if self._is_within_table(new):
            return
        if self._is_within_table(old):
            self._clear_active_cell_highlight()

    def _handle_tab_navigation(self, source, backwards: bool) -> bool:
        """Move through table cells in a predictable row-major order."""
        if self.tableWidget.rowCount() == 0:
            return False

        if self._pending_insert_ui_row is not None and not backwards:
            target = self._first_navigable_in_row(self._pending_insert_ui_row)
            self._pending_insert_ui_row = None
            if target is not None:
                self._commit_editor_if_needed(source)
                self._focus_cell(*target, edit=isinstance(source, QLineEdit))
                return True

        row, col = self._get_navigation_origin(source)
        target = self._next_navigable_cell(row, col, backwards=backwards)
        if target is None:
            return False

        self._commit_editor_if_needed(source)
        self._focus_cell(*target, edit=isinstance(source, QLineEdit))
        return True

    def _handle_directional_navigation(self, source, key: int) -> bool:
        """Move the active-cell highlight with non-text navigation keys."""
        if self.tableWidget.rowCount() == 0 or self.tableWidget.columnCount() == 0:
            return False
        row, col = self._get_navigation_origin(source)
        if row < 0 or col < 0:
            return self._focus_cell(0, 0, edit=False)
        if key == Qt.Key_Left:
            return self._focus_relative(row, col, 0, -1)
        if key == Qt.Key_Right:
            return self._focus_relative(row, col, 0, 1)
        if key == Qt.Key_Up:
            return self._focus_relative(row, col, -1, 0)
        if key == Qt.Key_Down:
            return self._focus_relative(row, col, 1, 0)
        if key == Qt.Key_Home:
            return self._focus_cell(row, 0, edit=False)
        if key == Qt.Key_End:
            return self._focus_cell(row, self.tableWidget.columnCount() - 1, edit=False)
        if key == Qt.Key_PageUp:
            return self._focus_relative(row, col, -self._page_step(), 0)
        if key == Qt.Key_PageDown:
            return self._focus_relative(row, col, self._page_step(), 0)
        return False

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
            if item is not None and fallback_text is not None and item.text() != fallback_text:
                item.setText(fallback_text)
            self.tableWidget.setFocus(Qt.FocusReason.OtherFocusReason)
        elif hasattr(source, "editingFinished"):
            source.editingFinished.emit()

    def _get_navigation_origin(self, source) -> tuple[int, int]:  # noqa: ANN001
        """Return the logical table position to advance from."""
        if hasattr(source, "property"):
            row = source.property("lens_row")
            col = source.property("lens_col")
            if isinstance(row, int) and isinstance(col, int):
                return row, col
        active_row, active_col = self._active_cell
        if active_row >= 0 and active_col >= 0:
            return active_row, active_col
        return self.tableWidget.currentRow(), self.tableWidget.currentColumn()

    def _is_properties_row(self, row: int) -> bool:
        return self.open_prop_source_row != -1 and row == self.open_prop_source_row + 1

    def _iter_navigable_positions(self) -> list[tuple[int, int]]:
        """Return all regular table cells in row-major order."""
        positions: list[tuple[int, int]] = []
        for row in range(self.tableWidget.rowCount()):
            if self._is_properties_row(row):
                continue
            for col in range(self.tableWidget.columnCount()):
                item = self.tableWidget.item(row, col)
                widget = self.tableWidget.cellWidget(row, col)
                if item is not None or widget is not None:
                    positions.append((row, col))
        return positions

    def _first_navigable_in_row(self, row: int) -> tuple[int, int] | None:
        """Return the first visible cell in *row*."""
        for col in range(self.tableWidget.columnCount()):
            item = self.tableWidget.item(row, col)
            widget = self.tableWidget.cellWidget(row, col)
            if item is not None or widget is not None:
                return row, col
        return None

    def _next_navigable_cell(
        self, row: int, col: int, backwards: bool = False
    ) -> tuple[int, int] | None:
        """Return the next visible cell and wrap across the whole table."""
        positions = self._iter_navigable_positions()
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

    def _focus_cell(self, row: int, col: int, *, edit: bool) -> bool:
        """Focus a table cell and optionally open it for editing."""
        if row < 0 or col < 0 or self._is_properties_row(row):
            return False
        item = self.tableWidget.item(row, col)
        widget = self.tableWidget.cellWidget(row, col)
        if item is None and widget is None:
            return False
        self.tableWidget.setFocus()
        if item is not None:
            self.tableWidget.setCurrentItem(item)
            self.tableWidget.scrollToItem(item, QAbstractItemView.PositionAtCenter)
        else:
            self.tableWidget.setCurrentCell(row, col)
        self._remember_active_cell(row, col)
        if edit and item is not None and item.flags() & Qt.ItemFlag.ItemIsEditable:
            self.tableWidget.editItem(item)
        return True

    def _focus_relative(self, row: int, col: int, row_delta: int, col_delta: int) -> bool:
        """Move to a nearby visible cell while clamping to the table bounds."""
        target_row = min(max(0, row + row_delta), self.tableWidget.rowCount() - 1)
        target_col = min(max(0, col + col_delta), self.tableWidget.columnCount() - 1)
        return self._focus_cell(target_row, target_col, edit=False)

    def _page_step(self) -> int:
        row_height = max(1, self.tableWidget.verticalHeader().defaultSectionSize())
        viewport_height = max(1, self.tableWidget.viewport().height())
        return max(1, viewport_height // row_height)

    def _cell_display_text(self, row: int, col: int) -> str:
        """Return the visible text for a table cell, including widget-backed ones."""
        item = self.tableWidget.item(row, col)
        if item is not None:
            return item.text()

        widget = self.tableWidget.cellWidget(row, col)
        if isinstance(widget, SurfaceTypeWidget):
            return widget.type_edit.text()
        if widget is not None and hasattr(widget, "text"):
            try:
                return str(widget.text())
            except TypeError:
                return ""
        return ""

    def _copy_current_cell_to_clipboard(self) -> None:
        """Copy the currently focused cell value to the clipboard."""
        row, col = self._active_cell
        if row < 0 or col < 0:
            row = self.tableWidget.currentRow()
            col = self.tableWidget.currentColumn()
        if row < 0 or col < 0:
            return
        QApplication.clipboard().setText(self._cell_display_text(row, col))

    def _cut_replacement_text(self, row: int, col: int) -> str | None:
        """Return a valid replacement value for Cut on a given cell.

        Table cells in the Lens Editor often represent required numeric fields,
        so writing an empty string can be invalid. This method maps Cut to a
        sensible default per column.
        """
        del row
        defaults = {
            self.connector.COL_COMMENT: "",
            self.connector.COL_RADIUS: "inf",
            self.connector.COL_THICKNESS: "0.0000",
            self.connector.COL_MATERIAL: "Air",
            self.connector.COL_CONIC: "0.0000",
            self.connector.COL_SEMI_DIAMETER: "0.0000",
        }
        return defaults.get(col)

    def _cut_current_cell_to_clipboard(self) -> None:
        """Cut the current cell when editable and copy its prior value."""
        row, col = self._active_cell
        if row < 0 or col < 0:
            row = self.tableWidget.currentRow()
            col = self.tableWidget.currentColumn()
        if row < 0 or col < 0:
            return

        text = self._cell_display_text(row, col)
        if text == "":
            return
        QApplication.clipboard().setText(text)

        widget = self.tableWidget.cellWidget(row, col)
        if isinstance(widget, SurfaceTypeWidget):
            if widget.type_edit.isReadOnly():
                return
            replacement = self._cut_replacement_text(row, col)
            if replacement is None:
                return
            widget.type_edit.setText(replacement)
            widget.text_changed()
            self._remember_active_cell(row, col)
            return

        item = self.tableWidget.item(row, col)
        if item is None or not (item.flags() & Qt.ItemFlag.ItemIsEditable):
            return
        replacement = self._cut_replacement_text(row, col)
        if replacement is None:
            return

        self.tableWidget.blockSignals(True)
        item.setText(replacement)
        self.tableWidget.blockSignals(False)
        self.on_item_changed_handler(item)
        self._remember_active_cell(row, col)

    def _copy_selected_row_to_clipboard(self) -> None:
        """Copy the current row as a tab-separated line."""
        row = self.tableWidget.currentRow()
        if row < 0:
            return
        values = [
            self._cell_display_text(row, col)
            for col in range(self.tableWidget.columnCount())
        ]
        QApplication.clipboard().setText("\t".join(values))

    def _paste_clipboard_into_current_cell(self) -> None:
        """Paste clipboard text into the active editable cell."""
        text = QApplication.clipboard().text()
        if text == "":
            return
        row, col = self._active_cell
        if row < 0 or col < 0:
            row = self.tableWidget.currentRow()
            col = self.tableWidget.currentColumn()
        if row < 0 or col < 0:
            return

        widget = self.tableWidget.cellWidget(row, col)
        if isinstance(widget, SurfaceTypeWidget):
            if widget.type_edit.isReadOnly():
                return
            pasted_type = text.strip().lower()
            if pasted_type in widget.connector.get_available_surface_types():
                widget.type_selected(pasted_type)
            else:
                widget.type_edit.setText(text)
                widget.text_changed()
            self._remember_active_cell(row, col)
            return

        item = self.tableWidget.item(row, col)
        if item is None or not (item.flags() & Qt.ItemFlag.ItemIsEditable):
            return

        self.tableWidget.blockSignals(True)
        item.setText(text)
        self.tableWidget.blockSignals(False)
        self.on_item_changed_handler(item)
        self._remember_active_cell(row, col)

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
            target = self._first_navigable_in_row(self._pending_insert_ui_row)
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
            type_info["has_extra_params"] = bool(params) or type_info["is_changeable"]

            widget = SurfaceTypeWidget(row, type_info, self.connector)
            widget.surfaceTypeChanged.connect(
                lambda nt, r=row: self.connector.set_surface_type(r, nt)
            )
            widget.propertiesIconClicked.connect(
                lambda r=row: self.toggle_properties_widget(r)
            )
            widget.installEventFilter(self)
            widget.type_button.setProperty("lens_row", row)
            widget.type_button.setProperty("lens_col", col_idx)
            widget.type_button.installEventFilter(self)
            widget.props_button.setProperty("lens_row", row)
            widget.props_button.setProperty("lens_col", col_idx)
            widget.props_button.installEventFilter(self)
            widget.type_edit.setProperty("lens_row", row)
            widget.type_edit.setProperty("lens_col", col_idx)
            widget.type_edit.setProperty("lens_table_editor", True)
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
        self._sync_current_cell_highlight(
            self.tableWidget.currentRow(),
            self.tableWidget.currentColumn(),
            -1,
            -1,
        )

    def _insert_properties_widget(self, source_row):
        prop_row_index = source_row + 1
        self.tableWidget.insertRow(prop_row_index)
        self.tableWidget.setVerticalHeaderItem(prop_row_index, QTableWidgetItem(""))
        prop_widget = SurfacePropertiesWidget(source_row, self.connector)
        self.tableWidget.setCellWidget(prop_row_index, 0, prop_widget)
        self.tableWidget.setSpan(prop_row_index, 0, 1, self.tableWidget.columnCount())
        self.tableWidget.verticalHeader().setSectionResizeMode(
            prop_row_index, QHeaderView.ResizeMode.Fixed
        )
        self._update_properties_widget_geometry()

    def _update_properties_widget_geometry(self) -> None:
        """Fit the expanded properties row to the current table width and content."""
        if self.open_prop_source_row < 0:
            return
        prop_row_index = self.open_prop_source_row + 1
        prop_widget = self.tableWidget.cellWidget(prop_row_index, 0)
        if not isinstance(prop_widget, SurfacePropertiesWidget):
            return
        available_width = max(320, self.tableWidget.viewport().width() - 24)
        preferred_height = prop_widget.preferred_height_for_width(available_width)
        self.tableWidget.setRowHeight(prop_row_index, preferred_height)

    @Slot()
    def update_headers_on_selection(self):
        selected_items = self.tableWidget.selectedItems()
        row = (
            self.tableWidget.currentRow()
            if not selected_items
            else selected_items[0].row()
        )
        if self._is_properties_row(row):
            row = self.open_prop_source_row
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
            current_item = self.tableWidget.item(row, col)
            if current_item is None:
                return
            self.tableWidget.blockSignals(True)
            current_item.setBackground(QBrush(color))
            self.tableWidget.blockSignals(False)

        set_bg(flash_color)
        QTimer.singleShot(duration_ms, lambda: set_bg(original_bg))

    @Slot(QTableWidgetItem)
    def on_item_changed_handler(self, item: QTableWidgetItem):
        if not self.tableWidget.signalsBlocked():
            row = item.row()
            col = item.column()
            text = item.text()
            if self._is_properties_row(row):
                return
            if not (item.flags() & Qt.ItemFlag.ItemIsEditable):
                return
            if text == "N/A":
                return
            surface_index = self.map_ui_row_to_surface_index(row)
            if surface_index < 0:
                return
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
            current_item = self.tableWidget.itemAt(pos)
            if current_item is not None:
                self.tableWidget.setCurrentItem(current_item)
            else:
                self.tableWidget.setCurrentCell(ui_row, self.tableWidget.columnAt(pos.x()))

            copy_cell_action = menu.addAction("Copy Cell")
            cut_cell_action = menu.addAction("Cut Cell")
            copy_row_action = menu.addAction("Copy Row")
            paste_cell_action = menu.addAction("Paste Cell")
            menu.addSeparator()
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
            chosen = menu.exec(self.tableWidget.viewport().mapToGlobal(pos))
            if chosen == copy_cell_action:
                self._copy_current_cell_to_clipboard()
            elif chosen == cut_cell_action:
                self._cut_current_cell_to_clipboard()
            elif chosen == copy_row_action:
                self._copy_selected_row_to_clipboard()
            elif chosen == paste_cell_action:
                self._paste_clipboard_into_current_cell()
        else:
            menu.exec(self.tableWidget.viewport().mapToGlobal(pos))
