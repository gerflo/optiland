"""System view: a multi-axis (non-sequential) system and its optical paths.

Hosts an :class:`~optiland_gui.services.nsq_service.NSQService` document
and shows its scene as a 2D layout with recorded ray paths, the detector
irradiance maps and an energy-balance summary. Traces run on a worker
thread; the panel only draws.

A system folded from sequential designs (``.olsys``) carries named optical
paths. Activating a path, from the pull-down or by clicking one of its
elements in the layout, loads that path's sequential design into the
connector, so the lens data editor, the 2D layout and every sequential
analysis work on it; edits made there rebuild the system.

Author: Optiland contributors, 2026
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
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

from optiland.optic import Optic

from . import __version__, gui_plot_utils
from .analysis_panel import CustomMatplotlibToolbar
from .services.file_service import with_scene_extension
from .services.nsq_service import NSQService, default_path_name
from .widgets.plot_navigation import PlotNavigation
from .worker import BusyOverlay

if TYPE_CHECKING:
    from optiland.nonsequential.tracer import SimulationResult

logger = logging.getLogger(__name__)

_PROJECTIONS = ("XZ", "YZ", "XY")
#: Combo entry that means "no path active".
NO_PATH = "(none)"
#: Delay between the last edit of the active path and the rebuild [ms].
REBUILD_DELAY_MS = 300
_HIGHLIGHT = {"dark": "#FFB000", "light": "#D9480F"}
_DIM_ALPHA = 0.35


class NSQPanel(QWidget):
    """Dockable System view for multi-axis systems.

    Args:
        connector: The GUI connector; receives the active path's design
            (``load_optic_from_object``) and reports edits (``opticChanged``).
            Its optional ``toast_manager`` is used for notifications.
        service: The system document service. A fresh one is created when
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
        self._last_scene_key: tuple = ()
        self._rebuild_timer = QTimer(self)
        self._rebuild_timer.setSingleShot(True)
        self._rebuild_timer.setInterval(REBUILD_DELAY_MS)
        self._rebuild_timer.timeout.connect(self._rebuild_from_active_path)
        self._build_ui()
        self.service.sceneChanged.connect(self._on_scene_changed)
        self.service.pathsChanged.connect(self._on_paths_changed)
        self.service.activePathChanged.connect(self._on_active_path_changed)
        self.service.traceStarted.connect(self._on_trace_started)
        self.service.traceFinished.connect(self._on_trace_finished)
        self.service.traceFailed.connect(self._on_trace_failed)
        optic_changed = getattr(self.connector, "opticChanged", None)
        if optic_changed is not None:
            optic_changed.connect(self._on_optic_changed)
        # Undo and redo restore a design with opticLoaded only; the path
        # must follow them as it follows an edit.
        optic_loaded = getattr(self.connector, "opticLoaded", None)
        if optic_loaded is not None:
            optic_loaded.connect(self._on_optic_changed)
        new_document = getattr(self.connector, "newDocument", None)
        if new_document is not None:
            new_document.connect(self._on_new_document)
        if self.service.scene is not None:
            self._on_paths_changed()
            self._on_scene_changed()
        elif not self.adopt_connector_optic():
            # No sequential design to start from (a bare connector): show the
            # first sample scene rather than nothing. (With a placeholder
            # text the combo starts without a current item.)
            self.service.load_sample(self.scene_combo.itemData(0))

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        from optiland.samples.nonsequential import SAMPLE_SCENES  # noqa: PLC0415

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        # Row 1: system selection --------------------------------------
        scene_row = QHBoxLayout()
        scene_row.addWidget(QLabel("System:"))
        self.scene_combo = QComboBox()
        self.scene_combo.setObjectName("NSQSceneCombo")
        self.scene_combo.setPlaceholderText("Sample scenes...")
        for key, label in SAMPLE_SCENES.items():
            self.scene_combo.addItem(label, key)
        self.scene_combo.activated.connect(self._on_sample_selected)
        scene_row.addWidget(self.scene_combo, 1)

        self.open_button = QPushButton("Open...")
        self.open_button.setObjectName("NSQOpenButton")
        self.open_button.clicked.connect(self._on_open_clicked)
        scene_row.addWidget(self.open_button)

        self.save_button = QPushButton("Save...")
        self.save_button.setObjectName("NSQSaveButton")
        self.save_button.clicked.connect(self._on_save_clicked)
        scene_row.addWidget(self.save_button)
        root.addLayout(scene_row)

        # Row 2: optical paths ------------------------------------------
        path_row = QHBoxLayout()
        path_row.addWidget(QLabel("Path:"))
        self.path_combo = QComboBox()
        self.path_combo.setObjectName("NSQPathCombo")
        self.path_combo.setToolTip(
            "Activate an optical path: its sequential design is loaded into the "
            "lens data editor, the 2D layout and the analyses. Clicking an "
            "element in the layout does the same."
        )
        self.path_combo.activated.connect(self._on_path_selected)
        path_row.addWidget(self.path_combo, 1)
        self.rename_path_button = QPushButton("Rename...")
        self.rename_path_button.setObjectName("NSQRenamePathButton")
        self.rename_path_button.clicked.connect(self._on_rename_path_clicked)
        path_row.addWidget(self.rename_path_button)
        root.addLayout(path_row)

        # Row 3: trace controls --------------------------------------------
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
        # 48 hits cover a folded system (a fundus camera's ring illumination
        # meets ~18 surfaces before the retina, ~27 when it returns).
        self.depth_spin = _spin("Max depth:", 1, 256, 48, "NSQDepthSpin")
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

        # Row 4: view controls ---------------------------------------------
        view_row = QHBoxLayout()
        self.scene_label = QLabel("")
        self.scene_label.setObjectName("NSQSceneLabel")
        view_row.addWidget(self.scene_label, 1)
        view_row.addWidget(QLabel("Projection:"))
        self.projection_combo = QComboBox()
        self.projection_combo.setObjectName("NSQProjectionCombo")
        self.projection_combo.addItems(_PROJECTIONS)
        self.projection_combo.currentTextChanged.connect(self._on_projection_changed)
        view_row.addWidget(self.projection_combo)
        view_row.addWidget(QLabel("Rays drawn:"))
        self.drawn_spin = QSpinBox()
        self.drawn_spin.setObjectName("NSQDrawnSpin")
        self.drawn_spin.setRange(0, 5000)
        self.drawn_spin.setValue(120)
        self.drawn_spin.setSingleStep(20)
        self.drawn_spin.valueChanged.connect(lambda _v: self.redraw())
        view_row.addWidget(self.drawn_spin)
        self.reset_view_button = QPushButton("Fit")
        self.reset_view_button.setObjectName("NSQFitButton")
        self.reset_view_button.setToolTip(
            "Show the whole system again (double-click on the layout does the "
            "same; wheel zooms, left drag pans)."
        )
        self.reset_view_button.clicked.connect(self.reset_layout_view)
        view_row.addWidget(self.reset_view_button)
        root.addLayout(view_row)

        # Tabs ------------------------------------------------------------
        self.tabs = QTabWidget()
        self.tabs.setObjectName("NSQTabs")

        layout_tab = QWidget()
        layout_box = QVBoxLayout(layout_tab)
        layout_box.setContentsMargins(0, 0, 0, 0)
        # Constrained layout is recomputed on every draw, so the title and
        # tick labels stay inside the figure after the dock is resized
        # (tight_layout would fix the margins at the first draw's size).
        self.layout_figure = Figure(figsize=(8, 5), layout="constrained")
        self.layout_canvas = FigureCanvas(self.layout_figure)
        self.layout_toolbar = CustomMatplotlibToolbar(self.layout_canvas, layout_tab)
        self.layout_toolbar.on_view_limits_changed = self._on_toolbar_view_changed
        layout_box.addWidget(self.layout_toolbar)
        layout_box.addWidget(self.layout_canvas, 1)
        self.navigation = PlotNavigation(
            self.layout_canvas, on_reset=self.reset_layout_view
        )
        self.layout_canvas.mpl_connect("pick_event", self._on_layout_pick)
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
            QMessageBox.critical(self, "System", message)

    @Slot(int)
    def _on_sample_selected(self, index: int) -> None:
        key = self.scene_combo.itemData(index)
        if key:
            self.service.load_sample(key)

    def _main_window_action(self, name: str):
        """The main window's slot ``name``, if this panel lives in one.

        A floating dock is its own top-level window, so the parent chain is
        walked instead of asking ``self.window()``.
        """
        widget = self.parent()
        while widget is not None:
            action = getattr(widget, name, None)
            if callable(action):
                return action
            widget = widget.parent()
        return None

    @Slot()
    def _on_open_clicked(self) -> None:
        # Inside the main window, go through its File -> Open path so the
        # unsaved-changes prompt and the recent-files list apply.
        opener = self._main_window_action("open_system_action")
        if opener is not None:
            opener()
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open multi-axis system",
            "",
            "Multi-axis system (*.olsys);;NSQ scene JSON (*.json);;All files (*)",
        )
        if not path:
            return
        try:
            self.service.load_file(path, self.connector)
        except Exception as exc:  # noqa: BLE001 -- surfaced to the user
            self._notify(f"Could not load system: {exc}", "error")

    @Slot()
    def _on_save_clicked(self) -> None:
        saver = self._main_window_action("save_system_as_action")
        if saver is not None:
            saver()
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save multi-axis system",
            "",
            "Multi-axis system (*.olsys);;NSQ scene JSON (*.json)",
        )
        if not path:
            return
        self.flush_pending_rebuild()
        try:
            self.service.save_file(
                with_scene_extension(path), application=("Optiland GUI", __version__)
            )
        except Exception as exc:  # noqa: BLE001 -- surfaced to the user
            self._notify(f"Could not save system: {exc}", "error")

    # -- documents ---------------------------------------------------------

    @Slot()
    def _on_new_document(self) -> None:
        """The connector got a new design: it becomes path 1 of a new system."""
        if self.service.is_activating:
            return
        self._rebuild_timer.stop()
        self.adopt_connector_optic()

    def adopt_connector_optic(self) -> bool:
        """Start a new document from the connector's current design.

        Returns:
            ``False`` when the connector holds no ``Optic`` (a stand-in in
            tests); the document is then left alone.
        """
        optic = self.connector.get_optic()
        if not isinstance(optic, Optic):
            return False
        source = self.connector.get_current_filepath()
        if not isinstance(source, str):
            source = None
        name = default_path_name(getattr(optic, "name", ""), source)
        error = self.service.adopt_optic(self._active_optic_data(), name, source=source)
        if error:
            self._notify(
                f"Path '{name}' is not shown in the System view: {error}", "warning"
            )
        return True

    def _active_optic_data(self):
        """The connector's design as stored in a path (with GUI state)."""
        capture = getattr(self.connector, "capture_optic_state", None)
        if callable(capture):
            data = capture()
            if isinstance(data, dict):
                return data
        return self.connector.get_optic()

    # -- optical paths ---------------------------------------------------

    @Slot()
    def _on_paths_changed(self) -> None:
        names = self.service.path_names
        self.path_combo.blockSignals(True)
        self.path_combo.clear()
        self.path_combo.addItem(NO_PATH, None)
        for name in names:
            self.path_combo.addItem(name, name)
        self.path_combo.blockSignals(False)
        has_paths = bool(names)
        self.path_combo.setEnabled(has_paths)
        self.rename_path_button.setEnabled(has_paths)
        self._select_combo_path(self.service.active_path)

    def _select_combo_path(self, name: str | None) -> None:
        index = self.path_combo.findData(name) if name is not None else 0
        self.path_combo.blockSignals(True)
        self.path_combo.setCurrentIndex(max(index, 0))
        self.path_combo.blockSignals(False)

    @Slot(int)
    def _on_path_selected(self, index: int) -> None:
        self.activate_path(self.path_combo.itemData(index))

    def activate_path(self, name: str | None) -> None:
        """Make ``name`` the active path (``None`` deactivates).

        Args:
            name: A path name of the current system, or ``None``.
        """
        self._rebuild_timer.stop()
        try:
            self.service.activate_path(name, self.connector)
        except Exception as exc:  # noqa: BLE001 -- surfaced to the user
            logger.exception("Activating optical path %r failed", name)
            self._notify(f"Could not activate path {name!r}: {exc}", "error")
            self._select_combo_path(self.service.active_path)

    @Slot(object)
    def _on_active_path_changed(self, name: object) -> None:
        self._select_combo_path(name if isinstance(name, str) else None)
        self._draw_layout(preserve_view=True)

    @Slot()
    def _on_rename_path_clicked(self) -> None:
        current = self.path_combo.currentData() or (
            self.service.path_names[0] if self.service.path_names else None
        )
        if current is None:
            return
        new, ok = QInputDialog.getText(
            self, "Rename optical path", "Name:", text=current
        )
        if not ok or not new.strip() or new.strip() == current:
            return
        try:
            self.service.rename_path(current, new.strip())
        except Exception as exc:  # noqa: BLE001 -- surfaced to the user
            self._notify(f"Could not rename path: {exc}", "error")

    @Slot()
    def _on_optic_changed(self) -> None:
        """An edit in the sequential tools: rebuild the active path (debounced)."""
        if self.service.active_path is None or self.service.is_activating:
            return
        self._rebuild_timer.start()

    @Slot()
    def _rebuild_from_active_path(self) -> None:
        if self.service.active_path is None:
            return
        try:
            self.service.sync_active_path(self._active_optic_data())
        except Exception as exc:  # noqa: BLE001 -- surfaced to the user
            logger.exception("Rebuilding the system from the active path failed")
            self._notify(f"System not rebuilt: {exc}", "error")

    def flush_pending_rebuild(self) -> None:
        """Commit the active path's design to the system now.

        Called before saving and exporting (and by tests): the debounce
        timer is cancelled and the design is synced; an unchanged design
        is a no-op, so this is cheap.
        """
        self._rebuild_timer.stop()
        if self.service.active_path is not None and not self.service.is_activating:
            self._rebuild_from_active_path()

    def _on_layout_pick(self, event) -> None:
        """A click on a drawn element activates the path it belongs to."""
        mouse = getattr(event, "mouseevent", None)
        if mouse is not None and (mouse.button != 1 or mouse.dblclick):
            return
        label = getattr(event.artist, "get_label", lambda: "")()
        if not isinstance(label, str) or label.startswith("_"):
            return
        paths = self.service.paths_for_component(label)
        if not paths:
            return
        current = self.service.active_path
        if current in paths and len(paths) > 1:
            # A shared element cycles through the paths it belongs to.
            target = paths[(paths.index(current) + 1) % len(paths)]
        elif current in paths:
            return
        else:
            target = paths[0]
        self.activate_path(target)

    # -- tracing -----------------------------------------------------------

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
        # The pull-down lists the samples; a document that is not one of
        # them shows the placeholder instead of a stale sample name.
        self.scene_combo.blockSignals(True)
        self.scene_combo.setCurrentIndex(
            self.scene_combo.findText(self.service.scene_label)
        )
        self.scene_combo.blockSignals(False)
        key = (self.service.scene_label, self.service.scene_path)
        # A different system starts with the full view; a rebuilt or
        # re-traced one keeps the user's zoom.
        preserve = key == self._last_scene_key
        self._last_scene_key = key
        if not preserve:
            self.navigation.forget_view()
        self.redraw(preserve_view=preserve)

    @Slot()
    def _on_trace_started(self) -> None:
        self.trace_button.setEnabled(False)
        self._busy_overlay.show_busy()

    @Slot(object)
    def _on_trace_finished(self, _result: object) -> None:
        self._busy_overlay.hide_busy()
        self.trace_button.setEnabled(True)
        self.redraw(preserve_view=True)

    @Slot(str)
    def _on_trace_failed(self, message: str) -> None:
        self._busy_overlay.hide_busy()
        self.trace_button.setEnabled(True)
        self._notify(f"Non-sequential trace failed: {message}", "error")

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------

    @Slot(str)
    def _on_projection_changed(self, _text: str) -> None:
        self.reset_layout_view()

    @Slot()
    def reset_layout_view(self) -> None:
        """Show the whole system (drop the remembered zoom and pan)."""
        self.navigation.forget_view()
        self._draw_layout(preserve_view=False)

    def _on_toolbar_view_changed(self) -> None:
        axes = self.layout_figure.get_axes()
        if axes:
            self.navigation.remember_view(axes[0])

    def redraw(self, preserve_view: bool = True) -> None:
        """Redraw the layout, the detector maps and the summary.

        Args:
            preserve_view: Keep a zoom or pan the user made in the layout.
        """
        self._draw_layout(preserve_view=preserve_view)
        self._draw_detectors()
        self._fill_summary()

    def _draw_layout(self, preserve_view: bool = True) -> None:
        from optiland.nonsequential.visualization import NSQViewer2D  # noqa: PLC0415

        gui_plot_utils.apply_gui_matplotlib_styles(theme=self.current_theme)
        self.layout_figure.clear()
        ax = self.layout_figure.add_subplot(111)
        scene = self.service.scene
        if scene is None:
            ax.text(0.5, 0.5, "No system loaded", ha="center", va="center")
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
                title=self._layout_title(),
            )
        except Exception as exc:  # noqa: BLE001 -- drawing must never crash the GUI
            logger.exception("NSQ layout drawing failed")
            ax.text(0.5, 0.5, f"Layout error: {exc}", ha="center", va="center")
        self._style_path_artists(ax)
        # Equal scale without shrinking the axes box: expand the data
        # limits instead so the plot keeps the whole canvas.
        ax.set_aspect("equal", adjustable="datalim")
        gui_plot_utils.apply_theme_to_existing_figure(self.layout_figure)
        if preserve_view and self.navigation.user_changed_view:
            self.navigation.restore_view(ax)
        self.layout_canvas.draw_idle()

    def _layout_title(self) -> str:
        active = self.service.active_path
        if active:
            return f"{self.service.scene_label}  |  path: {active}"
        return self.service.scene_label

    def _style_path_artists(self, ax) -> None:
        """Make drawn elements pickable and highlight the active path."""
        active = self.service.active_path
        members: set[str] = set()
        if active is not None:
            try:
                path = self.service.path(active)
                members = set(path.components) | set(path.sources)
            except (KeyError, RuntimeError):
                members = set()
        color = _HIGHLIGHT.get(self.current_theme, _HIGHLIGHT["dark"])
        pickable = bool(self.service.path_names)
        for artist in list(ax.lines) + list(ax.patches) + list(ax.collections):
            label = artist.get_label()
            if not isinstance(label, str) or label.startswith("_"):
                continue
            if pickable and self.service.paths_for_component(label):
                artist.set_picker(6)
            if not members:
                continue
            if label in members:
                artist.set_zorder(artist.get_zorder() + 1)
                if hasattr(artist, "set_linewidth"):
                    artist.set_linewidth(3.0)
                if hasattr(artist, "set_color"):
                    artist.set_color(color)
            else:
                artist.set_alpha(_DIM_ALPHA)

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
        self.redraw(preserve_view=True)


#: The panel under its user-facing name.
SystemPanel = NSQPanel
