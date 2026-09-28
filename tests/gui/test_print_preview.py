"""Print preview: page refreshes must not crash, and the page is laid out whole.

Regression (2026-09-25): switching the orientation in the print preview of
the 2D layout (and of an analysis plot) killed the application with an
access violation in Qt6Core. The render handler processed events for its
progress display after opening a painter on the printer; that painter had
already deleted the pages the preview still showed, and the repaint read
freed memory. The page is now rendered once, before the preview opens, and
the preview only draws it.
"""

from __future__ import annotations

import math
import subprocess
import sys
from pathlib import Path

import pytest
from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QImage, QPainter

from optiland_gui.print_preview import (
    LEGEND_MAX_HEIGHT_FRACTION,
    LegendEntry,
    PrintPage,
    draw_page,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DOTS_PER_METER_150_DPI = 5906
MARGIN = 40


@pytest.mark.parametrize("panel", ["layout", "analysis"])
def test_preview_survives_orientation_switches(panel: str) -> None:
    """The preview can be switched back and forth and closed without a crash."""
    result = subprocess.run(
        [sys.executable, "-m", "tests.gui._print_preview_driver", panel],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert result.returncode == 0, (result.returncode, result.stderr[-2000:])
    assert "refreshed 4" in result.stdout


def _image(width: int, height: int) -> QImage:
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(QColor("steelblue"))
    return image


def _draw(page: PrintPage, width: int, height: int):  # noqa: ANN202
    """Draw *page* on a white 150 dpi sheet; return the sheet, area and layout."""
    sheet = QImage(width, height, QImage.Format.Format_RGB32)
    sheet.fill(QColor("white"))
    sheet.setDotsPerMeterX(DOTS_PER_METER_150_DPI)
    sheet.setDotsPerMeterY(DOTS_PER_METER_150_DPI)
    area = QRectF(MARGIN, MARGIN, width - 2 * MARGIN, height - 2 * MARGIN)
    painter = QPainter(sheet)
    try:
        layout = draw_page(painter, area, page)
    finally:
        painter.end()
    return sheet, area, layout


A4_LANDSCAPE = (1754, 1240)
A4_PORTRAIT = (1240, 1754)
LEGEND = tuple(
    LegendEntry(number, label)
    for number, label in enumerate(
        [
            "Curved object surface, focus preset for the test; R2.500 (S0)",
            "Equivalent model lens 550 nm (literature) (S1⁠–⁠S4)",
            "ASPHERE-18-TEST (S5⁠–⁠S6)",
            "Fold mirror projected camera hole D2.000; 45-degree physical "
            "elliptical hole, outer diameter 30 mm (S7)",
            "ACHROMAT-01 (S8⁠–⁠S10)",
            "PCX-LENS-02 (S11⁠–⁠S12)",
            "Image sensor (6.000 x 5.000 mm) (S13)",
        ],
        start=1,
    )
)


def _inside(inner: QRectF, outer: QRectF) -> bool:
    return (
        inner.left() >= outer.left() - 0.5
        and inner.top() >= outer.top() - 0.5
        and inner.right() <= outer.right() + 0.5
        and inner.bottom() <= outer.bottom() + 0.5
    )


@pytest.mark.parametrize("sheet_size", [A4_LANDSCAPE, A4_PORTRAIT])
@pytest.mark.parametrize("image_size", [(2000, 900), (900, 2000)])
def test_plot_without_legend_fills_the_page(qapp, sheet_size, image_size) -> None:
    _, area, layout = _draw(PrintPage(_image(*image_size)), *sheet_size)

    rect = layout.image_rect
    assert _inside(rect, area)
    assert math.isclose(rect.width(), area.width(), abs_tol=1.0) or math.isclose(
        rect.height(), area.height(), abs_tol=1.0
    )
    assert math.isclose(rect.center().x(), area.center().x(), abs_tol=1.0)
    assert math.isclose(rect.center().y(), area.center().y(), abs_tol=1.0)
    assert math.isclose(
        rect.width() / rect.height(), image_size[0] / image_size[1], rel_tol=1e-3
    )
    assert layout.entry_rects == ()


@pytest.mark.parametrize("sheet_size", [A4_LANDSCAPE, A4_PORTRAIT])
def test_legend_sits_under_the_plot_within_the_page(qapp, sheet_size) -> None:
    _, area, layout = _draw(PrintPage(_image(2000, 900), LEGEND), *sheet_size)

    rect = layout.image_rect
    entries = layout.entry_rects
    assert len(entries) == len(LEGEND)
    assert _inside(rect, area)
    for entry in entries:
        assert _inside(entry, area)
        assert entry.top() > rect.bottom()
    for index, first in enumerate(entries):
        for second in entries[index + 1 :]:
            assert not first.intersects(second)
    # The plot takes all the room the legend leaves: the full width, or the
    # full height above the legend.
    block_height = max(entry.bottom() for entry in entries) - rect.top()
    assert math.isclose(rect.width(), area.width(), abs_tol=1.0) or math.isclose(
        block_height, area.height(), abs_tol=1.0
    )
    # Numbers run down the columns.
    lefts = sorted({round(entry.left()) for entry in entries})
    assert entries[0].left() == min(entry.left() for entry in entries)
    assert len(lefts) >= 2
    assert entries[1].top() > entries[0].top()


def test_long_legend_leaves_most_of_the_page_to_the_plot(qapp) -> None:
    legend = tuple(LegendEntry(n, f"Catalog lens LA{1000 + n}-A") for n in range(40))

    _, area, layout = _draw(PrintPage(_image(2000, 900), legend), *A4_LANDSCAPE)

    legend_top = min(entry.top() for entry in layout.entry_rects)
    legend_bottom = max(entry.bottom() for entry in layout.entry_rects)
    assert legend_bottom - legend_top <= LEGEND_MAX_HEIGHT_FRACTION * area.height()
    assert all(_inside(entry, area) for entry in layout.entry_rects)


def test_legend_entries_are_drawn(qapp) -> None:
    sheet, _, layout = _draw(PrintPage(_image(2000, 900), LEGEND), *A4_LANDSCAPE)

    for entry in layout.entry_rects:
        dark = 0
        for x in range(int(entry.left()), int(entry.right()), 2):
            for y in range(int(entry.top()), int(entry.bottom()), 2):
                if QColor(sheet.pixel(x, y)).lightness() < 100:
                    dark += 1
        assert dark > 20  # circle, number and label
