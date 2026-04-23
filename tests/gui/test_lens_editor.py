"""Tests for LensEditor variable highlighting and SurfaceTypeWidget badge."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QLineEdit


@pytest.fixture()
def mock_connector(minimal_optic, qapp):
    conn = MagicMock()
    conn._optic = minimal_optic
    conn.toast_manager = MagicMock()
    conn.COL_TYPE = 0
    conn.COL_COMMENT = 1
    conn.COL_RADIUS = 2
    conn.COL_THICKNESS = 3
    conn.COL_MATERIAL = 4
    conn.COL_CONIC = 5
    conn.COL_SEMI_DIAMETER = 6
    conn.get_column_headers.return_value = [
        "Type", "Comment", "Radius", "Thickness", "Material", "Conic", "Semi-Diameter"
    ]
    conn.get_surface_count.return_value = 4
    conn.get_optimization_variables.return_value = []
    conn.get_surface_type_info.return_value = {
        "display_text": "Standard",
        "is_changeable": True,
        "has_extra_params": False,
    }
    conn.get_surface_geometry_params.return_value = {}
    conn.get_surface_aperture_config.return_value = {"type": "none"}
    conn.get_surface_data.return_value = ""
    conn.get_available_surface_types.return_value = ["standard", "aspheric"]
    return conn


class TestSurfaceTypeWidgetBadge:
    def _make_widget(self, mock_connector):
        from optiland_gui.lens_editor import SurfaceTypeWidget

        type_info = {
            "display_text": "Standard",
            "is_changeable": True,
            "has_extra_params": False,
        }
        return SurfaceTypeWidget(1, type_info, mock_connector)

    def test_badge_hidden_by_default(self, qapp, mock_connector):
        w = self._make_widget(mock_connector)
        # isHidden() checks only the widget's own flag (parent need not be shown)
        assert w._var_badge.isHidden()

    def test_badge_shown_when_variables_set(self, qapp, mock_connector):
        w = self._make_widget(mock_connector)
        w.setHasVariables(["asphere_coeff"])
        assert not w._var_badge.isHidden()
        assert "asphere_coeff" in w._var_badge.toolTip()

    def test_badge_hidden_again_when_cleared(self, qapp, mock_connector):
        w = self._make_widget(mock_connector)
        w.setHasVariables(["asphere_coeff"])
        w.setHasVariables([])
        assert w._var_badge.isHidden()


class TestLensEditorVariableHighlighting:
    def test_no_highlight_when_no_variables(self, qapp, mock_connector):
        from PySide6.QtGui import QColor

        from optiland_gui.lens_editor import LensEditor

        mock_connector.get_optimization_variables.return_value = []
        editor = LensEditor(mock_connector)
        editor.load_data()

        # The highlight color used for variables is (100, 150, 255, 80).
        highlight = QColor(100, 150, 255, 80)
        item = editor.tableWidget.item(1, mock_connector.COL_RADIUS)
        if item is not None:
            bg = item.background().color()
            assert bg != highlight

    def test_radius_variable_highlights_radius_cell(self, qapp, mock_connector):
        from PySide6.QtGui import QColor

        from optiland_gui.lens_editor import LensEditor

        mock_connector.get_optimization_variables.return_value = [
            {"surface_number": 1, "type": "radius", "min_val": None, "max_val": None}
        ]
        editor = LensEditor(mock_connector)
        editor.load_data()

        item = editor.tableWidget.item(1, mock_connector.COL_RADIUS)
        assert item is not None
        # Blue highlight (100, 150, 255, 80) must be set
        expected = QColor(100, 150, 255, 80)
        assert item.background().color() == expected

    def test_asphere_variable_shows_badge_on_type_column(self, qapp, mock_connector):
        from optiland_gui.lens_editor import LensEditor, SurfaceTypeWidget

        mock_connector.get_optimization_variables.return_value = [
            {
                "surface_number": 1,
                "type": "asphere_coeff",
                "min_val": None,
                "max_val": None,
                "coeff_number": 0,
            }
        ]
        editor = LensEditor(mock_connector)
        editor.load_data()

        widget = editor.tableWidget.cellWidget(1, mock_connector.COL_TYPE)
        assert isinstance(widget, SurfaceTypeWidget)
        # isHidden() checks the widget's own flag — no need for parent to be shown
        assert not widget._var_badge.isHidden()


def test_lens_editor_copy_shortcuts_copy_widget_cell_and_row(qapp, mock_connector):
    from optiland_gui.lens_editor import LensEditor

    mock_connector.get_surface_data.side_effect = (
        lambda row, col: {
            mock_connector.COL_COMMENT: f"Comment {row}",
            mock_connector.COL_RADIUS: f"{row}.0",
            mock_connector.COL_THICKNESS: f"{row + 1}.0",
            mock_connector.COL_MATERIAL: "BK7",
            mock_connector.COL_CONIC: "0.0",
            mock_connector.COL_SEMI_DIAMETER: "12.7",
        }.get(col, "")
    )
    editor = LensEditor(mock_connector)
    editor.load_data()

    editor.tableWidget.setCurrentCell(1, mock_connector.COL_TYPE)
    editor._copy_current_cell_to_clipboard()
    assert qapp.clipboard().text() == "Standard"

    editor._copy_selected_row_to_clipboard()
    assert qapp.clipboard().text() == "\t".join(
        ["Standard", "Comment 1", "1.0", "2.0", "BK7", "0.0", "12.7"]
    )


def test_lens_editor_context_menu_contains_copy_actions(qapp, mock_connector, monkeypatch):
    from optiland_gui.lens_editor import LensEditor

    editor = LensEditor(mock_connector)
    action_texts: list[str] = []

    class _FakeMenu:
        def __init__(self, *_args, **_kwargs):
            self._actions = []

        def setObjectName(self, *_args, **_kwargs):
            return None

        def addAction(self, text):  # noqa: ANN001
            action = MagicMock()
            action.text.return_value = text
            self._actions.append(action)
            return action

        def addSeparator(self):
            return None

        def exec(self, *_args, **_kwargs):  # noqa: ANN201
            action_texts.extend(action.text() for action in self._actions)
            return None

    monkeypatch.setattr("optiland_gui.lens_editor.QMenu", _FakeMenu)

    target_item = editor.tableWidget.item(1, mock_connector.COL_COMMENT)
    assert target_item is not None

    editor.show_context_menu(editor.tableWidget.visualItemRect(target_item).center())

    assert action_texts[:4] == ["Copy Cell", "Cut Cell", "Copy Row", "Paste Cell"]


def test_lens_editor_ctrl_c_copies_widget_backed_type_cell(qapp, mock_connector):
    from optiland_gui.lens_editor import LensEditor

    editor = LensEditor(mock_connector)
    editor.load_data()
    editor.tableWidget.setCurrentCell(1, mock_connector.COL_TYPE)

    widget = editor.tableWidget.cellWidget(1, mock_connector.COL_TYPE)
    assert widget is not None

    handled = editor.eventFilter(
        widget,
        QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier),
    )

    assert handled is True
    assert qapp.clipboard().text() == "Standard"


def test_lens_editor_ctrl_insert_copies_widget_backed_type_cell(qapp, mock_connector):
    from optiland_gui.lens_editor import LensEditor

    editor = LensEditor(mock_connector)
    editor.load_data()
    editor.tableWidget.setCurrentCell(1, mock_connector.COL_TYPE)

    widget = editor.tableWidget.cellWidget(1, mock_connector.COL_TYPE)
    assert widget is not None

    handled = editor.eventFilter(
        widget,
        QKeyEvent(
            QEvent.Type.KeyPress,
            Qt.Key.Key_Insert,
            Qt.KeyboardModifier.ControlModifier,
        ),
    )

    assert handled is True
    assert qapp.clipboard().text() == "Standard"


def test_lens_editor_ctrl_insert_copies_from_table_viewport(qapp, mock_connector):
    from optiland_gui.lens_editor import LensEditor

    mock_connector.get_surface_data.side_effect = (
        lambda row, col: {
            mock_connector.COL_COMMENT: "Stop",
            mock_connector.COL_RADIUS: "inf",
            mock_connector.COL_THICKNESS: "20.0000",
            mock_connector.COL_MATERIAL: "Air",
            mock_connector.COL_CONIC: "0.0000",
            mock_connector.COL_SEMI_DIAMETER: "12.7000",
        }.get(col, "")
    )
    editor = LensEditor(mock_connector)
    editor.load_data()
    editor._remember_active_cell(1, mock_connector.COL_THICKNESS)

    handled = editor.eventFilter(
        editor.tableWidget.viewport(),
        QKeyEvent(
            QEvent.Type.KeyPress,
            Qt.Key.Key_Insert,
            Qt.KeyboardModifier.ControlModifier,
        ),
    )

    assert handled is True
    assert qapp.clipboard().text() == "20.0000"


def test_lens_editor_current_type_cell_widget_gets_separate_highlight(
    qapp, mock_connector
):
    from optiland_gui.lens_editor import SurfaceTypeWidget, LensEditor

    editor = LensEditor(mock_connector)
    editor.load_data()
    editor.tableWidget.setCurrentCell(1, mock_connector.COL_TYPE)

    widget = editor.tableWidget.cellWidget(1, mock_connector.COL_TYPE)
    assert isinstance(widget, SurfaceTypeWidget)
    assert widget.property("currentCell") is True

    editor.tableWidget.setCurrentCell(2, mock_connector.COL_COMMENT)

    assert widget.property("currentCell") is False


def test_lens_editor_ctrl_c_copies_last_clicked_table_cell_not_stale_type_focus(
    qapp, mock_connector
):
    from optiland_gui.lens_editor import LensEditor

    mock_connector.get_surface_data.side_effect = (
        lambda row, col: {
            mock_connector.COL_COMMENT: "Stop",
            mock_connector.COL_RADIUS: "inf",
            mock_connector.COL_THICKNESS: "20.0000",
            mock_connector.COL_MATERIAL: "Air",
            mock_connector.COL_CONIC: "0.0000",
            mock_connector.COL_SEMI_DIAMETER: "12.7000",
        }.get(col, "")
        if row == 1
        else ""
    )
    editor = LensEditor(mock_connector)
    editor.load_data()

    editor.tableWidget.setCurrentCell(1, mock_connector.COL_TYPE)
    editor._remember_active_cell(1, mock_connector.COL_THICKNESS)
    editor.tableWidget.setCurrentCell(1, mock_connector.COL_THICKNESS)
    editor._copy_current_cell_to_clipboard()

    assert qapp.clipboard().text() == "20.0000"


def test_lens_editor_active_cell_highlight_survives_focus_within_table(
    qapp, mock_connector
):
    from optiland_gui.lens_editor import LensEditor

    editor = LensEditor(mock_connector)
    editor.load_data()
    child = QLineEdit(editor.tableWidget)

    editor._remember_active_cell(1, mock_connector.COL_THICKNESS)
    editor._handle_application_focus_changed(editor.tableWidget, child)

    assert editor._active_cell == (1, mock_connector.COL_THICKNESS)


def test_lens_editor_active_cell_highlight_clears_when_focus_leaves_table(
    qapp, mock_connector
):
    from optiland_gui.lens_editor import LensEditor

    editor = LensEditor(mock_connector)
    editor.load_data()
    outside = QLineEdit()

    editor._remember_active_cell(1, mock_connector.COL_THICKNESS)
    editor._handle_application_focus_changed(editor.tableWidget, outside)

    assert editor._active_cell == (-1, -1)


def test_lens_editor_mouse_click_sets_active_cell_for_copy(qapp, mock_connector):
    from optiland_gui.lens_editor import LensEditor

    mock_connector.get_surface_data.side_effect = (
        lambda row, col: {
            mock_connector.COL_COMMENT: "Stop",
            mock_connector.COL_RADIUS: "inf",
            mock_connector.COL_THICKNESS: "20.0000",
            mock_connector.COL_MATERIAL: "Air",
            mock_connector.COL_CONIC: "0.0000",
            mock_connector.COL_SEMI_DIAMETER: "12.7000",
        }.get(col, "")
        if row == 1
        else ""
    )
    editor = LensEditor(mock_connector)
    editor.load_data()

    item = editor.tableWidget.item(1, mock_connector.COL_THICKNESS)
    assert item is not None
    click_pos = editor.tableWidget.visualItemRect(item).center()
    event = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        click_pos,
        editor.tableWidget.viewport().mapToGlobal(click_pos),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    editor.eventFilter(editor.tableWidget.viewport(), event)

    assert editor._active_cell == (1, mock_connector.COL_THICKNESS)

    editor._copy_current_cell_to_clipboard()
    assert qapp.clipboard().text() == "20.0000"


def test_lens_editor_current_cell_change_does_not_override_clicked_copy_target(
    qapp, mock_connector
):
    from optiland_gui.lens_editor import LensEditor

    mock_connector.get_surface_data.side_effect = (
        lambda row, col: {
            mock_connector.COL_COMMENT: "ADC1",
            mock_connector.COL_RADIUS: "inf",
            mock_connector.COL_THICKNESS: "20.0000",
            mock_connector.COL_MATERIAL: "Air",
            mock_connector.COL_CONIC: "0.0000",
            mock_connector.COL_SEMI_DIAMETER: "12.7000",
        }.get(col, "")
        if row == 1
        else ""
    )
    editor = LensEditor(mock_connector)
    editor.load_data()

    editor._remember_active_cell(1, mock_connector.COL_THICKNESS)
    editor._sync_current_cell_highlight(
        1,
        mock_connector.COL_COMMENT,
        1,
        mock_connector.COL_THICKNESS,
    )
    editor._copy_current_cell_to_clipboard()

    assert qapp.clipboard().text() == "20.0000"


def test_lens_editor_paste_shortcuts_update_active_editable_cell(qapp, mock_connector):
    from optiland_gui.lens_editor import LensEditor

    editor = LensEditor(mock_connector)
    editor.load_data()
    qapp.clipboard().setText("33.3333")

    editor._remember_active_cell(1, mock_connector.COL_THICKNESS)
    handled = editor.eventFilter(
        editor.tableWidget,
        QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier),
    )

    assert handled is True
    assert editor.tableWidget.item(1, mock_connector.COL_THICKNESS).text() == "33.3333"


def test_lens_editor_shift_insert_pastes_into_type_widget(qapp, mock_connector):
    from optiland_gui.lens_editor import LensEditor, SurfaceTypeWidget

    editor = LensEditor(mock_connector)
    editor.load_data()
    qapp.clipboard().setText("aspheric")

    widget = editor.tableWidget.cellWidget(1, mock_connector.COL_TYPE)
    assert isinstance(widget, SurfaceTypeWidget)
    editor._remember_active_cell(1, mock_connector.COL_TYPE)
    handled = editor.eventFilter(
        widget,
        QKeyEvent(
            QEvent.Type.KeyPress,
            Qt.Key.Key_Insert,
            Qt.KeyboardModifier.ShiftModifier,
        ),
    )

    assert handled is True
    assert widget.type_edit.text() == "Aspheric"


def test_lens_editor_shift_insert_pastes_from_table_viewport(qapp, mock_connector):
    from optiland_gui.lens_editor import LensEditor

    editor = LensEditor(mock_connector)
    editor.load_data()
    qapp.clipboard().setText("33.3333")
    editor._remember_active_cell(1, mock_connector.COL_THICKNESS)

    handled = editor.eventFilter(
        editor.tableWidget.viewport(),
        QKeyEvent(
            QEvent.Type.KeyPress,
            Qt.Key.Key_Insert,
            Qt.KeyboardModifier.ShiftModifier,
        ),
    )

    assert handled is True
    assert editor.tableWidget.item(1, mock_connector.COL_THICKNESS).text() == "33.3333"


def test_lens_editor_ctrl_x_cuts_active_editable_cell(qapp, mock_connector):
    from optiland_gui.lens_editor import LensEditor

    mock_connector.get_surface_data.side_effect = (
        lambda row, col: {
            mock_connector.COL_COMMENT: "Stop",
            mock_connector.COL_RADIUS: "inf",
            mock_connector.COL_THICKNESS: "20.0000",
            mock_connector.COL_MATERIAL: "Air",
            mock_connector.COL_CONIC: "0.0000",
            mock_connector.COL_SEMI_DIAMETER: "12.7000",
        }.get(col, "")
    )
    editor = LensEditor(mock_connector)
    editor.load_data()
    qapp.clipboard().clear()
    editor._remember_active_cell(1, mock_connector.COL_THICKNESS)

    handled = editor.eventFilter(
        editor.tableWidget,
        QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_X, Qt.KeyboardModifier.ControlModifier),
    )

    assert handled is True
    assert qapp.clipboard().text() == "20.0000"
    assert editor.tableWidget.item(1, mock_connector.COL_THICKNESS).text() == "0.0000"


def test_lens_editor_does_not_override_native_copy_in_text_inputs(qapp, mock_connector):
    from optiland_gui.lens_editor import LensEditor

    editor = LensEditor(mock_connector)
    editor.load_data()
    widget = editor.tableWidget.cellWidget(1, mock_connector.COL_TYPE)
    assert widget is not None
    widget.type_edit.setFocus()
    widget.type_edit.selectAll()

    handled = editor.eventFilter(
        widget.type_edit,
        QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier),
    )

    assert handled is False


def test_lens_editor_does_not_override_native_paste_in_text_inputs(qapp, mock_connector):
    from optiland_gui.lens_editor import LensEditor

    editor = LensEditor(mock_connector)
    editor.load_data()
    widget = editor.tableWidget.cellWidget(1, mock_connector.COL_TYPE)
    assert widget is not None

    handled = editor.eventFilter(
        widget.type_edit,
        QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier),
    )

    assert handled is False


def test_lens_editor_tab_moves_across_columns_and_rows(qapp, mock_connector):
    from optiland_gui.lens_editor import LensEditor

    editor = LensEditor(mock_connector)
    editor.load_data()
    editor._remember_active_cell(1, mock_connector.COL_COMMENT)

    handled = editor.eventFilter(
        editor.tableWidget,
        QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Tab, Qt.NoModifier),
    )

    assert handled is True
    assert editor._active_cell == (1, mock_connector.COL_RADIUS)


def test_lens_editor_arrow_keys_move_active_cell_when_not_editing_text(qapp, mock_connector):
    from optiland_gui.lens_editor import LensEditor

    editor = LensEditor(mock_connector)
    editor.load_data()
    editor._remember_active_cell(1, mock_connector.COL_THICKNESS)

    handled = editor.eventFilter(
        editor.tableWidget,
        QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Right, Qt.NoModifier),
    )

    assert handled is True
    assert editor._active_cell == (1, mock_connector.COL_MATERIAL)


def test_lens_editor_restores_persisted_column_widths(qapp, mock_connector, monkeypatch):
    from optiland_gui.lens_editor import LensEditor

    class _FakeSettings:
        _store: dict[str, object] = {}
        sync_calls = 0

        def __init__(self, *_args, **_kwargs):
            pass

        def value(self, key, defaultValue=None, type=None):  # noqa: ANN001, A002, N803
            value = self._store.get(key, defaultValue)
            if type is not None and value is not None:
                try:
                    return type(value)
                except (TypeError, ValueError):
                    return defaultValue
            return value

        def setValue(self, key, value):  # noqa: ANN001, N802
            self._store[key] = value

        def sync(self):
            type(self).sync_calls += 1

    monkeypatch.setattr("optiland_gui.lens_editor.QSettings", _FakeSettings)

    editor = LensEditor(mock_connector)
    editor.load_data()
    editor.tableWidget.setColumnWidth(mock_connector.COL_THICKNESS, 173)
    editor.close()

    restored = LensEditor(mock_connector)
    restored.load_data()

    assert restored.tableWidget.columnWidth(mock_connector.COL_THICKNESS) == 173
    assert _FakeSettings.sync_calls >= 1


def test_surface_properties_widget_applies_annular_aperture(qapp, mock_connector):
    from optiland_gui.lens_editor import SurfacePropertiesWidget

    mock_connector.get_surface_aperture_config.return_value = {
        "type": "ring_aperture",
        "outer_radius": 3.8,
        "inner_radius": 1.5,
        "clear_radius": 3.8,
    }

    widget = SurfacePropertiesWidget(1, mock_connector)
    widget.aperture_inputs["outer_radius"].setText("4.2000")
    widget.aperture_inputs["inner_radius"].setText("1.1000")
    widget.apply_changes()

    mock_connector.set_surface_aperture_config.assert_called_with(
        1,
        {
            "type": "ring_aperture",
            "outer_radius": "4.2000",
            "inner_radius": "1.1000",
            "clear_radius": "4.2000",
        },
    )


def test_surface_properties_widget_selecting_annular_seeds_inner_radius_and_applies_on_confirm(
    qapp, mock_connector
):
    from optiland_gui.lens_editor import SurfacePropertiesWidget

    mock_connector.get_surface_aperture_config.return_value = {"type": "none"}

    widget = SurfacePropertiesWidget(1, mock_connector)
    widget.aperture_type_combo.setCurrentText("Annular Aperture")

    mock_connector.set_surface_aperture_config.assert_not_called()
    mock_connector.set_surface_geometry_params.assert_not_called()

    widget.apply_changes()

    mock_connector.set_surface_aperture_config.assert_called_with(
        1,
        {
            "type": "ring_aperture",
            "outer_radius": "1.0000",
            "inner_radius": "0.2500",
            "clear_radius": "1.0000",
        },
    )
    mock_connector.set_surface_geometry_params.assert_not_called()


def test_surface_properties_widget_shows_only_relevant_aperture_fields(
    qapp, mock_connector
):
    from optiland_gui.lens_editor import SurfacePropertiesWidget

    mock_connector.get_surface_aperture_config.return_value = {"type": "none"}

    widget = SurfacePropertiesWidget(1, mock_connector)

    widget.aperture_type_combo.setCurrentText("Circular Aperture")
    assert not widget.aperture_inputs["outer_radius"].isHidden()
    assert widget.aperture_inputs["inner_radius"].isHidden()
    assert widget.aperture_inputs["clear_radius"].isHidden()

    widget.aperture_type_combo.setCurrentText("Annular Aperture")
    assert not widget.aperture_inputs["outer_radius"].isHidden()
    assert not widget.aperture_inputs["inner_radius"].isHidden()
    assert widget.aperture_inputs["clear_radius"].isHidden()

    widget.aperture_type_combo.setCurrentText("Annular Mask")
    assert not widget.aperture_inputs["outer_radius"].isHidden()
    assert not widget.aperture_inputs["inner_radius"].isHidden()
    assert not widget.aperture_inputs["clear_radius"].isHidden()


def test_even_asphere_surface_properties_widget_uses_structured_coefficient_fields(
    qapp, mock_connector
):
    from optiland_gui.lens_editor import SurfacePropertiesWidget

    mock_connector.get_surface_type_info.return_value = {
        "display_text": "Even_Asphere",
        "is_changeable": True,
        "has_extra_params": True,
    }
    mock_connector.get_surface_geometry_params.return_value = {
        "Coefficients": [0.1, 0.01, 0.001]
    }

    widget = SurfacePropertiesWidget(1, mock_connector)

    assert widget._geometry_mode == "even_asphere"
    assert len(widget._asphere_coeff_inputs) >= 8
    assert widget._asphere_coeff_inputs[0].text() == "0.1"
    assert widget._asphere_coeff_inputs[1].text() == "0.01"
    assert widget._asphere_coeff_inputs[2].text() == "0.001"

    widget._asphere_coeff_inputs[0].setText("0.25")
    widget._asphere_coeff_inputs[1].setText("0.05")
    widget._asphere_coeff_inputs[2].setText("")
    widget.apply_changes()

    mock_connector.set_surface_geometry_params.assert_called_with(
        1, {"Coefficients": "[0.25, 0.05]"}
    )


def test_structured_even_asphere_editor_is_used_even_if_display_type_is_standard(
    qapp, mock_connector
):
    from optiland.geometries.even_asphere import EvenAsphere
    from optiland.coordinate_system import CoordinateSystem
    from optiland_gui.lens_editor import SurfacePropertiesWidget

    mock_connector.get_surface_type_info.return_value = {
        "display_text": "Standard",
        "is_changeable": True,
        "has_extra_params": True,
    }
    mock_connector.get_surface_geometry_params.return_value = {
        "Coefficients": [0.1, 0.01]
    }
    mock_connector._optic.surfaces.surfaces[1].geometry = EvenAsphere(
        CoordinateSystem(), 50.0, 0.0, coefficients=[0.1, 0.01]
    )

    widget = SurfacePropertiesWidget(1, mock_connector)

    assert widget._geometry_mode == "even_asphere"
    assert widget._asphere_coeff_inputs[0].text() == "0.1"


def test_standard_surface_with_coeff_like_params_does_not_use_even_asphere_editor(
    qapp, mock_connector
):
    from optiland_gui.lens_editor import SurfacePropertiesWidget

    mock_connector.get_surface_type_info.return_value = {
        "display_text": "Standard",
        "is_changeable": True,
        "has_extra_params": True,
    }
    mock_connector.get_surface_geometry_params.return_value = {
        "Coefficients": [0.1, 0.01]
    }

    widget = SurfacePropertiesWidget(1, mock_connector)

    assert widget._geometry_mode == "generic"
    assert widget._asphere_coeff_inputs == []


def test_properties_panel_width_stays_within_table_viewport(qapp, mock_connector):
    from optiland_gui.lens_editor import LensEditor

    editor = LensEditor(mock_connector)
    editor.resize(640, 480)
    editor.load_data()
    editor.open_prop_source_row = 1
    editor.load_data()
    editor.tableWidget.viewport().resize(300, 300)

    for col in range(editor.tableWidget.columnCount()):
        editor.tableWidget.setColumnWidth(col, 70)

    assert editor._properties_widget_available_width() <= (
        editor.tableWidget.viewport().width() - 24
    )


def test_surface_properties_widget_apply_and_close_emits_close_request(
    qapp, mock_connector
):
    from optiland_gui.lens_editor import SurfacePropertiesWidget

    mock_connector.get_surface_aperture_config.return_value = {"type": "none"}
    widget = SurfacePropertiesWidget(1, mock_connector)
    closed: list[bool] = []
    widget.requestClose.connect(lambda: closed.append(True))

    widget.aperture_type_combo.setCurrentText("Annular Aperture")
    widget._apply_and_close()

    assert closed == [True]
    mock_connector.set_surface_aperture_config.assert_called()
