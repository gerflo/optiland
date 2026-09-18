"""Wheel zoom, drag pan and view memory shared with the 2D layout viewer."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

from optiland_gui.widgets.plot_navigation import PlotNavigation


@pytest.fixture
def canvas(qapp):
    figure = Figure(figsize=(4, 3))
    canvas = FigureCanvas(figure)
    ax = figure.add_subplot(111)
    ax.plot([0, 10], [0, 10])
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 10)
    canvas.draw()
    return canvas


def _event(ax, xdata, ydata, **kwargs):
    x, y = ax.transData.transform((xdata, ydata))
    fields = {
        "inaxes": ax,
        "xdata": xdata,
        "ydata": ydata,
        "x": float(x),
        "y": float(y),
        "button": 1,
        "dblclick": False,
        "key": None,
        "step": -1,
    }
    fields.update(kwargs)
    return SimpleNamespace(**fields)


def test_wheel_zoom_keeps_the_point_under_the_cursor(canvas):
    ax = canvas.figure.axes[0]
    nav = PlotNavigation(canvas)
    nav.on_scroll(_event(ax, 2.0, 8.0, step=1))  # zoom in
    x0, x1 = ax.get_xlim()
    y0, y1 = ax.get_ylim()
    assert (x1 - x0) == pytest.approx(10 / 1.1)
    assert (y1 - y0) == pytest.approx(10 / 1.1)
    # The cursor point keeps its relative position in the view.
    assert (2.0 - x0) / (x1 - x0) == pytest.approx(0.2)
    assert (8.0 - y0) / (y1 - y0) == pytest.approx(0.8)
    assert nav.user_changed_view
    nav.on_scroll(_event(ax, 2.0, 8.0, step=-1))  # zoom out again
    assert ax.get_xlim() == pytest.approx((0.0, 10.0))


def test_drag_pan_shifts_the_view(canvas):
    ax = canvas.figure.axes[0]
    nav = PlotNavigation(canvas)
    nav.on_press(_event(ax, 5.0, 5.0))
    nav.on_motion(_event(ax, 6.0, 5.0))
    nav.on_release(_event(ax, 6.0, 5.0))
    x0, x1 = ax.get_xlim()
    assert x0 == pytest.approx(-1.0, abs=0.05) and x1 == pytest.approx(9.0, abs=0.05)
    assert nav.user_changed_view


def test_view_is_remembered_across_a_redraw_and_reset_on_double_click(canvas):
    ax = canvas.figure.axes[0]
    resets = []
    nav = PlotNavigation(canvas, on_reset=lambda: resets.append(True))
    nav.on_scroll(_event(ax, 5.0, 5.0, step=1))
    zoomed = (ax.get_xlim(), ax.get_ylim())

    # A redraw (clear + replot) followed by restore_view brings the zoom back.
    canvas.figure.clear()
    ax2 = canvas.figure.add_subplot(111)
    ax2.plot([0, 10], [0, 10])
    assert nav.restore_view(ax2)
    assert ax2.get_xlim() == pytest.approx(zoomed[0])
    assert ax2.get_ylim() == pytest.approx(zoomed[1])

    nav.on_press(_event(ax2, 1.0, 1.0, dblclick=True))
    assert resets == [True]
    assert not nav.user_changed_view
    assert not nav.restore_view(ax2)


def test_toolbar_mode_suppresses_the_drag_pan(canvas):
    ax = canvas.figure.axes[0]
    nav = PlotNavigation(canvas, coordinate_label=False)
    canvas.toolbar = SimpleNamespace(mode="pan/zoom")
    nav.on_press(_event(ax, 5.0, 5.0))
    nav.on_motion(_event(ax, 7.0, 5.0))
    nav.on_release(_event(ax, 7.0, 5.0))
    assert ax.get_xlim() == pytest.approx((0.0, 10.0))
    assert not nav.user_changed_view
