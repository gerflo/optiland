"""A layout that places its items in rows and wraps them when space runs out.

Qt has no flow layout of its own; this is the one from the Qt examples. A
row of controls laid out with it takes a single line when the panel is wide
and continues on the next line instead of forcing a wide minimum size when
the panel is narrow.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QLayout, QLayoutItem, QWidget


class FlowLayout(QLayout):
    """Lays out items left to right and starts a new row when one is full.

    Args:
        parent: Widget the layout is installed on, if any.
        h_spacing: Gap between neighbouring items of a row [px].
        v_spacing: Gap between rows [px].
    """

    def __init__(
        self, parent: QWidget | None = None, h_spacing: int = 6, v_spacing: int = 4
    ) -> None:
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self._h_spacing = h_spacing
        self._v_spacing = v_spacing

    def addItem(self, item: QLayoutItem) -> None:  # noqa: N802 -- Qt override
        """Append *item* to the flow."""
        self._items.append(item)

    def count(self) -> int:
        """Number of items in the flow."""
        return len(self._items)

    def itemAt(self, index: int) -> QLayoutItem | None:  # noqa: N802 -- Qt override
        """The item at *index*, or ``None``."""
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int) -> QLayoutItem | None:  # noqa: N802 -- Qt override
        """Remove and return the item at *index*, or ``None``."""
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self) -> Qt.Orientation:  # noqa: N802 -- Qt override
        """The flow never asks for more space than its rows need."""
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802 -- Qt override
        """The height depends on how many rows the width allows."""
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802 -- Qt override
        """Height the items need when laid out in *width* pixels."""
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802 -- Qt override
        """Place the items inside *rect*."""
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self) -> QSize:  # noqa: N802 -- Qt override
        """All items in a single row."""
        width = 0
        height = 0
        visible = [item for item in self._items if not item.isEmpty()]
        for item in visible:
            hint = item.sizeHint()
            width += hint.width()
            height = max(height, hint.height())
        width += self._h_spacing * max(len(visible) - 1, 0)
        margins = self.contentsMargins()
        return QSize(
            width + margins.left() + margins.right(),
            height + margins.top() + margins.bottom(),
        )

    def minimumSize(self) -> QSize:  # noqa: N802 -- Qt override
        """The widest single item: narrower than that the flow cannot go."""
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        return size + QSize(
            margins.left() + margins.right(), margins.top() + margins.bottom()
        )

    def _rows(self, width: int) -> list[list[tuple[QLayoutItem, QSize]]]:
        """Split the visible items into rows that fit into *width* pixels."""
        rows: list[list[tuple[QLayoutItem, QSize]]] = []
        row: list[tuple[QLayoutItem, QSize]] = []
        used = 0
        for item in self._items:
            if item.isEmpty():
                continue
            hint = item.sizeHint()
            needed = hint.width() if not row else used + self._h_spacing + hint.width()
            if row and needed > width:
                rows.append(row)
                row = []
                needed = hint.width()
            row.append((item, hint))
            used = needed
        if row:
            rows.append(row)
        return rows

    def _do_layout(self, rect: QRect, test_only: bool) -> int:
        margins = self.contentsMargins()
        area = rect.adjusted(
            margins.left(), margins.top(), -margins.right(), -margins.bottom()
        )
        y = area.y()
        rows = self._rows(area.width())
        for number, row in enumerate(rows):
            line_height = max(hint.height() for _, hint in row)
            if not test_only:
                x = area.x()
                for item, hint in row:
                    # Centre each item on its row: a button and a labelled
                    # spin box do not have the same height.
                    top = y + (line_height - hint.height()) // 2
                    item.setGeometry(QRect(QPoint(x, top), hint))
                    x += hint.width() + self._h_spacing
            y += line_height
            if number < len(rows) - 1:
                y += self._v_spacing
        return y - rect.y() + margins.bottom()
