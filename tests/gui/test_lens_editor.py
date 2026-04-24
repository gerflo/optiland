"""Tests for LensEditor variable highlighting and SurfaceTypeWidget badge."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QColor, QKeyEvent
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QLineEdit, QTableWidgetSelectionRange


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
    conn.get_surface_group_metadata.return_value = {
        "group_id": None,
        "group_name": None,
        "group_role": None,
    }
    conn.get_group_rows.return_value = []
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
    action_state: dict[str, bool] = {}
    mock_connector.get_group_rows.return_value = []

    class _FakeMenu:
        def __init__(self, *_args, **_kwargs):
            self._actions = []

        def setObjectName(self, *_args, **_kwargs):
            return None

        def addAction(self, text):  # noqa: ANN001
            action = MagicMock()
            action.text.return_value = text
            enabled = {"value": True}

            def _set_enabled(value):  # noqa: ANN001
                enabled["value"] = bool(value)

            action.setEnabled.side_effect = _set_enabled
            action.isEnabled.side_effect = lambda: enabled["value"]
            self._actions.append(action)
            return action

        def addSeparator(self):
            return None

        def exec(self, *_args, **_kwargs):  # noqa: ANN201
            action_state.update({action.text(): action.isEnabled() for action in self._actions})
            return None

    monkeypatch.setattr("optiland_gui.lens_editor.QMenu", _FakeMenu)

    target_item = editor.tableWidget.item(1, mock_connector.COL_COMMENT)
    assert target_item is not None

    editor.show_context_menu(editor.tableWidget.visualItemRect(target_item).center())

    assert list(action_state)[:4] == ["Copy Cell", "Cut Cell", "Copy Row", "Paste Cell"]
    assert "Create Element from Selected Surfaces" not in action_state
    assert "Select Entire Element" not in action_state
    assert "Rename Element" not in action_state
    assert "Ungroup Element" not in action_state
    assert "Flip Element" not in action_state
    assert "Duplicate Element" not in action_state
    assert "Move Element..." not in action_state


def test_lens_editor_context_menu_shows_create_element_only_for_valid_multi_selection(
    qapp, mock_connector, monkeypatch
):
    from optiland_gui.lens_editor import LensEditor

    action_state = {}
    editor = LensEditor(mock_connector)
    editor.load_data()
    editor._select_surface_rows([1, 2])

    class _FakeMenu:
        def __init__(self, *_args, **_kwargs):
            self._actions = []

        def setObjectName(self, *_args, **_kwargs):
            return None

        def addAction(self, text):  # noqa: ANN001
            action = MagicMock()
            action.text.return_value = text
            enabled = {"value": True}

            def _set_enabled(value):  # noqa: ANN001
                enabled["value"] = bool(value)

            action.setEnabled.side_effect = _set_enabled
            action.isEnabled.side_effect = lambda: enabled["value"]
            self._actions.append(action)
            return action

        def addSeparator(self):
            return None

        def exec(self, *_args, **_kwargs):  # noqa: ANN201
            action_state.update({action.text(): action.isEnabled() for action in self._actions})
            return None

    monkeypatch.setattr("optiland_gui.lens_editor.QMenu", _FakeMenu)

    target_item = editor.tableWidget.item(1, mock_connector.COL_COMMENT)
    assert target_item is not None

    editor.show_context_menu(editor.tableWidget.visualItemRect(target_item).center())

    assert action_state["Create Element from Selected Surfaces"] is True
    assert "Select Entire Element" not in action_state


def test_lens_editor_context_menu_shows_element_actions_for_grouped_surface(
    qapp, mock_connector, monkeypatch
):
    from optiland_gui.lens_editor import LensEditor

    action_state = {}
    mock_connector.get_group_rows.side_effect = lambda row: [1, 2] if row in (1, 2) else []
    mock_connector.get_surface_group_metadata.side_effect = lambda row: (
        {"group_id": "grp1", "group_name": "L1", "group_role": "lens"}
        if row in (1, 2)
        else {"group_id": None, "group_name": None, "group_role": None}
    )
    editor = LensEditor(mock_connector)
    editor.load_data()

    class _FakeMenu:
        def __init__(self, *_args, **_kwargs):
            self._actions = []

        def setObjectName(self, *_args, **_kwargs):
            return None

        def addAction(self, text):  # noqa: ANN001
            action = MagicMock()
            action.text.return_value = text
            enabled = {"value": True}

            def _set_enabled(value):  # noqa: ANN001
                enabled["value"] = bool(value)

            action.setEnabled.side_effect = _set_enabled
            action.isEnabled.side_effect = lambda: enabled["value"]
            self._actions.append(action)
            return action

        def addSeparator(self):
            return None

        def exec(self, *_args, **_kwargs):  # noqa: ANN201
            action_state.update({action.text(): action.isEnabled() for action in self._actions})
            return None

    monkeypatch.setattr("optiland_gui.lens_editor.QMenu", _FakeMenu)

    target_item = editor.tableWidget.item(1, mock_connector.COL_COMMENT)
    assert target_item is not None

    editor.show_context_menu(editor.tableWidget.visualItemRect(target_item).center())

    assert "Select Entire Element" in action_state
    assert "Rename Element" in action_state
    assert "Ungroup Element" in action_state
    assert "Flip Element" in action_state
    assert "Duplicate Element" in action_state
    assert "Move Element..." in action_state


def test_lens_editor_context_menu_hides_create_element_for_already_grouped_selection(
    qapp, mock_connector, monkeypatch
):
    from optiland_gui.lens_editor import LensEditor

    action_state = {}
    mock_connector.get_group_rows.side_effect = lambda row: [1, 2] if row in (1, 2) else []
    mock_connector.get_surface_group_metadata.side_effect = lambda row: (
        {"group_id": "grp1", "group_name": "L1", "group_role": "lens"}
        if row in (1, 2)
        else {"group_id": None, "group_name": None, "group_role": None}
    )
    editor = LensEditor(mock_connector)
    editor.load_data()
    editor._select_surface_rows([1, 2])

    class _FakeMenu:
        def __init__(self, *_args, **_kwargs):
            self._actions = []

        def setObjectName(self, *_args, **_kwargs):
            return None

        def addAction(self, text):  # noqa: ANN001
            action = MagicMock()
            action.text.return_value = text
            enabled = {"value": True}

            def _set_enabled(value):  # noqa: ANN001
                enabled["value"] = bool(value)

            action.setEnabled.side_effect = _set_enabled
            action.isEnabled.side_effect = lambda: enabled["value"]
            self._actions.append(action)
            return action

        def addSeparator(self):
            return None

        def exec(self, *_args, **_kwargs):  # noqa: ANN201
            action_state.update({action.text(): action.isEnabled() for action in self._actions})
            return None

    monkeypatch.setattr("optiland_gui.lens_editor.QMenu", _FakeMenu)

    target_item = editor.tableWidget.item(1, mock_connector.COL_COMMENT)
    assert target_item is not None

    editor.show_context_menu(editor.tableWidget.visualItemRect(target_item).center())

    assert "Create Element from Selected Surfaces" not in action_state


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


def test_lens_editor_select_entire_element_selects_group_rows(qapp, mock_connector):
    from optiland_gui.lens_editor import LensEditor

    mock_connector.get_group_rows.return_value = [1, 2]
    mock_connector.get_surface_group_metadata.side_effect = lambda row: (
        {"group_id": "grp1", "group_name": "L1", "group_role": "lens"}
        if row in (1, 2)
        else {"group_id": None, "group_name": None, "group_role": None}
    )
    editor = LensEditor(mock_connector)
    editor.load_data()

    editor._select_entire_element(1)

    selected_rows = sorted({index.row() for index in editor.tableWidget.selectedIndexes()})
    assert selected_rows == [1, 2]


def test_lens_editor_grouped_elements_are_collapsed_by_default(qapp, mock_connector):
    from optiland_gui.lens_editor import LensEditor, SurfaceTypeWidget

    mock_connector.get_group_rows.side_effect = lambda row: [1, 2] if row in (1, 2) else []
    mock_connector.get_surface_group_metadata.side_effect = lambda row: (
        {"group_id": "grp1", "group_name": "L1", "group_role": "lens"}
        if row in (1, 2)
        else {"group_id": None, "group_name": None, "group_role": None}
    )
    mock_connector.get_surface_data.side_effect = lambda row, col: {
        (1, mock_connector.COL_RADIUS): "50.0",
        (2, mock_connector.COL_RADIUS): "-50.0",
        (1, mock_connector.COL_THICKNESS): "5.0",
        (2, mock_connector.COL_THICKNESS): "45.0",
        (1, mock_connector.COL_MATERIAL): "N-BK7",
        (2, mock_connector.COL_MATERIAL): "Air",
        (1, mock_connector.COL_SEMI_DIAMETER): "12.7",
        (2, mock_connector.COL_SEMI_DIAMETER): "12.7",
    }.get((row, col), "")

    editor = LensEditor(mock_connector)

    assert editor.tableWidget.isRowHidden(2) is True
    type_widget = editor.tableWidget.cellWidget(1, mock_connector.COL_TYPE)
    assert isinstance(type_widget, SurfaceTypeWidget)
    assert type_widget.type_edit.text() == "L1"
    assert editor.tableWidget.item(1, mock_connector.COL_COMMENT).text() == "L1 (2 surfaces, lens)"
    assert editor.tableWidget.item(1, mock_connector.COL_RADIUS).text() == "..."
    assert editor.tableWidget.item(1, mock_connector.COL_CONIC).text() == "..."
    assert editor.tableWidget.item(1, mock_connector.COL_THICKNESS).text() == "45.0"
    assert editor.tableWidget.item(1, mock_connector.COL_MATERIAL).text() == "N-BK7"
    assert editor.tableWidget.item(1, mock_connector.COL_COMMENT).font().bold() is True
    assert type_widget.type_edit.font().bold() is True
    assert (
        editor.tableWidget.item(1, mock_connector.COL_THICKNESS).flags()
        & Qt.ItemFlag.ItemIsEditable
    )
    assert editor.tableWidget.verticalHeaderItem(1).text() == "▸ 1"


def test_lens_editor_toggle_group_expanded_reveals_member_rows(qapp, mock_connector):
    from optiland_gui.lens_editor import LensEditor

    mock_connector.get_group_rows.side_effect = lambda row: [1, 2] if row in (1, 2) else []
    mock_connector.get_surface_group_metadata.side_effect = lambda row: (
        {"group_id": "grp1", "group_name": "L1", "group_role": "lens"}
        if row in (1, 2)
        else {"group_id": None, "group_name": None, "group_role": None}
    )

    editor = LensEditor(mock_connector)
    assert editor.tableWidget.isRowHidden(2) is True

    editor._toggle_group_expanded(1)

    assert editor.tableWidget.isRowHidden(2) is False
    assert editor.tableWidget.verticalHeaderItem(1).text() == "▾ 1"
    assert editor.tableWidget.verticalHeaderItem(2).background().color().alpha() > 0
    assert editor.tableWidget.item(2, mock_connector.COL_COMMENT).background().color().alpha() > 0


def test_lens_editor_collapsed_group_material_summary_hides_mixed_glasses(
    qapp, mock_connector
):
    from optiland_gui.lens_editor import LensEditor

    mock_connector.get_group_rows.side_effect = lambda row: [1, 2, 3] if row in (1, 2, 3) else []
    mock_connector.get_surface_group_metadata.side_effect = lambda row: (
        {"group_id": "grp1", "group_name": "ASM1", "group_role": "assembly"}
        if row in (1, 2, 3)
        else {"group_id": None, "group_name": None, "group_role": None}
    )
    mock_connector.get_surface_data.side_effect = lambda row, col: {
        (1, mock_connector.COL_THICKNESS): "5.0",
        (2, mock_connector.COL_THICKNESS): "10.0",
        (3, mock_connector.COL_THICKNESS): "15.0",
        (1, mock_connector.COL_MATERIAL): "N-BK7",
        (2, mock_connector.COL_MATERIAL): "N-SF5",
        (3, mock_connector.COL_MATERIAL): "Air",
    }.get((row, col), "")

    editor = LensEditor(mock_connector)

    assert editor.tableWidget.item(1, mock_connector.COL_MATERIAL).text() == "..."


def test_lens_editor_collapsed_group_thickness_edits_last_surface(qapp, mock_connector):
    from optiland_gui.lens_editor import LensEditor

    mock_connector.get_group_rows.side_effect = lambda row: [1, 2] if row in (1, 2) else []
    mock_connector.get_surface_group_metadata.side_effect = lambda row: (
        {"group_id": "grp1", "group_name": "L1", "group_role": "lens"}
        if row in (1, 2)
        else {"group_id": None, "group_name": None, "group_role": None}
    )
    mock_connector.get_surface_data.side_effect = lambda row, col: {
        (1, mock_connector.COL_THICKNESS): "5.0",
        (2, mock_connector.COL_THICKNESS): "45.0",
        (1, mock_connector.COL_MATERIAL): "N-BK7",
        (2, mock_connector.COL_MATERIAL): "Air",
    }.get((row, col), "")

    editor = LensEditor(mock_connector)
    item = editor.tableWidget.item(1, mock_connector.COL_THICKNESS)
    assert item is not None

    mock_connector.set_surface_data.reset_mock()
    item.setText("60.0000")

    mock_connector.set_surface_data.assert_called_once_with(
        2, mock_connector.COL_THICKNESS, "60.0000"
    )


def test_lens_editor_collapsing_group_reanchors_focus_to_summary_row(qapp, mock_connector):
    from optiland_gui.lens_editor import LensEditor

    mock_connector.get_group_rows.side_effect = lambda row: [1, 2] if row in (1, 2) else []
    mock_connector.get_surface_group_metadata.side_effect = lambda row: (
        {"group_id": "grp1", "group_name": "L1", "group_role": "lens"}
        if row in (1, 2)
        else {"group_id": None, "group_name": None, "group_role": None}
    )

    editor = LensEditor(mock_connector)
    editor._expanded_group_ids.add("grp1")
    editor.load_data()
    editor.tableWidget.setCurrentCell(2, mock_connector.COL_COMMENT)
    editor._remember_active_cell(2, mock_connector.COL_COMMENT)

    editor._toggle_group_expanded(1)

    assert editor.tableWidget.isRowHidden(2) is True
    assert editor.tableWidget.currentRow() == 1
    assert editor._active_cell == (1, mock_connector.COL_TYPE)


def test_lens_editor_vertical_header_click_toggles_group(qapp, mock_connector):
    from optiland_gui.lens_editor import LensEditor

    mock_connector.get_group_rows.side_effect = lambda row: [1, 2] if row in (1, 2) else []
    mock_connector.get_surface_group_metadata.side_effect = lambda row: (
        {"group_id": "grp1", "group_name": "L1", "group_role": "lens"}
        if row in (1, 2)
        else {"group_id": None, "group_name": None, "group_role": None}
    )

    editor = LensEditor(mock_connector)
    assert editor.tableWidget.isRowHidden(2) is True

    editor._handle_vertical_header_clicked(1)

    assert editor.tableWidget.isRowHidden(2) is False


def test_lens_editor_selected_surface_rows_fill_gaps_between_selected_rows(
    qapp, mock_connector
):
    from optiland_gui.lens_editor import LensEditor

    editor = LensEditor(mock_connector)
    editor.load_data()
    editor.tableWidget.setRangeSelected(QTableWidgetSelectionRange(1, 0, 1, 6), True)
    editor.tableWidget.setRangeSelected(QTableWidgetSelectionRange(3, 0, 3, 6), True)

    assert editor._selected_surface_rows() == [1, 2, 3]


def test_lens_editor_right_click_keeps_multi_row_selection_on_selected_row(
    qapp, mock_connector, monkeypatch
):
    from optiland_gui.lens_editor import LensEditor
    from PySide6.QtGui import QContextMenuEvent

    editor = LensEditor(mock_connector)
    editor.load_data()
    editor.tableWidget.setRangeSelected(QTableWidgetSelectionRange(1, 0, 2, 6), True)
    selected_before = sorted({index.row() for index in editor.tableWidget.selectedIndexes()})
    assert selected_before == [1, 2]

    class _FakeMenu:
        def __init__(self, *_args, **_kwargs):
            self._actions = []

        def setObjectName(self, *_args, **_kwargs):
            return None

        def addAction(self, _text):  # noqa: ANN001
            action = MagicMock()
            action.text.return_value = _text
            action.setEnabled.side_effect = lambda _value: None
            action.isEnabled.side_effect = lambda: True
            self._actions.append(action)
            return action

        def addSeparator(self):
            return None

        def exec(self, *_args, **_kwargs):  # noqa: ANN201
            return None

    monkeypatch.setattr("optiland_gui.lens_editor.QMenu", _FakeMenu)
    target_item = editor.tableWidget.item(2, mock_connector.COL_COMMENT)
    assert target_item is not None

    editor.show_context_menu(editor.tableWidget.visualItemRect(target_item).center())

    selected_after = sorted({index.row() for index in editor.tableWidget.selectedIndexes()})
    assert selected_after == [1, 2]

    widget = editor.tableWidget.cellWidget(1, mock_connector.COL_TYPE)
    assert widget is not None
    editor.eventFilter(
        widget,
        QContextMenuEvent(
            QContextMenuEvent.Reason.Mouse,
            QPoint(1, 1),
            editor.tableWidget.viewport().mapToGlobal(
                editor.tableWidget.visualItemRect(target_item).center()
            ),
        ),
    )
    selected_after_widget = sorted(
        {index.row() for index in editor.tableWidget.selectedIndexes()}
    )
    assert selected_after_widget == [1, 2]


def test_lens_editor_move_element_uses_safe_dialog_parent_and_moves_rows(
    qapp, mock_connector, monkeypatch
):
    from optiland_gui.lens_editor import LensEditor

    mock_connector.get_group_rows.return_value = [1, 2]
    editor = LensEditor(mock_connector)
    editor.load_data()

    captured = {}

    def _fake_get_int(parent, title, label, value, minimum, maximum):  # noqa: ANN001
        captured["parent"] = parent
        captured["title"] = title
        captured["label"] = label
        captured["value"] = value
        captured["minimum"] = minimum
        captured["maximum"] = maximum
        return 3, True

    monkeypatch.setattr("optiland_gui.lens_editor.QInputDialog.getInt", _fake_get_int)
    mock_connector.move_surface_element.return_value = [2, 3]

    editor._move_element(1)

    assert captured["parent"] is editor.window()
    assert captured["minimum"] == 1
    assert captured["maximum"] == 3
    mock_connector.move_surface_element.assert_called_once_with(1, 3)


def test_lens_editor_delete_on_collapsed_group_removes_entire_element(
    qapp, mock_connector
):
    from optiland_gui.lens_editor import LensEditor

    mock_connector.get_group_rows.side_effect = lambda row: [1, 2] if row in (1, 2) else []
    mock_connector.get_surface_group_metadata.side_effect = lambda row: (
        {"group_id": "grp1", "group_name": "L1", "group_role": "lens"}
        if row in (1, 2)
        else {"group_id": None, "group_name": None, "group_role": None}
    )

    editor = LensEditor(mock_connector)
    editor.load_data()
    editor.tableWidget.setCurrentCell(1, mock_connector.COL_COMMENT)

    handled = editor.eventFilter(
        editor.tableWidget,
        QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Delete, Qt.KeyboardModifier.NoModifier),
    )

    assert handled is True
    mock_connector.remove_surface_element.assert_called_once_with(1)
    mock_connector.remove_surface.assert_not_called()


def test_lens_editor_delete_on_expanded_group_removes_only_active_surface(
    qapp, mock_connector
):
    from optiland_gui.lens_editor import LensEditor

    mock_connector.get_group_rows.side_effect = lambda row: [1, 2] if row in (1, 2) else []
    mock_connector.get_surface_group_metadata.side_effect = lambda row: (
        {"group_id": "grp1", "group_name": "L1", "group_role": "lens"}
        if row in (1, 2)
        else {"group_id": None, "group_name": None, "group_role": None}
    )

    editor = LensEditor(mock_connector)
    editor._expanded_group_ids.add("grp1")
    editor.load_data()
    editor.tableWidget.setCurrentCell(2, mock_connector.COL_COMMENT)

    handled = editor.eventFilter(
        editor.tableWidget,
        QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Delete, Qt.KeyboardModifier.NoModifier),
    )

    assert handled is True
    mock_connector.remove_surface.assert_called_once_with(2)
    mock_connector.remove_surface_element.assert_not_called()


def test_lens_editor_delete_in_active_text_editor_does_not_remove_surface(
    qapp, mock_connector
):
    from optiland_gui.lens_editor import LensEditor

    editor = LensEditor(mock_connector)
    editor.load_data()
    text_editor = QLineEdit(editor.tableWidget)
    text_editor.setProperty("lens_row", 2)
    text_editor.setProperty("lens_col", mock_connector.COL_THICKNESS)
    text_editor.setProperty("lens_table_editor", True)

    handled = editor.eventFilter(
        text_editor,
        QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Delete, Qt.KeyboardModifier.NoModifier),
    )

    assert handled is False
    mock_connector.remove_surface.assert_not_called()
    mock_connector.remove_surface_element.assert_not_called()


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


def test_lens_editor_collapsed_element_summary_row_rejects_type_changes(
    qapp, mock_connector
):
    from optiland_gui.lens_editor import LensEditor, SurfaceTypeWidget

    mock_connector.get_group_rows.side_effect = lambda row: [1, 2] if row in (1, 2) else []
    mock_connector.get_surface_group_metadata.side_effect = lambda row: (
        {"group_id": "grp1", "group_name": "L1", "group_role": "lens"}
        if row in (1, 2)
        else {"group_id": None, "group_name": None, "group_role": None}
    )
    editor = LensEditor(mock_connector)
    editor.load_data()

    widget = editor.tableWidget.cellWidget(1, mock_connector.COL_TYPE)
    assert isinstance(widget, SurfaceTypeWidget)
    assert widget.type_edit.isReadOnly() is True

    mock_connector.set_surface_type.reset_mock()
    widget.surfaceTypeChanged.emit("aspheric")

    mock_connector.set_surface_type.assert_not_called()


def test_lens_editor_update_theme_reapplies_group_row_presentation_without_crashing(
    qapp, mock_connector
):
    from optiland_gui.lens_editor import LensEditor

    mock_connector.get_group_rows.side_effect = lambda row: [1, 2] if row in (1, 2) else []
    mock_connector.get_surface_group_metadata.side_effect = lambda row: (
        {"group_id": "grp1", "group_name": "L1", "group_role": "lens"}
        if row in (1, 2)
        else {"group_id": None, "group_name": None, "group_role": None}
    )
    editor = LensEditor(mock_connector)
    editor.load_data()

    editor.update_theme("light")

    comment_item = editor.tableWidget.item(1, mock_connector.COL_COMMENT)
    assert comment_item is not None
    assert "L1" in comment_item.text()


def test_lens_editor_summary_row_rebuilds_deleted_items_during_theme_refresh(
    qapp, mock_connector, monkeypatch
):
    from optiland_gui.lens_editor import LensEditor

    class _BrokenItem:
        def setText(self, _text):
            return None

        def setBackground(self, _brush):
            return None

        def setData(self, _role, _value):
            raise RuntimeError("Internal C++ object already deleted")

    mock_connector.get_group_rows.side_effect = lambda row: [1, 2] if row in (1, 2) else []
    mock_connector.get_surface_group_metadata.side_effect = lambda row: (
        {"group_id": "grp1", "group_name": "L1", "group_role": "lens"}
        if row in (1, 2)
        else {"group_id": None, "group_name": None, "group_role": None}
    )
    editor = LensEditor(mock_connector)
    editor.load_data()

    original_ensure = editor._ensure_table_item

    def flaky_ensure(row, col_idx, *, create=True):
        if row == 1 and col_idx == mock_connector.COL_COMMENT and create:
            monkeypatch.setattr(editor, "_ensure_table_item", original_ensure)
            return _BrokenItem()
        return original_ensure(row, col_idx, create=create)

    monkeypatch.setattr(editor, "_ensure_table_item", flaky_ensure)

    editor.update_theme("light")

    comment_item = editor.tableWidget.item(1, mock_connector.COL_COMMENT)
    assert comment_item is not None
    assert "L1" in comment_item.text()


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


def test_lens_editor_tab_skips_hidden_member_rows_for_collapsed_elements(
    qapp, mock_connector
):
    from optiland_gui.lens_editor import LensEditor

    mock_connector.get_group_rows.side_effect = lambda row: [1, 2] if row in (1, 2) else []
    mock_connector.get_surface_group_metadata.side_effect = lambda row: (
        {"group_id": "grp1", "group_name": "L1", "group_role": "lens"}
        if row in (1, 2)
        else {"group_id": None, "group_name": None, "group_role": None}
    )
    editor = LensEditor(mock_connector)
    editor.load_data()
    editor._remember_active_cell(1, mock_connector.COL_SEMI_DIAMETER)

    handled = editor.eventFilter(
        editor.tableWidget,
        QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Tab, Qt.NoModifier),
    )

    assert handled is True
    assert editor._active_cell == (3, mock_connector.COL_TYPE)


def test_lens_editor_down_arrow_skips_hidden_member_rows_for_collapsed_elements(
    qapp, mock_connector
):
    from optiland_gui.lens_editor import LensEditor

    mock_connector.get_group_rows.side_effect = lambda row: [1, 2] if row in (1, 2) else []
    mock_connector.get_surface_group_metadata.side_effect = lambda row: (
        {"group_id": "grp1", "group_name": "L1", "group_role": "lens"}
        if row in (1, 2)
        else {"group_id": None, "group_name": None, "group_role": None}
    )
    editor = LensEditor(mock_connector)
    editor.load_data()
    editor._remember_active_cell(1, mock_connector.COL_COMMENT)

    handled = editor.eventFilter(
        editor.tableWidget,
        QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Down, Qt.NoModifier),
    )

    assert handled is True
    assert editor._active_cell == (3, mock_connector.COL_COMMENT)


def test_lens_editor_enter_on_collapsed_summary_row_skips_hidden_member_rows(
    qapp, mock_connector
):
    from optiland_gui.lens_editor import LensEditor

    mock_connector.get_group_rows.side_effect = lambda row: [1, 2] if row in (1, 2) else []
    mock_connector.get_surface_group_metadata.side_effect = lambda row: (
        {"group_id": "grp1", "group_name": "L1", "group_role": "lens"}
        if row in (1, 2)
        else {"group_id": None, "group_name": None, "group_role": None}
    )
    editor = LensEditor(mock_connector)
    editor.load_data()
    editor._remember_active_cell(1, mock_connector.COL_SEMI_DIAMETER)

    handled = editor.eventFilter(
        editor.tableWidget,
        QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.NoModifier),
    )

    assert handled is True
    assert editor._active_cell == (3, mock_connector.COL_TYPE)


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


def test_lens_editor_hide_persists_explicit_column_widths(qapp, mock_connector, monkeypatch):
    from optiland_gui.lens_editor import LensEditor

    class _FakeSettings:
        _store: dict[str, object] = {}

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
            return None

    monkeypatch.setattr("optiland_gui.lens_editor.QSettings", _FakeSettings)

    editor = LensEditor(mock_connector)
    editor.load_data()
    editor.tableWidget.setColumnWidth(mock_connector.COL_RADIUS, 211)
    editor.hide()

    restored = LensEditor(mock_connector)
    restored.load_data()

    assert restored.tableWidget.columnWidth(mock_connector.COL_RADIUS) == 211
    stored_widths = _FakeSettings._store.get("LensEditor/Table/ColumnWidths")
    assert isinstance(stored_widths, list)
    assert stored_widths[mock_connector.COL_RADIUS] == 211


def test_lens_editor_table_allows_wide_columns_with_horizontal_scrollbar(
    qapp, mock_connector
):
    from optiland_gui.lens_editor import LensEditor

    editor = LensEditor(mock_connector)
    header = editor.tableWidget.horizontalHeader()

    assert editor.tableWidget.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAsNeeded
    assert header.maximumSectionSize() >= 1_000_000


def test_lens_editor_collapsed_element_row_uses_theme_aware_summary_color(
    qapp, mock_connector, monkeypatch
):
    from optiland_gui.lens_editor import LensEditor

    class _FakeSettings:
        _store = {"Appearance/ThemeId": "test-light"}

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
            return None

    monkeypatch.setattr("optiland_gui.lens_editor.QSettings", _FakeSettings)
    mock_connector.get_group_rows.side_effect = lambda row: [1, 2] if row in (1, 2) else []
    mock_connector.get_surface_group_metadata.side_effect = lambda row: (
        {"group_id": "grp1", "group_name": "L1", "group_role": "lens"}
        if row in (1, 2)
        else {"group_id": None, "group_name": None, "group_role": None}
    )
    qapp.setProperty("activeThemeMode", "light")

    editor = LensEditor(mock_connector)
    comment_item = editor.tableWidget.item(1, mock_connector.COL_COMMENT)

    assert comment_item is not None
    base_color = editor.tableWidget.palette().base().color()
    expected = base_color.darker(editor.ElementRowBackgroundFactor)
    assert comment_item.data(editor._focus_delegate._ROW_ACCENT_ROLE).name().lower() == expected.name().lower()


def test_lens_editor_prefers_live_application_theme_mode_over_settings(
    qapp, mock_connector, monkeypatch
):
    from optiland_gui.lens_editor import LensEditor

    class _FakeSettings:
        _store = {"Appearance/ThemeId": "test-light"}

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
            return None

    class _FakeTheme:
        mode = "light"

    monkeypatch.setattr("optiland_gui.lens_editor.QSettings", _FakeSettings)
    monkeypatch.setattr("optiland_gui.lens_editor.get_theme", lambda _theme_id: _FakeTheme())
    qapp.setProperty("activeThemeMode", "dark")

    editor = LensEditor(mock_connector)

    assert editor._theme_mode() == "dark"


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


def test_surface_properties_widget_update_theme_restyles_sections(qapp, mock_connector):
    from optiland_gui.lens_editor import SurfacePropertiesWidget

    widget = SurfacePropertiesWidget(1, mock_connector)

    widget.update_theme("light")
    assert "rgba(0, 0, 0, 0.62)" in widget.styleSheet()

    widget.update_theme("dark")
    assert "rgba(255, 255, 255, 0.72)" in widget.styleSheet()
