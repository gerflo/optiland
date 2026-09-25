"""Print preview of a rendered plot, with an optional numbered legend.

Shared by the 2D layout and the analysis plots. The page content is rendered
once, before the preview opens; the preview then only draws it, however
often Qt regenerates its pages (orientation, paper size, Print).

Nothing here may process events while Qt regenerates the preview: opening a
``QPainter`` on the printer deletes the pages the preview widget still
shows, and a repaint in that window reads freed memory. A progress display
that did so crashed the application whenever the orientation was switched.
"""

from __future__ import annotations

import contextlib
import logging
import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

import shiboken6
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter, QPen
from PySide6.QtWidgets import QApplication, QMessageBox, QStyleFactory, QWidget

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

logger = logging.getLogger(__name__)

LEGEND_FONT_PT = 8.0
LEGEND_MAX_COLUMNS = 4
# The plot keeps at least the rest of the page height; a longer legend is
# spread over more columns instead.
LEGEND_MAX_HEIGHT_FRACTION = 0.4
# A legend column is at least this many average characters wide, unless no
# entry needs that much.
LEGEND_MIN_COLUMN_CHARS = 40
# Circled number diameter, and the gaps, in multiples of the font height.
LEGEND_MARKER_SCALE = 1.3
LEGEND_ROW_GAP = 0.35
LEGEND_COLUMN_GAP = 2.0
LEGEND_TOP_GAP = 1.0

# Qt's toolbar icons are dark and made for light backgrounds, so the preview
# uses the light Fusion palette; the rules below override those of the app's
# dark theme that would otherwise bleed into the dialog.
_PREVIEW_STYLESHEET = """
    QWidget          { background-color: #f0f0f0; color: #202020; }
    QToolBar         { background-color: #ececec; border: none; spacing: 2px; }
    QToolBar::separator { width: 1px; background-color: #c8c8c8;
                          margin: 4px 2px; }
    QToolButton      { color: #202020; background-color: transparent;
                       border: 1px solid transparent; padding: 2px;
                       border-radius: 2px; }
    QToolButton:hover    { background-color: #dce9f7; border-color: #7ab3e0; }
    QToolButton:pressed,
    QToolButton:checked  { background-color: #b8d0ea; border-color: #4e8cc0; }
    QToolButton:disabled { color: #909090; }
    QPushButton      { background-color: #e1e1e1; color: #202020;
                       border: 1px solid #adadad; border-radius: 3px;
                       padding: 4px 12px; }
    QPushButton:hover    { background-color: #dce9f7; border-color: #7ab3e0; }
    QPushButton:pressed  { background-color: #b8d0ea; border-color: #4e8cc0; }
    QPushButton:default  { border-color: #0078d7; }
    QPushButton:disabled { background-color: #d4d4d4; color: #888888;
                           border-color: #d4d4d4; }
    QLabel           { color: #202020; background-color: transparent; }
    QCheckBox, QRadioButton, QGroupBox { color: #202020; }
    QGroupBox        { border: 1px solid #b0b0b0; border-radius: 4px;
                       margin-top: 8px; padding-top: 8px; }
    QGroupBox::title { color: #202020; }
    QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
        background-color: #ffffff; color: #202020;
        border: 1px solid #aaaaaa; border-radius: 2px; padding: 1px 4px; }
    QComboBox::drop-down { background-color: #e1e1e1;
                           border-left: 1px solid #aaaaaa; }
    QAbstractItemView{ background-color: #ffffff; color: #202020;
                       border: 1px solid #aaaaaa; }
    QScrollBar:vertical, QScrollBar:horizontal {
        background-color: #e8e8e8; border: none; }
    QScrollBar::handle:vertical   { background-color: #b0b0b0;
                                    border-radius: 3px; min-height: 20px; }
    QScrollBar::handle:horizontal { background-color: #b0b0b0;
                                    border-radius: 3px; min-width:  20px; }
    QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {
        background-color: #909090; }
    QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }
"""


@dataclass(frozen=True)
class LegendEntry:
    """One numbered line of the legend under a printed plot."""

    number: int
    label: str


@dataclass(frozen=True)
class PrintPage:
    """What a printed page shows: the plot image and the legend under it."""

    image: QImage
    legend: tuple[LegendEntry, ...] = ()


@dataclass(frozen=True)
class PageLayout:
    """Where :func:`draw_page` put the plot and the legend, in device pixels."""

    image_rect: QRectF
    entry_rects: tuple[QRectF, ...]


@dataclass(frozen=True)
class _LegendMetrics:
    """Sizes of the legend parts on one paint device, in device pixels."""

    font: QFont
    metrics: QFontMetricsF
    marker: float
    marker_gap: float
    row_gap: float
    column_gap: float
    top_gap: float

    @classmethod
    def for_painter(cls, painter: QPainter) -> _LegendMetrics:
        font = QFont(painter.font())
        font.setPointSizeF(LEGEND_FONT_PT)
        metrics = QFontMetricsF(font, painter.device())
        height = metrics.height()
        return cls(
            font=font,
            metrics=metrics,
            marker=LEGEND_MARKER_SCALE * height,
            marker_gap=0.5 * height,
            row_gap=LEGEND_ROW_GAP * height,
            column_gap=LEGEND_COLUMN_GAP * height,
            top_gap=LEGEND_TOP_GAP * height,
        )

    def text_offset(self) -> float:
        """Distance from the marker's left edge to the label text."""
        return self.marker + self.marker_gap

    def label_height(self, label: str, width: float) -> float:
        rect = self.metrics.boundingRect(
            QRectF(0.0, 0.0, max(width, 1.0), 1e9),
            int(Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap),
            label,
        )
        return rect.height()

    def entry_height(self, label: str, column_width: float) -> float:
        text_top = max(0.0, 0.5 * (self.marker - self.metrics.height()))
        text = self.label_height(label, column_width - self.text_offset())
        return max(self.marker, text_top + text)


def _legend_rects(
    legend: Sequence[LegendEntry],
    width: float,
    max_height: float,
    sizes: _LegendMetrics,
) -> list[QRectF]:
    """Entry rectangles of a legend *width* wide, relative to its top left.

    The entries run down the columns in order. The fewest columns that are
    at least ``LEGEND_MIN_COLUMN_CHARS`` wide are used, more when the legend
    would otherwise take more than *max_height*.
    """
    count = len(legend)
    natural = max(
        sizes.text_offset() + sizes.metrics.horizontalAdvance(entry.label)
        for entry in legend
    )
    minimum = min(
        natural,
        sizes.text_offset()
        + LEGEND_MIN_COLUMN_CHARS * sizes.metrics.averageCharWidth(),
    )
    fitting = int((width + sizes.column_gap) // (minimum + sizes.column_gap))
    first = max(1, min(fitting, LEGEND_MAX_COLUMNS, count))
    best: list[QRectF] | None = None
    best_height = math.inf
    for columns in range(first, max(first, min(LEGEND_MAX_COLUMNS, count)) + 1):
        rects = _column_major_rects(legend, width, columns, sizes)
        height = max(rect.bottom() for rect in rects)
        if height < best_height:
            best, best_height = rects, height
        if height <= max_height:
            break
    return best or []


def _column_major_rects(
    legend: Sequence[LegendEntry], width: float, columns: int, sizes: _LegendMetrics
) -> list[QRectF]:
    per_column = math.ceil(len(legend) / columns)
    column_width = (width - (columns - 1) * sizes.column_gap) / columns
    rects = []
    y = 0.0
    for index, entry in enumerate(legend):
        column, row = divmod(index, per_column)
        if row == 0:
            y = 0.0
        height = sizes.entry_height(entry.label, column_width)
        x = column * (column_width + sizes.column_gap)
        rects.append(QRectF(x, y, column_width, height))
        y += height + sizes.row_gap
    return rects


def _fit(size_w: float, size_h: float, width: float, height: float) -> float:
    """Scale that fits a ``size_w`` x ``size_h`` box into ``width`` x ``height``."""
    if size_w <= 0 or size_h <= 0:
        return 0.0
    return max(0.0, min(width / size_w, height / size_h))


def layout_page(
    area: QRectF,
    image_w: float,
    image_h: float,
    legend: Sequence[LegendEntry],
    sizes: _LegendMetrics,
) -> PageLayout:
    """Place the plot as large as the page allows, the legend right under it.

    Without a legend the plot is centred on the page. With one, plot and
    legend are centred together; the legend is as wide as the plot (the
    page when the plot fills its width) and gets at most
    ``LEGEND_MAX_HEIGHT_FRACTION`` of the page height where columns allow.
    """
    if not legend:
        scale = _fit(image_w, image_h, area.width(), area.height())
        w, h = image_w * scale, image_h * scale
        rect = QRectF(
            area.x() + 0.5 * (area.width() - w),
            area.y() + 0.5 * (area.height() - h),
            w,
            h,
        )
        return PageLayout(rect, ())

    max_legend = LEGEND_MAX_HEIGHT_FRACTION * area.height()
    legend_width = area.width()
    for _ in range(2):
        rects = _legend_rects(legend, legend_width, max_legend, sizes)
        legend_height = max(rect.bottom() for rect in rects)
        room = area.height() - legend_height - sizes.top_gap
        scale = _fit(image_w, image_h, area.width(), room)
        w, h = image_w * scale, image_h * scale
        if w >= legend_width - 0.5:
            break
        # A plot narrower than the page: keep the legend under the plot, but
        # never squeeze it below half the page width.
        legend_width = max(w, 0.5 * area.width())
    block = h + sizes.top_gap + legend_height
    top = area.y() + max(0.0, 0.5 * (area.height() - block))
    image_rect = QRectF(area.x() + 0.5 * (area.width() - w), top, w, h)
    legend_left = area.x() + 0.5 * (area.width() - legend_width)
    legend_top = image_rect.bottom() + sizes.top_gap
    entry_rects = tuple(rect.translated(legend_left, legend_top) for rect in rects)
    return PageLayout(image_rect, entry_rects)


def draw_page(painter: QPainter, area: QRectF, page: PrintPage) -> PageLayout:
    """Draw *page* into *area* of an active painter.

    Returns:
        Where the plot and each legend entry went.
    """
    sizes = _LegendMetrics.for_painter(painter)
    layout = layout_page(
        area, page.image.width(), page.image.height(), page.legend, sizes
    )
    painter.save()
    try:
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawImage(layout.image_rect, page.image)
        _draw_legend(painter, page.legend, layout.entry_rects, sizes)
    finally:
        painter.restore()
    return layout


def _draw_legend(
    painter: QPainter,
    legend: Sequence[LegendEntry],
    rects: Sequence[QRectF],
    sizes: _LegendMetrics,
) -> None:
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setFont(sizes.font)
    pen = QPen(QColor("black"))
    pen.setWidthF(max(1.0, 0.06 * sizes.marker))
    text_top = max(0.0, 0.5 * (sizes.marker - sizes.metrics.height()))
    for entry, rect in zip(legend, rects, strict=True):
        marker = QRectF(rect.x(), rect.y(), sizes.marker, sizes.marker)
        painter.setPen(pen)
        painter.setBrush(QColor("white"))
        painter.drawEllipse(marker)
        painter.drawText(marker, int(Qt.AlignmentFlag.AlignCenter), str(entry.number))
        text = QRectF(
            QPointF(rect.x() + sizes.text_offset(), rect.y() + text_top),
            QPointF(rect.right(), rect.bottom()),
        )
        painter.drawText(
            text,
            int(
                Qt.AlignmentFlag.AlignLeft
                | Qt.AlignmentFlag.AlignTop
                | Qt.TextFlag.TextWordWrap
            ),
            entry.label,
        )


def paint_page(printer, page: PrintPage) -> None:
    """Draw *page* onto *printer*, the target of ``paintRequested``.

    Must not process events: see the module docstring.
    """
    painter = QPainter(printer)
    if not painter.isActive():
        return
    try:
        draw_page(painter, QRectF(painter.viewport()), page)
    finally:
        painter.end()


def show_print_preview(
    parent: QWidget, title: str, render: Callable[[], PrintPage]
) -> None:
    """Render a page once, then show it in a print preview dialog.

    Args:
        parent: The widget the dialog belongs to.
        title: The dialog's window title.
        render: Builds the page; called once, under a wait cursor, before
            the dialog opens.
    """
    try:
        from PySide6.QtPrintSupport import QPrinter, QPrintPreviewDialog
    except ImportError:
        QMessageBox.warning(
            parent, "Print", "Print support is not available on this system."
        )
        return

    QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
    try:
        page = render()
    except Exception as exc:  # noqa: BLE001 -- printing must not take the GUI down
        logger.error("Could not render the plot for printing: %s", exc, exc_info=True)
        return
    finally:
        QApplication.restoreOverrideCursor()
    if page.image.isNull():
        logger.error("Could not render the plot for printing.")
        return

    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    preview = QPrintPreviewDialog(printer, parent)
    try:
        preview.setWindowTitle(title)
        fusion = QStyleFactory.create("Fusion")
        if fusion:
            preview.setStyle(fusion)
            preview.setPalette(fusion.standardPalette())
        preview.setStyleSheet(_PREVIEW_STYLESHEET)
        preview.paintRequested.connect(lambda device: paint_page(device, page))
        _print_with_preview_page_layout(preview, printer)
        preview.exec()
    finally:
        # Delete the dialog while the printer it points to still exists.
        shiboken6.delete(preview)


def _print_with_preview_page_layout(preview, printer) -> None:
    """Make the preview's Print button keep the page layout chosen there.

    On Windows QPrintDialog re-reads the printer driver's DEVMODE when it
    opens, which resets the orientation to the driver default (usually
    portrait) whatever the preview showed. The layout is saved before the
    dialog and restored after it is accepted.
    """
    from PySide6.QtGui import QAction
    from PySide6.QtPrintSupport import QPrintDialog

    def print_page() -> None:
        saved_layout = printer.pageLayout()
        dialog = QPrintDialog(printer, preview)
        if dialog.exec():
            printer.setPageLayout(saved_layout)
            preview.paintRequested.emit(printer)

    for action in preview.findChildren(QAction, "qt_print_action"):
        with contextlib.suppress(RuntimeError):
            action.triggered.disconnect()
        action.triggered.connect(print_page)
        break
