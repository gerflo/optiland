"""Drive a print preview through page refreshes, in a process of its own.

Run by ``test_print_preview.py`` as ``python -m tests.gui._print_preview_driver
<layout|analysis>`` from the repository root. Switching the orientation in
the print preview used to crash the whole process (an access violation in
Qt), which a test inside the pytest process could not survive to report.

Prints ``refreshed <n>`` and exits with 0 once the preview has been closed.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtPrintSupport import QPrintPreviewDialog, QPrintPreviewWidget
from PySide6.QtWidgets import QApplication

import optiland.backend as be
from optiland.optic import Optic

REFRESHES = 4
STEP_MS = 150
GIVE_UP_MS = 30_000


def _optic() -> Optic:
    optic = Optic()
    optic.surfaces.add(index=0, radius=be.inf, thickness=be.inf)
    optic.surfaces.add(index=1, radius=50.0, thickness=5.0, material="N-BK7")
    optic.surfaces.add(index=2, radius=-50.0, thickness=45.0, is_stop=True)
    optic.surfaces.add(index=3, radius=be.inf, thickness=0.0)
    optic.set_aperture(aperture_type="EPD", value=10.0)
    optic.fields.set_type("angle")
    optic.fields.add(y=0.0)
    optic.wavelengths.add(value=0.55, is_primary=True)
    optic.updater.update()
    return optic


class _DefaultSettings:
    """QSettings stand-in that always answers with the default value."""

    def __init__(self, *_args, **_kwargs) -> None:
        pass

    def value(self, _key: str, default=None, *, type=None):  # noqa: A002, ANN001
        if type is bool:
            return bool(default)
        if type is int:
            return int(default)
        return default

    def setValue(self, _key: str, _value) -> None:  # noqa: ANN001, N802
        return None


class _Connector(QObject):
    opticLoaded = Signal()
    opticChanged = Signal()

    def __init__(self, optic: Optic) -> None:
        super().__init__()
        self._optic = optic
        self.toast_manager = None

    def get_optic(self) -> Optic:
        return self._optic

    def get_effective_optic(self) -> Optic:
        return self._optic

    def get_surface_count(self) -> int:
        return self._optic.surfaces.num_surfaces

    def get_disabled_surface_indices(self) -> set[int]:
        return set()


class _LinePlot:
    def view(self, fig_to_plot_on=None):  # noqa: ANN001
        ax = fig_to_plot_on.add_subplot(111)
        ax.plot([0.0, 1.0], [0.0, 1.0])
        return ax


def _layout_print():  # noqa: ANN202
    import optiland_gui.viewer_panel as viewer_panel

    viewer_panel.QSettings = _DefaultSettings
    viewer = viewer_panel.MatplotlibViewer(_Connector(_optic()))
    viewer.resize(900, 500)
    viewer.show()
    viewer._plot_optic_sync()
    viewer.set_highlighted_surfaces([1, 2], True)
    return viewer, viewer._print_layout


def _analysis_print():  # noqa: ANN202
    from optiland_gui.analysis_panel import AnalysisPanel

    optic = _optic()
    connector = MagicMock()
    connector._optic = optic
    connector.get_optic.return_value = optic
    connector.get_effective_optic.return_value = optic
    connector.toast_manager = MagicMock()
    connector.get_analysis_registry.return_value = []
    panel = AnalysisPanel(connector)
    panel.resize(900, 700)
    panel.show()
    panel.analysis_results_pages.append(
        {
            "name": "Line Plot",
            "analysis_instance": _LinePlot(),
            "plot_type": "embedded_mpl",
            "view_args": {},
            "constructor_args_used": {},
        }
    )
    panel.switch_plot_page(0)
    return panel, panel._print_analysis


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv[:1])
    widget, open_preview = {"layout": _layout_print, "analysis": _analysis_print}[
        sys.argv[1]
    ]()
    refreshed = 0

    def step() -> None:
        nonlocal refreshed
        dialog = next(
            (
                w
                for w in app.topLevelWidgets()
                if isinstance(w, QPrintPreviewDialog) and w.isVisible()
            ),
            None,
        )
        if dialog is None:
            QTimer.singleShot(STEP_MS, step)
            return
        if refreshed >= REFRESHES:
            dialog.reject()
            return
        preview = dialog.findChild(QPrintPreviewWidget)
        # Every switch makes Qt regenerate the pages through paintRequested.
        if refreshed % 2 == 0:
            preview.setLandscapeOrientation()
        else:
            preview.setPortraitOrientation()
        refreshed += 1
        QTimer.singleShot(STEP_MS, step)

    QTimer.singleShot(STEP_MS, step)
    QTimer.singleShot(GIVE_UP_MS, lambda: app.exit(3))
    open_preview()
    print(f"refreshed {refreshed}", flush=True)
    widget.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
