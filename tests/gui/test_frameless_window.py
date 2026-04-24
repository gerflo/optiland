from __future__ import annotations

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QWidget

from optiland_gui.widgets.frameless_window import FramelessWindow


class _BrokenWindowWidget(QWidget):
    def window(self):  # noqa: ANN201
        raise RuntimeError("Internal C++ object already deleted")


def test_frameless_window_event_filter_ignores_deleted_widget_wrappers(qapp):
    window = FramelessWindow()
    window.set_frameless_mode(True)
    broken = _BrokenWindowWidget()
    event = QEvent(QEvent.Type.MouseMove)

    handled = window.eventFilter(broken, event)

    assert handled is False
