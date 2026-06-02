"""Shared primitives for background computation in the Optiland GUI."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QRect, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

# Sawtooth cycle length for the timed (indeterminate) progress mode.
# The pie fills 0 % → 99.99 % over this many ticks, then resets instantly.
# At 30 ms/tick, 1000 ticks = 30 seconds per lap — a natural activity signal
# that never plateaus regardless of how long the operation takes.
_TIMED_CYCLE_TICKS = 1000


class BusyOverlay(QWidget):
    """Semi-transparent overlay for a parent widget.

    Always shows a pie-chart style indicator:

    * **Timed mode** (default, no explicit progress set): the pie fills
      according to elapsed time using an exponential curve so the user
      always sees *something* growing, even without real progress data.
    * **Explicit mode**: when :meth:`set_progress` is called with a
      0.0–1.0 value the pie reflects that exact fraction (e.g. during
      print rendering where staged progress is known).

    In both modes a short spinning arc on the outer track confirms the
    operation is still active.

    Place as a direct child of the widget to cover, then call
    ``show_busy()`` / ``hide_busy()`` to control visibility.
    """

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._angle = 0
        self._ticks = 0          # elapsed ticks since show_busy()
        self._progress: float | None = None   # None → use timed fake progress
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self.hide()
        parent.installEventFilter(self)

    def show_busy(self) -> None:
        self._ticks = 0
        self._progress = None
        self.resize(self.parent().size())
        self.raise_()
        self.show()
        self._timer.start(30)

    def hide_busy(self) -> None:
        self._timer.stop()
        self.hide()

    def set_progress(self, value: float | None) -> None:
        """Set the progress fraction (0.0–1.0) or ``None`` for timed mode."""
        self._progress = value
        self.update()

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if obj is self.parent() and event.type() == QEvent.Type.Resize:
            self.resize(event.size())
        return False

    def _tick(self) -> None:
        self._ticks += 1
        self._angle = (self._angle + 8) % 360
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor(0, 0, 0, 90))

        cx, cy = self.width() // 2, self.height() // 2
        r_pie = 26
        r_outer = 38

        # Resolve progress fraction
        if self._progress is not None:
            fraction = max(0.0, min(1.0, self._progress))
        else:
            # Sawtooth: 0.00 % → 99.99 % over one cycle, then resets instantly.
            # Never plateaus regardless of operation duration.
            fraction = (self._ticks % _TIMED_CYCLE_TICKS) / _TIMED_CYCLE_TICKS * 0.9999

        # Dark backing disc
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(30, 30, 40, 210))
        p.drawEllipse(QRect(cx - r_outer - 5, cy - r_outer - 5,
                            2 * (r_outer + 5), 2 * (r_outer + 5)))

        # Track ring (full circle, dim)
        track_pen = QPen(QColor(70, 70, 90, 180), 5)
        track_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(track_pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QRect(cx - r_outer, cy - r_outer,
                            2 * r_outer, 2 * r_outer))

        # Progress pie fill (clockwise from 12 o'clock)
        progress_span = int(fraction * 360 * 16)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(100, 180, 255, 210))
        p.drawPie(QRect(cx - r_pie, cy - r_pie, 2 * r_pie, 2 * r_pie),
                  90 * 16, -progress_span)

        # Percentage label
        p.setPen(QColor(255, 255, 255, 220))
        font = p.font()
        font.setPointSize(7)
        font.setBold(True)
        p.setFont(font)
        p.drawText(QRect(cx - r_pie, cy - r_pie, 2 * r_pie, 2 * r_pie),
                   Qt.AlignmentFlag.AlignCenter,
                   f"{fraction * 100:.2f}%")

        # Outer activity arc (short, spinning)
        spin_pen = QPen(QColor(140, 210, 255, 220), 5)
        spin_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(spin_pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawArc(QRect(cx - r_outer, cy - r_outer,
                        2 * r_outer, 2 * r_outer),
                  int(-self._angle * 16), 80 * 16)

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
