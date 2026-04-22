"""Shared copy helpers for plain QTableWidget-based views."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QPoint, Qt
from PySide6.QtGui import QColor, QKeySequence, QPainter, QPen, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QMenu,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableWidget,
)


class _ActiveCellDelegate(QStyledItemDelegate):
    """Paint a persistent highlight for the helper's active cell."""

    _BORDER = QColor("#FFD166")
    _FILL = QColor(255, 209, 102, 80)

    def __init__(self, support: "TableCopySupport", parent=None) -> None:
        super().__init__(parent)
        self._support = support

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:  # noqa: ANN001
        if self._support.is_active_cell(index.row(), index.column()):
            active_option = QStyleOptionViewItem(option)
            active_option.backgroundBrush = self._FILL
            super().paint(painter, active_option, index)
            painter.save()
            painter.setPen(QPen(self._BORDER, 2))
            painter.drawRect(option.rect.adjusted(1, 1, -2, -2))
            painter.restore()
            return
        super().paint(painter, option, index)


class TableCopySupport(QObject):
    """Attach consistent cell-copy behaviour to a plain ``QTableWidget``."""

    def __init__(self, table: QTableWidget, *, enable_context_menu: bool = True) -> None:
        super().__init__(table)
        self._table = table
        self._enable_context_menu = enable_context_menu
        self._active_cell: tuple[int, int] = (-1, -1)
        self._delegate = _ActiveCellDelegate(self, table)
        table.setItemDelegate(self._delegate)
        self._copy_shortcut = QShortcut(QKeySequence.Copy, table)
        self._copy_insert_shortcut = QShortcut(QKeySequence("Ctrl+Insert"), table)
        self._cut_shortcut = QShortcut(QKeySequence.Cut, table)
        self._paste_shortcut = QShortcut(QKeySequence.Paste, table)
        self._paste_insert_shortcut = QShortcut(QKeySequence("Shift+Insert"), table)
        self._copy_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._copy_insert_shortcut.setContext(
            Qt.ShortcutContext.WidgetWithChildrenShortcut
        )
        self._cut_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._paste_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._paste_insert_shortcut.setContext(
            Qt.ShortcutContext.WidgetWithChildrenShortcut
        )

        table.setContextMenuPolicy(Qt.CustomContextMenu)
        table.installEventFilter(self)
        table.viewport().installEventFilter(self)
        table.cellPressed.connect(self._remember_cell)
        table.cellClicked.connect(self._remember_cell)
        table.currentCellChanged.connect(self._handle_current_cell_changed)
        if enable_context_menu:
            table.customContextMenuRequested.connect(self._show_context_menu)
        self._copy_shortcut.activated.connect(self.copy_current_cell_to_clipboard)
        self._copy_insert_shortcut.activated.connect(self.copy_current_cell_to_clipboard)
        self._cut_shortcut.activated.connect(self.cut_current_cell_to_clipboard)
        self._paste_shortcut.activated.connect(self.paste_clipboard_into_current_cell)
        self._paste_insert_shortcut.activated.connect(
            self.paste_clipboard_into_current_cell
        )
        app = QApplication.instance()
        if app is not None:
            app.focusChanged.connect(self._handle_application_focus_changed)

    def _remember_cell(self, row: int, col: int) -> None:
        if row >= 0 and col >= 0:
            self._active_cell = (row, col)
            self._table.viewport().update()

    def _handle_current_cell_changed(
        self,
        current_row: int,
        current_col: int,
        previous_row: int,
        previous_col: int,
    ) -> None:
        del previous_row, previous_col
        if self._active_cell == (-1, -1):
            self._remember_cell(current_row, current_col)

    def eventFilter(self, watched, event) -> bool:  # noqa: ANN001
        if not hasattr(self, "_table"):
            return super().eventFilter(watched, event)
        try:
            viewport = self._table.viewport()
        except RuntimeError:
            return super().eventFilter(watched, event)
        if watched is self._table and event.type() == QEvent.KeyPress:
            has_ctrl = bool(event.modifiers() & Qt.ControlModifier)
            has_shift = bool(event.modifiers() & Qt.ShiftModifier)
            if (
                has_ctrl
                and event.key() in (Qt.Key_C, Qt.Key_Insert)
            ):
                self.copy_current_cell_to_clipboard()
                return True
            if has_ctrl and event.key() == Qt.Key_X:
                self.cut_current_cell_to_clipboard()
                return True
            if (
                has_ctrl and event.key() == Qt.Key_V
            ) or (
                has_shift and event.key() == Qt.Key_Insert
            ):
                self.paste_clipboard_into_current_cell()
                return True
            if self._handle_navigation_key(event):
                return True
        if watched is viewport and event.type() == QEvent.MouseButtonPress:
            pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
            item = self._table.itemAt(pos)
            if item is not None:
                self._table.setCurrentItem(item)
                self._remember_cell(item.row(), item.column())
        return super().eventFilter(watched, event)

    def _handle_navigation_key(self, event) -> bool:  # noqa: ANN001
        row, col = self._current_cell()
        if row < 0 or col < 0:
            if self._table.rowCount() <= 0 or self._table.columnCount() <= 0:
                return False
            return self._set_active_cell(0, 0)

        key = event.key()
        is_shift_tab = key == Qt.Key_Tab and bool(event.modifiers() & Qt.ShiftModifier)
        if key in (Qt.Key_Tab, Qt.Key_Backtab):
            return self._move_linear(-1 if (key == Qt.Key_Backtab or is_shift_tab) else 1)
        if key == Qt.Key_Left:
            return self._move_relative(0, -1)
        if key == Qt.Key_Right:
            return self._move_relative(0, 1)
        if key == Qt.Key_Up:
            return self._move_relative(-1, 0)
        if key == Qt.Key_Down:
            return self._move_relative(1, 0)
        if key == Qt.Key_Home:
            return self._set_active_cell(row, 0)
        if key == Qt.Key_End:
            return self._set_active_cell(row, self._table.columnCount() - 1)
        if key == Qt.Key_PageUp:
            return self._move_relative(-self._page_step(), 0)
        if key == Qt.Key_PageDown:
            return self._move_relative(self._page_step(), 0)
        return False

    def _page_step(self) -> int:
        row_height = max(1, self._table.verticalHeader().defaultSectionSize())
        viewport_height = max(1, self._table.viewport().height())
        return max(1, viewport_height // row_height)

    def _move_linear(self, delta: int) -> bool:
        row, col = self._current_cell()
        row_count = self._table.rowCount()
        column_count = self._table.columnCount()
        if row_count <= 0 or column_count <= 0:
            return False
        index = (row * column_count + col + delta) % (row_count * column_count)
        target_row, target_col = divmod(index, column_count)
        return self._set_active_cell(target_row, target_col)

    def _move_relative(self, row_delta: int, col_delta: int) -> bool:
        row, col = self._current_cell()
        target_row = min(max(0, row + row_delta), self._table.rowCount() - 1)
        target_col = min(max(0, col + col_delta), self._table.columnCount() - 1)
        return self._set_active_cell(target_row, target_col)

    def _set_active_cell(self, row: int, col: int) -> bool:
        if row < 0 or col < 0:
            return False
        item = self._table.item(row, col)
        if item is not None:
            self._table.setCurrentItem(item)
            self._table.scrollToItem(item, QTableWidget.PositionAtCenter)
        else:
            self._table.setCurrentCell(row, col)
        self._remember_cell(row, col)
        return True

    def _is_within_table(self, widget: QObject | None) -> bool:
        """Return whether *widget* is the table itself or one of its children."""
        current = widget
        while current is not None:
            if current is self._table:
                return True
            parent_getter = getattr(current, "parent", None)
            if not callable(parent_getter):
                break
            current = parent_getter()
        return False

    def _handle_application_focus_changed(self, old, new) -> None:  # noqa: ANN001
        """Keep the active-cell highlight until focus truly leaves the table."""
        if self._is_within_table(new):
            return
        if self._is_within_table(old):
            self.clear_active_cell()

    def clear_active_cell(self) -> None:
        """Clear the persistent active-cell highlight and copy target."""
        if self._active_cell != (-1, -1):
            self._active_cell = (-1, -1)
            self._table.viewport().update()

    def is_active_cell(self, row: int, col: int) -> bool:
        """Return whether ``(row, col)`` is the persistent active cell."""
        return self._active_cell == (row, col)

    def _current_cell(self) -> tuple[int, int]:
        row, col = self._active_cell
        if row >= 0 and col >= 0:
            return row, col
        return self._table.currentRow(), self._table.currentColumn()

    def current_cell(self) -> tuple[int, int]:
        """Return the current copy target cell."""
        return self._current_cell()

    def copy_current_cell_to_clipboard(self) -> None:
        """Copy the last active table cell to the clipboard."""
        row, col = self._current_cell()
        if row < 0 or col < 0:
            return
        item = self._table.item(row, col)
        if item is None:
            return
        QApplication.clipboard().setText(item.text())

    def cut_current_cell_to_clipboard(self) -> None:
        """Cut the active cell when it is editable, otherwise leave it unchanged."""
        row, col = self._current_cell()
        if row < 0 or col < 0:
            return
        item = self._table.item(row, col)
        if item is None:
            return
        QApplication.clipboard().setText(item.text())
        if item.flags() & Qt.ItemFlag.ItemIsEditable:
            item.setText("")

    def paste_clipboard_into_current_cell(self) -> None:
        """Paste clipboard text into the active cell when it is editable."""
        row, col = self._current_cell()
        if row < 0 or col < 0:
            return
        item = self._table.item(row, col)
        if item is None or not (item.flags() & Qt.ItemFlag.ItemIsEditable):
            return
        item.setText(QApplication.clipboard().text())

    def copy_selected_row_to_clipboard(self) -> None:
        """Copy the current row as a tab-separated line."""
        row, _col = self._current_cell()
        if row < 0:
            return
        header = self._table.horizontalHeader()
        values: list[str] = []
        for visual_column in range(self._table.columnCount()):
            column = header.logicalIndex(visual_column)
            item = self._table.item(row, column)
            values.append("" if item is None else item.text())
        QApplication.clipboard().setText("\t".join(values))

    def _show_context_menu(self, pos: QPoint) -> None:
        item = self._table.itemAt(pos)
        if item is not None:
            self._table.setCurrentItem(item)
            self._remember_cell(item.row(), item.column())

        menu = QMenu(self._table)
        copy_cell_action = menu.addAction("Copy Cell")
        cut_cell_action = menu.addAction("Cut Cell")
        paste_cell_action = menu.addAction("Paste Cell")
        copy_row_action = menu.addAction("Copy Row")

        row, col = self._current_cell()
        item = self._table.item(row, col) if row >= 0 and col >= 0 else None
        has_item = item is not None
        is_editable = bool(item is not None and item.flags() & Qt.ItemFlag.ItemIsEditable)
        copy_cell_action.setEnabled(has_item)
        cut_cell_action.setEnabled(is_editable)
        paste_cell_action.setEnabled(is_editable)
        copy_row_action.setEnabled(row >= 0)

        chosen = menu.exec(self._table.viewport().mapToGlobal(pos))
        if chosen == copy_cell_action:
            self.copy_current_cell_to_clipboard()
        elif chosen == cut_cell_action:
            self.cut_current_cell_to_clipboard()
        elif chosen == paste_cell_action:
            self.paste_clipboard_into_current_cell()
        elif chosen == copy_row_action:
            self.copy_selected_row_to_clipboard()
