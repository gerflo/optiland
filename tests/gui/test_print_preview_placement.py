"""Print previews reopen where they were closed, as large and as oriented.

User request (2026-09-29): the application must always remember the place,
size and page orientation (landscape/portrait) of the different print
preview windows. The 2D layout and every analysis have a preview window of
their own.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QRect, QSettings, QTimer
from PySide6.QtGui import QAction, QPageLayout
from PySide6.QtPrintSupport import QPrintPreviewDialog, QPrintPreviewWidget
from PySide6.QtWidgets import QApplication

from tests.gui.test_layout_selection_highlight import _ConnectorStub, _make_viewer

if TYPE_CHECKING:
    from collections.abc import Callable

LANDSCAPE = QPageLayout.Orientation.Landscape
PORTRAIT = QPageLayout.Orientation.Portrait
POLL_MS = 50
SETTLE_MS = 300
GIVE_UP_MS = 20_000


@dataclass
class _Seen:
    """What a preview window showed just before it was closed."""

    geometry: QRect | None = None
    opened_at: QRect | None = None
    orientation: QPageLayout.Orientation | None = None
    checked_button: str = ""


@pytest.fixture()
def settings_file(tmp_path, monkeypatch):  # noqa: ANN001, ANN201
    """Route the preview's settings to a scratch ini; the user's stay untouched."""
    path = str(tmp_path / "preview.ini")
    monkeypatch.setattr(
        "optiland_gui.print_preview.QSettings",
        lambda *_args: QSettings(path, QSettings.Format.IniFormat),
        raising=False,  # before the fix the module had no settings at all
    )
    return path


def _run_preview(
    open_preview: Callable[[], None],
    geometry: QRect | None = None,
    orientation: QPageLayout.Orientation | None = None,
) -> _Seen:
    """Open a preview, optionally move it and switch its page, then close it.

    Every step runs on timers, so no test ever waits for a click; a preview
    that is still open after ``GIVE_UP_MS`` is closed and the test fails.
    """
    app = QApplication.instance()
    seen = _Seen()
    stuck: list[str] = []

    def dialog() -> QPrintPreviewDialog | None:
        widget = app.activeModalWidget()
        return widget if isinstance(widget, QPrintPreviewDialog) else None

    def change() -> None:
        preview = dialog()
        if preview is None:
            QTimer.singleShot(POLL_MS, change)
            return
        seen.opened_at = preview.geometry()
        if orientation is not None:
            widget = preview.findChild(QPrintPreviewWidget)
            if orientation == LANDSCAPE:
                widget.setLandscapeOrientation()
            else:
                widget.setPortraitOrientation()
        if geometry is not None:
            preview.setGeometry(geometry)
        QTimer.singleShot(SETTLE_MS, close)

    def close() -> None:
        preview = dialog()
        if preview is None:
            return
        seen.geometry = preview.geometry()
        seen.orientation = preview.findChild(QPrintPreviewWidget).orientation()
        seen.checked_button = ",".join(
            action.text()
            for action in preview.findChildren(QAction)
            if action.text() in {"Portrait", "Landscape"} and action.isChecked()
        )
        preview.reject()

    def give_up() -> None:
        preview = dialog()
        if preview is not None:
            stuck.append(preview.windowTitle())
            preview.reject()

    QTimer.singleShot(POLL_MS, change)
    watchdog = QTimer()
    watchdog.setSingleShot(True)
    watchdog.timeout.connect(give_up)
    watchdog.start(GIVE_UP_MS)
    try:
        open_preview()
    finally:
        watchdog.stop()
    assert not stuck, f"preview left open: {stuck}"
    assert seen.geometry is not None, "no print preview was shown"
    return seen


def _free_place(seen: _Seen, shift: int) -> QRect:
    """A place and size clearly apart from where the preview first opened."""
    screen = QApplication.primaryScreen().availableGeometry()
    width = max(500, min(screen.width() - 200, seen.opened_at.width() - 150 + shift))
    height = max(400, min(screen.height() - 200, seen.opened_at.height() - 100))
    return QRect(screen.x() + 60 + shift, screen.y() + 50 + shift, width, height)


@pytest.fixture()
def layout_viewer(qapp, minimal_optic, monkeypatch):  # noqa: ANN001, ANN201
    viewer = _make_viewer(monkeypatch, _ConnectorStub(minimal_optic))
    viewer.resize(900, 500)
    yield viewer
    viewer.close()
    viewer.deleteLater()


class _LinePlot:
    def view(self, fig_to_plot_on=None):  # noqa: ANN001, ANN202
        ax = fig_to_plot_on.add_subplot(111)
        ax.plot([0.0, 1.0], [0.0, 1.0])
        return ax


@pytest.fixture()
def analysis_panel(qapp, minimal_optic):  # noqa: ANN001, ANN201
    from optiland_gui.analysis_panel import AnalysisPanel

    connector = MagicMock()
    connector._optic = minimal_optic
    connector.get_optic.return_value = minimal_optic
    connector.get_effective_optic.return_value = minimal_optic
    connector.toast_manager = MagicMock()
    connector.get_analysis_registry.return_value = []
    panel = AnalysisPanel(connector)
    panel.resize(900, 700)
    for name in ("Line Plot A", "Line Plot B"):
        panel.analysis_results_pages.append(
            {
                "name": name,
                "analysis_instance": _LinePlot(),
                "plot_type": "embedded_mpl",
                "view_args": {},
                "constructor_args_used": {},
            }
        )
    yield panel
    panel.close()
    panel.deleteLater()


def test_layout_preview_reopens_where_it_was_closed(
    qapp, settings_file, layout_viewer
) -> None:
    first = _run_preview(layout_viewer._print_layout)
    place = _free_place(first, 0)
    moved = _run_preview(layout_viewer._print_layout, place, LANDSCAPE)
    assert moved.orientation == LANDSCAPE
    assert moved.geometry != first.opened_at

    reopened = _run_preview(layout_viewer._print_layout)

    assert reopened.opened_at == moved.geometry
    assert reopened.orientation == LANDSCAPE
    assert reopened.checked_button == "Landscape"

    # And back: portrait is remembered as well, not only landscape.
    _run_preview(layout_viewer._print_layout, orientation=PORTRAIT)
    portrait = _run_preview(layout_viewer._print_layout)
    assert (portrait.orientation, portrait.checked_button) == (PORTRAIT, "Portrait")


def test_each_analysis_preview_keeps_its_own_place_and_orientation(
    qapp, settings_file, analysis_panel, layout_viewer
) -> None:
    def preview_of(page: int) -> Callable[[], None]:
        def open_preview() -> None:
            analysis_panel.switch_plot_page(page)
            analysis_panel._print_analysis()

        return open_preview

    first = _run_preview(preview_of(0))
    a = _run_preview(preview_of(0), _free_place(first, 0), LANDSCAPE)
    b = _run_preview(preview_of(1), _free_place(first, 80), PORTRAIT)
    layout = _run_preview(layout_viewer._print_layout, _free_place(first, 40), PORTRAIT)
    assert len({(g.x(), g.y()) for g in (a.geometry, b.geometry, layout.geometry)}) == 3

    again_a = _run_preview(preview_of(0))
    again_b = _run_preview(preview_of(1))
    again_layout = _run_preview(layout_viewer._print_layout)

    assert (again_a.opened_at, again_a.orientation) == (a.geometry, LANDSCAPE)
    assert (again_b.opened_at, again_b.orientation) == (b.geometry, PORTRAIT)
    assert (again_layout.opened_at, again_layout.orientation) == (
        layout.geometry,
        PORTRAIT,
    )
