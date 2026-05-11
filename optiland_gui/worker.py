"""Shared primitives for background computation in the Optiland GUI."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QRect, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget


class BusyOverlay(QWidget):
    """Semi-transparent spinning-arc overlay for a parent widget.

    Place as a direct child of the widget to cover, then call
    ``show_busy()`` / ``hide_busy()`` to control visibility.
    """

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._angle = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self.hide()
        parent.installEventFilter(self)

    def show_busy(self) -> None:
        self.resize(self.parent().size())
        self.raise_()
        self.show()
        self._timer.start(30)

    def hide_busy(self) -> None:
        self._timer.stop()
        self.hide()

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if obj is self.parent() and event.type() == QEvent.Type.Resize:
            self.resize(event.size())
        return False

    def _tick(self) -> None:
        self._angle = (self._angle + 8) % 360
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor(0, 0, 0, 90))
        r = 30
        cx, cy = self.width() // 2, self.height() // 2
        pen = QPen(QColor(100, 180, 255), 6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        rect = QRect(cx - r, cy - r, 2 * r, 2 * r)
        p.drawArc(rect, int(-self._angle * 16), 270 * 16)
        p.end()


class _Worker(QObject):
    """Runs a zero-argument callable in a QThread, emits result or exception."""

    finished = Signal(object)
    error = Signal(object)

    def __init__(self, fn) -> None:
        super().__init__()
        self._fn = fn

    @Slot()
    def run(self) -> None:
        try:
            self.finished.emit(self._fn())
        except Exception as exc:  # noqa: BLE001
            self.error.emit(exc)
