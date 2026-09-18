"""Mouse navigation for an embedded Matplotlib canvas.

The 2D layout viewer lets the user zoom with the wheel around the cursor,
pan with a left drag, read the cursor position and go back to the full
view. :class:`PlotNavigation` gives any other canvas the same behaviour
without copying the viewer, and remembers a user-chosen view so a redraw
(after an edit, a trace, a theme change) does not throw it away.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel

if TYPE_CHECKING:
    from collections.abc import Callable

_ZOOM_STEP = 1.1


class PlotNavigation:
    """Wheel zoom, drag pan, cursor read-out and view memory for one canvas.

    Args:
        canvas: A ``FigureCanvasQTAgg``.
        on_reset: Called on a double click; typically redraws with the full
            view. When ``None`` the double click only autoscale the axes.
        coordinate_label: Show the cursor position in the lower left corner.

    Attributes:
        user_changed_view: True once the user zoomed or panned; cleared by
            :meth:`forget_view`.
    """

    def __init__(
        self,
        canvas,
        on_reset: Callable[[], None] | None = None,
        coordinate_label: bool = True,
    ) -> None:
        self.canvas = canvas
        self.on_reset = on_reset
        self.user_changed_view = False
        self._view: tuple[tuple[float, float], tuple[float, float]] | None = None
        self._pan_button: int | None = None
        self._pan_axes = None
        self._label: QLabel | None = None
        if coordinate_label:
            self._label = QLabel(canvas)
            self._label.setObjectName("PlotCursorLabel")
            self._label.setStyleSheet(
                "QLabel { background: rgba(0, 0, 0, 120); color: white; "
                "padding: 2px 6px; border-radius: 3px; }"
            )
            self._label.setVisible(False)
        canvas.mpl_connect("scroll_event", self.on_scroll)
        canvas.mpl_connect("button_press_event", self.on_press)
        canvas.mpl_connect("button_release_event", self.on_release)
        canvas.mpl_connect("motion_notify_event", self.on_motion)

    # -- view memory ---------------------------------------------------------

    def remember_view(self, ax) -> None:
        """Store the current limits of ``ax`` as the user's view."""
        self._view = (tuple(ax.get_xlim()), tuple(ax.get_ylim()))
        self.user_changed_view = True

    def restore_view(self, ax) -> bool:
        """Re-apply the remembered limits to ``ax``; False when there are none."""
        if self._view is None:
            return False
        ax.set_xlim(*self._view[0])
        ax.set_ylim(*self._view[1])
        return True

    def forget_view(self) -> None:
        """Drop the remembered view (the next redraw shows everything)."""
        self._view = None
        self.user_changed_view = False

    # -- events --------------------------------------------------------------

    def _toolbar_active(self) -> bool:
        toolbar = getattr(self.canvas, "toolbar", None)
        return bool(getattr(toolbar, "mode", ""))

    def on_scroll(self, event) -> None:
        """Zoom about the cursor by :data:`_ZOOM_STEP` per wheel step."""
        ax = event.inaxes
        if ax is None or event.xdata is None or event.ydata is None:
            return
        scale = _ZOOM_STEP if event.step < 0 else 1.0 / _ZOOM_STEP
        x0, x1 = ax.get_xlim()
        y0, y1 = ax.get_ylim()
        width = (x1 - x0) * scale
        height = (y1 - y0) * scale
        rel_x = (x1 - event.xdata) / (x1 - x0) if x1 != x0 else 0.5
        rel_y = (y1 - event.ydata) / (y1 - y0) if y1 != y0 else 0.5
        ax.set_xlim(event.xdata - width * (1.0 - rel_x), event.xdata + width * rel_x)
        ax.set_ylim(event.ydata - height * (1.0 - rel_y), event.ydata + height * rel_y)
        self.remember_view(ax)
        self.canvas.draw_idle()

    def on_press(self, event) -> None:
        """Start a left-drag pan; a double click resets the view."""
        if event.inaxes is None or self._toolbar_active():
            return
        if event.dblclick and event.button == 1:
            self.forget_view()
            if self.on_reset is not None:
                self.on_reset()
            else:
                event.inaxes.autoscale()
                self.canvas.draw_idle()
            return
        if event.button == 1:
            event.inaxes.start_pan(event.x, event.y, event.button)
            self._pan_button = event.button
            self._pan_axes = event.inaxes
            self.canvas.setCursor(Qt.CursorShape.ClosedHandCursor)

    def on_motion(self, event) -> None:
        """Continue a pan and update the cursor read-out."""
        if self._pan_axes is not None and self._pan_button is not None:
            self._pan_axes.drag_pan(self._pan_button, event.key, event.x, event.y)
            self.canvas.draw_idle()
        if self._label is None:
            return
        if event.inaxes is not None and event.xdata is not None:
            self._label.setText(f"({event.xdata:.3f}, {event.ydata:.3f})")
            self._label.adjustSize()
            self._label.move(6, self.canvas.height() - self._label.height() - 6)
            self._label.setVisible(True)
            self._label.raise_()
        else:
            self._label.setVisible(False)

    def on_release(self, event) -> None:
        """End a pan and remember the resulting view."""
        if self._pan_axes is None:
            return
        ax = self._pan_axes
        ax.end_pan()
        self._pan_axes = None
        self._pan_button = None
        self.canvas.setCursor(Qt.CursorShape.ArrowCursor)
        self.remember_view(ax)
        self.canvas.draw_idle()
