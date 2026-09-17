"""Non-sequential (NSQ) panel: beam splitters, multi-path illumination.

Hosts an :class:`~optiland_gui.services.nsq_service.NSQService` document
and shows its scene as a 2D layout with recorded ray paths, the detector
irradiance maps and an energy-balance summary. Traces run on a worker
thread; the panel only draws.

Author: Optiland contributors, 2026
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from . import gui_plot_utils
from .analysis_panel import CustomMatplotlibToolbar
from .services.nsq_service import NSQService
from .worker import BusyOverlay

if TYPE_CHECKING:
    from optiland.nonsequential.tracer import SimulationResult

logger = logging.getLogger(__name__)

_PROJECTIONS = ("XZ", "YZ", "XY")


class NSQPanel(QWidget):
    """Dockable panel for non-sequential scenes.

    Args:
        connector: The GUI connector; only its optional ``toast_manager``
            is used for notifications.
        service: The NSQ document service. A fresh one is created when
            ``None``.
        parent: Optional parent widget.
    """

    def __init__(
        self,
        connector,
        service: NSQService | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.connector = connector
        self.service = service if service is not None else NSQService(self)
        self.current_theme = "dark"

        self._build_ui()
        self.service.sceneChanged.connect(self._on_scene_changed)
        self.service.traceStarted.connect(self._on_trace_started)
        self.service.traceFinished.connect(self._on_trace_finished)
        self.service.traceFailed.connect(self._on_trace_failed)

        if self.service.scene is None:
            self.service.load_sample(self.scene_combo.currentData())
        else:
            self._on_scene_changed()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        from optiland.samples.nonsequential import SAMPLE_SCENES  # noqa: PLC0415

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        # Row 1: scene selection ------------------------------------------
        scene_row = QHBoxLayout()
        scene_row.addWidget(QLabel("Scene:"))
        self.scene_combo = QComboBox()
        self.scene_combo.setObjectName("NSQSceneCombo")
        for key, label in SAMPLE_SCENES.items():
            self.scene_combo.addItem(label, key)
        self.scene_combo.activated.connect(self._on_sample_selected)
        scene_row.addWidget(self.scene_combo, 1)

        self.open_button = QPushButton("Open JSON...")
        self.open_button.setObjectName("NSQOpenButton")
        self.open_button.clicked.connect(self._on_open_clicked)
        scene_row.addWidget(self.open_button)

        self.save_button = QPushButton("Save JSON...")
        self.save_button.setObjectName("NSQSaveButton")
        self.save_button.clicked.connect(self._on_save_clicked)
        scene_row.addWidget(self.save_button)
        root.addLayout(scene_row)

        # Row 2: trace controls --------------------------------------------
        controls = QHBoxLayout()

        def _spin(label: str, lo: int, hi: int, value: int, name: str) -> QSpinBox:
            controls.addWidget(QLabel(label))
            box = QSpinBox()
            box.setObjectName(name)
            box.setRange(lo, hi)
            box.setValue(value)
            box.setAccelerated(True)
            controls.addWidget(box)
            return box

        self.rays_spin = _spin("Rays:", 100, 20_000_000, 20_000, "NSQRaysSpin")
        self.rays_spin.setSingleStep(1000)
        self.seed_spin = _spin("Seed:", 0, 2_000_000_000, 7, "NSQSeedSpin")
        self.depth_spin = _spin("Max depth:", 1, 256, 16, "NSQDepthSpin")
        self.split_spin = _spin("Split depth:", 0, 8, 0, "NSQSplitSpin")
        self.split_spin.setToolTip(
            "0: one branch per hit, chosen by roulette.\n"
            "n > 0: follow both reflected and transmitted branches for the "
            "first n hits of every ray (deterministic arm powers)."
        )
        self.paths_spin = _spin("Recorded paths:", 0, 50_000, 500, "NSQPathsSpin")
        self.paths_spin.setSingleStep(100)

        controls.addStretch(1)
        self.trace_button = QPushButton("Trace")
        self.trace_button.setObjectName("NSQTraceButton")
        self.trace_button.setDefault(True)
        self.trace_button.clicked.connect(self._on_trace_clicked)
        controls.addWidget(self.trace_button)
        root.addLayout(controls)

        # Row 3: view controls ---------------------------------------------
        view_row = QHBoxLayout()
        self.scene_label = QLabel("")
        self.scene_label.setObjectName("NSQSceneLabel")
        view_row.addWidget(self.scene_label, 1)
        view_row.addWidget(QLabel("Projection:"))
        self.projection_combo = QComboBox()
        self.projection_combo.setObjectName("NSQProjectionCombo")
        self.projection_combo.addItems(_PROJECTIONS)
        self.projection_combo.currentTextChanged.connect(lambda _t: self.redraw())
        view_row.addWidget(self.projection_combo)
        view_row.addWidget(QLabel("Rays drawn:"))
        self.drawn_spin = QSpinBox()
        self.drawn_spin.setObjectName("NSQDrawnSpin")
        self.drawn_spin.setRange(0, 5000)
        self.drawn_spin.setValue(120)
        self.drawn_spin.setSingleStep(20)
        self.drawn_spin.valueChanged.connect(lambda _v: self.redraw())
        view_row.addWidget(self.drawn_spin)
        root.addLayout(view_row)

        # Tabs ------------------------------------------------------------
        self.tabs = QTabWidget()
        self.tabs.setObjectName("NSQTabs")

        layout_tab = QWidget()
        layout_box = QVBoxLayout(layout_tab)
        layout_box.setContentsMargins(0, 0, 0, 0)
        self.layout_figure = Figure(figsize=(8, 5))
        self.layout_canvas = FigureCanvas(self.layout_figure)
        self.layout_toolbar = CustomMatplotlibToolbar(self.layout_canvas, layout_tab)
        layout_box.addWidget(self.layout_toolbar)
        layout_box.addWidget(self.layout_canvas, 1)
        self.tabs.addTab(layout_tab, "Layout")

        detectors_tab = QWidget()
        detectors_box = QVBoxLayout(detectors_tab)
        detectors_box.setContentsMargins(0, 0, 0, 0)
        self.detector_figure = Figure(figsize=(8, 5), layout="constrained")
        self.detector_canvas = FigureCanvas(self.detector_figure)
        self.detector_toolbar = CustomMatplotlibToolbar(
            self.detector_canvas, detectors_tab
        )
        detectors_box.addWidget(self.detector_toolbar)
        detectors_box.addWidget(self.detector_canvas, 1)
        self.tabs.addTab(detectors_tab, "Detectors")

        summary_tab = QWidget()
        summary_box = QVBoxLayout(summary_tab)
        summary_box.setContentsMargins(0, 0, 0, 0)
        summary_split = QSplitter(Qt.Orientation.Vertical)
        self.summary_table = QTableWidget(0, 2)
        self.summary_table.setObjectName("NSQSummaryTable")
        self.summary_table.setHorizontalHeaderLabels(["Item", "Value"])
        self.summary_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self.summary_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self.summary_table.verticalHeader().setVisible(False)
        self.summary_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        summary_split.addWidget(self.summary_table)
        self.report_text = QPlainTextEdit()
        self.report_text.setObjectName("NSQReportText")
        self.report_text.setReadOnly(True)
        summary_split.addWidget(self.report_text)
        summary_box.addWidget(summary_split)
        self.tabs.addTab(summary_tab, "Summary")

        root.addWidget(self.tabs, 1)
        self._busy_overlay = BusyOverlay(self.tabs)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _notify(self, message: str, level: str = "info") -> None:
        toast = getattr(self.connector, "toast_manager", None)
        if toast is not None:
            toast.notify(message, level)
        elif level == "error":
            QMessageBox.critical(self, "Non-Sequential", message)

    @Slot(int)
    def _on_sample_selected(self, index: int) -> None:
        key = self.scene_combo.itemData(index)
        if key:
            self.service.load_sample(key)

    @Slot()
    def _on_open_clicked(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open non-sequential scene", "", "NSQ scene (*.json)"
        )
        if not path:
            return
        try:
            self.service.load_file(path)
        except Exception as exc:  # noqa: BLE001 -- surfaced to the user
            self._notify(f"Could not load scene: {exc}", "error")

    @Slot()
    def _on_save_clicked(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Save non-sequential scene", "", "NSQ scene (*.json)"
        )
        if not path:
            return
        try:
            self.service.save_file(path)
        except Exception as exc:  # noqa: BLE001 -- surfaced to the user
            self._notify(f"Could not save scene: {exc}", "error")

    def _trace_kwargs(self) -> dict:
        self.service.set_sampling(self.split_spin.value())
        return {
            "num_rays": self.rays_spin.value(),
            "seed": self.seed_spin.value(),
            "max_depth": self.depth_spin.value(),
            "record_paths": self.paths_spin.value(),
        }

    @Slot()
    def _on_trace_clicked(self) -> None:
        if not self.service.trace_async(**self._trace_kwargs()):
            self._notify("A trace is already running.", "warning")

    def run_trace_sync(self) -> SimulationResult:
        """Trace on the GUI thread with the panel's settings (tests, scripts)."""
        return self.service.trace_sync(**self._trace_kwargs())

    @Slot()
    def _on_scene_changed(self) -> None:
        self.scene_label.setText(self.service.scene_label)
        self.redraw()

    @Slot()
    def _on_trace_started(self) -> None:
        self.trace_button.setEnabled(False)
        self._busy_overlay.show_busy()

    @Slot(object)
    def _on_trace_finished(self, _result: object) -> None:
        self._busy_overlay.hide_busy()
        self.trace_button.setEnabled(True)
        self.redraw()

    @Slot(str)
    def _on_trace_failed(self, message: str) -> None:
        self._busy_overlay.hide_busy()
        self.trace_button.setEnabled(True)
        self._notify(f"Non-sequential trace failed: {message}", "error")

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------

    def redraw(self) -> None:
        """Redraw the layout, the detector maps and the summary."""
        self._draw_layout()
        self._draw_detectors()
        self._fill_summary()

    def _draw_layout(self) -> None:
        from optiland.nonsequential.visualization import NSQViewer2D  # noqa: PLC0415

        gui_plot_utils.apply_gui_matplotlib_styles(theme=self.current_theme)
        self.layout_figure.clear()
        ax = self.layout_figure.add_subplot(111)
        scene = self.service.scene
        if scene is None:
            ax.text(0.5, 0.5, "No scene loaded", ha="center", va="center")
            self.layout_canvas.draw_idle()
            return
        result = self.service.result
        num_rays = self.drawn_spin.value() if result is not None else 0
        try:
            NSQViewer2D(scene).view(
                result,
                ax=ax,
                projection=self.projection_combo.currentText(),
                num_rays=num_rays,
                title=self.service.scene_label,
            )
        except Exception as exc:  # noqa: BLE001 -- drawing must never crash the GUI
            logger.exception("NSQ layout drawing failed")
            ax.text(0.5, 0.5, f"Layout error: {exc}", ha="center", va="center")
        # Equal scale without shrinking the axes box: expand the data
        # limits instead so the plot keeps the whole canvas.
        ax.set_aspect("equal", adjustable="datalim")
        gui_plot_utils.apply_theme_to_existing_figure(self.layout_figure)
        self.layout_figure.tight_layout()
        self.layout_canvas.draw_idle()

    def _draw_detectors(self) -> None:
        gui_plot_utils.apply_gui_matplotlib_styles(theme=self.current_theme)
        self.detector_figure.clear()
        result = self.service.result
        maps = []
        if result is not None:
            for name, detector in result.detectors.items():
                if hasattr(detector, "irradiance") and hasattr(detector, "x_coords"):
                    maps.append((name, detector))
        if not maps:
            ax = self.detector_figure.add_subplot(111)
            ax.text(
                0.5,
                0.5,
                "Run a trace to see the detector irradiance maps",
                ha="center",
                va="center",
            )
            ax.set_axis_off()
            self.detector_canvas.draw_idle()
            return
        cols = 2 if len(maps) > 1 else 1
        rows = int(np.ceil(len(maps) / cols))
        for i, (name, det_map) in enumerate(maps, start=1):
            ax = self.detector_figure.add_subplot(rows, cols, i)
            extent = [
                float(det_map.x_coords[0]),
                float(det_map.x_coords[-1]),
                float(det_map.y_coords[0]),
                float(det_map.y_coords[-1]),
            ]
            image = ax.imshow(
                np.asarray(det_map.irradiance),
                origin="lower",
                extent=extent,
                aspect="equal",
            )
            self.detector_figure.colorbar(
                image, ax=ax, label="W/mm²", fraction=0.046, pad=0.03
            )
            ax.set_xlabel("x [mm]")
            ax.set_ylabel("y [mm]")
            ax.set_title(
                f"{name}: {det_map.total_flux_float:.4g} W, {det_map.num_rays_hit} rays"
            )
        gui_plot_utils.apply_theme_to_existing_figure(self.detector_figure)
        self.detector_canvas.draw_idle()

    def _fill_summary(self) -> None:
        rows = self.service.summary_rows()
        self.summary_table.setRowCount(len(rows))
        for r, (label, value) in enumerate(rows):
            self.summary_table.setItem(r, 0, QTableWidgetItem(label))
            self.summary_table.setItem(r, 1, QTableWidgetItem(value))
        result = self.service.result
        self.report_text.setPlainText(result.report() if result is not None else "")

    def update_theme(self, theme_name: str) -> None:
        """Apply *theme_name* (``"dark"``/``"light"``) to the embedded plots."""
        self.current_theme = theme_name
        self.layout_toolbar.update_theme()
        self.detector_toolbar.update_theme()
        self.redraw()
