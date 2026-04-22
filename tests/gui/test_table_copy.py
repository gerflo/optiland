from __future__ import annotations

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QLineEdit, QTableWidget, QTableWidgetItem

from optiland_gui.utils.table_copy import TableCopySupport


def test_table_copy_support_copies_last_active_cell(qapp) -> None:
    table = QTableWidget(2, 2)
    table.setItem(0, 0, QTableWidgetItem("A0"))
    table.setItem(0, 1, QTableWidgetItem("A1"))
    table.setItem(1, 0, QTableWidgetItem("B0"))
    table.setItem(1, 1, QTableWidgetItem("B1"))
    support = TableCopySupport(table)

    table.setCurrentCell(1, 1)
    support._remember_cell(1, 1)
    support.copy_current_cell_to_clipboard()

    assert qapp.clipboard().text() == "B1"


def test_table_copy_support_copies_current_row_in_visual_order(qapp) -> None:
    table = QTableWidget(1, 3)
    table.setHorizontalHeaderLabels(["A", "B", "C"])
    table.setItem(0, 0, QTableWidgetItem("A0"))
    table.setItem(0, 1, QTableWidgetItem("B0"))
    table.setItem(0, 2, QTableWidgetItem("C0"))
    support = TableCopySupport(table)

    table.horizontalHeader().moveSection(2, 0)
    table.setCurrentCell(0, 1)
    support._remember_cell(0, 1)
    support.copy_selected_row_to_clipboard()

    assert qapp.clipboard().text() == "C0\tA0\tB0"


def test_table_copy_support_keeps_active_cell_for_table_children(qapp) -> None:
    table = QTableWidget(1, 1)
    table.setItem(0, 0, QTableWidgetItem("A0"))
    support = TableCopySupport(table)
    child = QLineEdit(table)

    support._remember_cell(0, 0)
    assert support.is_active_cell(0, 0) is True

    support._handle_application_focus_changed(table, child)

    assert support.is_active_cell(0, 0) is True


def test_table_copy_support_clears_active_cell_when_focus_leaves_table(qapp) -> None:
    table = QTableWidget(1, 1)
    table.setItem(0, 0, QTableWidgetItem("A0"))
    support = TableCopySupport(table)
    outside = QLineEdit()

    support._remember_cell(0, 0)
    assert support.is_active_cell(0, 0) is True

    support._handle_application_focus_changed(table, outside)

    assert support.is_active_cell(0, 0) is False


def test_table_copy_support_tab_moves_left_to_right_then_next_row(qapp) -> None:
    table = QTableWidget(2, 2)
    for row in range(2):
        for col in range(2):
            table.setItem(row, col, QTableWidgetItem(f"{row},{col}"))
    support = TableCopySupport(table)

    table.setCurrentCell(0, 0)
    support.eventFilter(table, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Tab, Qt.NoModifier))
    assert support.current_cell() == (0, 1)

    support.eventFilter(table, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Tab, Qt.NoModifier))
    assert support.current_cell() == (1, 0)


def test_table_copy_support_arrow_and_home_end_navigation(qapp) -> None:
    table = QTableWidget(3, 3)
    for row in range(3):
        for col in range(3):
            table.setItem(row, col, QTableWidgetItem(f"{row},{col}"))
    support = TableCopySupport(table)
    support._remember_cell(1, 1)

    support.eventFilter(table, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Left, Qt.NoModifier))
    assert support.current_cell() == (1, 0)

    support.eventFilter(table, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_End, Qt.NoModifier))
    assert support.current_cell() == (1, 2)

    support.eventFilter(table, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Home, Qt.NoModifier))
    assert support.current_cell() == (1, 0)


def test_table_copy_support_ctrl_insert_copies_active_cell(qapp) -> None:
    table = QTableWidget(1, 1)
    table.setItem(0, 0, QTableWidgetItem("A0"))
    support = TableCopySupport(table)
    support._remember_cell(0, 0)

    handled = support.eventFilter(
        table,
        QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Insert, Qt.ControlModifier),
    )

    assert handled is True
    assert qapp.clipboard().text() == "A0"


def test_table_copy_support_shift_insert_pastes_into_editable_cell(qapp) -> None:
    table = QTableWidget(1, 1)
    table.setItem(0, 0, QTableWidgetItem("A0"))
    support = TableCopySupport(table)
    support._remember_cell(0, 0)
    qapp.clipboard().setText("Pasted")

    handled = support.eventFilter(
        table,
        QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Insert, Qt.ShiftModifier),
    )

    assert handled is True
    assert table.item(0, 0).text() == "Pasted"


def test_table_copy_support_ctrl_x_cuts_editable_cell(qapp) -> None:
    table = QTableWidget(1, 1)
    table.setItem(0, 0, QTableWidgetItem("A0"))
    support = TableCopySupport(table)
    support._remember_cell(0, 0)

    handled = support.eventFilter(
        table,
        QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_X, Qt.ControlModifier),
    )

    assert handled is True
    assert qapp.clipboard().text() == "A0"
    assert table.item(0, 0).text() == ""


def test_table_copy_support_cut_and_paste_are_noops_for_read_only_cells(qapp) -> None:
    table = QTableWidget(1, 1)
    item = QTableWidgetItem("A0")
    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
    table.setItem(0, 0, item)
    support = TableCopySupport(table)
    support._remember_cell(0, 0)
    qapp.clipboard().setText("Pasted")

    support.eventFilter(
        table,
        QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Insert, Qt.ShiftModifier),
    )
    assert table.item(0, 0).text() == "A0"

    support.eventFilter(
        table,
        QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_X, Qt.ControlModifier),
    )
    assert table.item(0, 0).text() == "A0"
