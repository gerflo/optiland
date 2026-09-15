"""Embedded spot diagrams arrange their square boxes to suit the canvas."""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")

import pytest
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

import optiland.analysis.spot_diagram.core as spot_core
from optiland.analysis import SpotDiagram
from optiland.samples.objectives import CookeTriplet


def _spot_diagram(num_fields: int) -> SpotDiagram:
    fields = [(0.0, i / max(1, num_fields - 1)) for i in range(num_fields)]
    return SpotDiagram(
        CookeTriplet(), fields=fields, wavelengths="primary", num_rings=3
    )


def _draw(spot: SpotDiagram, size: tuple[float, float]) -> Figure:
    figure = Figure(figsize=size, dpi=100)
    FigureCanvasAgg(figure)
    spot.view(fig_to_plot_on=figure)
    figure.tight_layout()
    figure.canvas.draw()
    return figure


def _box_side(figure: Figure) -> float:
    return min(ax.bbox.width for ax in figure.axes)


@pytest.mark.parametrize(
    ("num_fields", "size"),
    [(1, (8, 6)), (2, (6, 9)), (3, (6, 9)), (4, (12, 5)), (6, (6, 9))],
)
def test_spot_boxes_are_as_large_as_the_canvas_allows(
    monkeypatch, num_fields, size
) -> None:
    spot = _spot_diagram(num_fields)
    side = _box_side(_draw(spot, size))

    largest = 0.0
    for num_cols in range(1, num_fields + 1):
        num_rows = -(-num_fields // num_cols)

        def grid(_num_fields, fig, _figsize, rows=num_rows, cols=num_cols):  # noqa: ANN001
            fig.clear()
            axs = fig.subplots(rows, cols, sharex=True, sharey=True, squeeze=False)
            return fig, axs.flatten()

        monkeypatch.setattr(spot_core, "setup_plot_layout", grid)
        largest = max(largest, _box_side(_draw(spot, size)))

    assert side >= 0.9 * largest


def test_a_box_without_a_neighbour_below_labels_its_x_axis() -> None:
    # Three fields in a roomy canvas share a 2 x 2 grid with one empty cell.
    figure = _draw(_spot_diagram(3), (10, 8))
    assert figure.axes[0].get_gridspec().get_geometry() == (2, 2)

    top_right = figure.axes[1]
    assert any(
        label.get_visible() and label.get_text()
        for label in top_right.get_xticklabels()
    )
