"""
Provides the main viewing panel for optical systems.

This module defines the `ViewerPanel`, which contains tabs for 2D and 3D
visualizations of the optical system. It includes `MatplotlibViewer` for 2D
plots and `VTKViewer` for 3D rendering.

@author: Manuel Fragata Mendes, 2025
"""

from __future__ import annotations

import logging
import math

import matplotlib
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from PySide6.QtCore import QPoint, QSettings, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QCursor, QIcon, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

try:
    import vtk
    from vtkmodules.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor

    VTK_AVAILABLE = True
except ImportError:
    VTK_AVAILABLE = False

from typing import TYPE_CHECKING

from optiland.visualization.analysis.surface_sag import SurfaceSagViewer
from optiland.visualization.system.rays import Rays2D, Rays3D
from optiland.visualization.system.system import (
    OpticalSystem as OptilandOpticalSystemPlotter,
)

from . import gui_plot_utils
from .analysis_panel import CustomMatplotlibToolbar
from .config import APPLICATION_NAME, ORGANIZATION_NAME
from .worker import BusyOverlay

if TYPE_CHECKING:
    from .optiland_connector import OptilandConnector


logger = logging.getLogger(__name__)


class SagViewer(QWidget):
    """A widget for displaying a 2D sag plot of a selected optical surface."""

    def __init__(self, connector: OptilandConnector, parent=None):
        super().__init__(parent)
        self.connector = connector
        self.current_theme = "dark"

        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.setSpacing(25)

        # Main Plotting Area
        plot_widget = QWidget()
        plot_layout = QVBoxLayout(plot_widget)
        plot_layout.setContentsMargins(0, 0, 0, 0)
        plot_layout.setSpacing(2)
        main_layout.addWidget(plot_widget, 1)

        # --- Toolbar and Title ---
        toolbar_container = QWidget()
        toolbar_container.setObjectName("ViewerToolbarContainer")
        toolbar_container.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        toolbar_container.setMaximumHeight(60)
        toolbar_layout = QHBoxLayout(toolbar_container)
        toolbar_layout.setContentsMargins(0, 0, 0, 0)
        plot_layout.addWidget(toolbar_container)

        # --- Matplotlib Canvas ---
        self.figure = Figure(figsize=(5, 5), dpi=100)
        self.canvas = FigureCanvas(self.figure)
        plot_layout.addWidget(self.canvas, 1)

        # --- Add Toolbar to container ---
        self.toolbar = CustomMatplotlibToolbar(self.canvas, toolbar_container)
        toolbar_layout.addWidget(self.toolbar)
        toolbar_layout.addStretch()

        # Add settings toggle button to toolbar
        self.settings_toggle_btn = QToolButton()
        self.settings_toggle_btn.setToolTip("Toggle Sag Viewer Settings")
        self.settings_toggle_btn.setCheckable(True)
        self.settings_toggle_btn.setChecked(True)
        self.settings_toggle_btn.toggled.connect(self._toggle_settings)
        self.toolbar.addWidget(self.settings_toggle_btn)

        # Re-route the toolbar's home button to our full plot refresh
        for action in self.toolbar.actions():
            if action.toolTip() == "Reset original view":
                action.triggered.disconnect()
                action.triggered.connect(self.plot_sag)
                break

        # --- Cursor Coordinate Label ---
        self.cursor_coord_label = QLabel("", self.canvas)
        self.cursor_coord_label.setObjectName("CursorCoordLabel")
        self.cursor_coord_label.setStyleSheet(
            "background-color:rgba(0,0,0,0.65);color:white;padding:2px 4px;"
            "border-radius:3px;"
        )
        self.cursor_coord_label.setVisible(False)
        self.cursor_coord_label.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents
        )

        # Connect mouse move event
        self.canvas.mpl_connect("motion_notify_event", self.on_mouse_move_on_plot)

        # Settings Area
        self.settings_area = QWidget()
        self.settings_area.setFixedWidth(220)
        settings_layout = QVBoxLayout(self.settings_area)
        settings_layout.addWidget(QLabel("Sag Viewer Settings"))

        settings_form = QFormLayout()
        self.surface_selector = QSpinBox()
        self.surface_selector.setRange(0, 100)
        settings_form.addRow("Surface Index:", self.surface_selector)

        self.x_cross_section = QDoubleSpinBox()
        self.x_cross_section.setRange(-1000, 1000)
        self.x_cross_section.setValue(0.0)
        settings_form.addRow("X Cross-section (for Y-plot):", self.x_cross_section)

        self.y_cross_section = QDoubleSpinBox()
        self.y_cross_section.setRange(-1000, 1000)
        self.y_cross_section.setValue(0.0)
        settings_form.addRow("Y Cross-section (for X-plot):", self.y_cross_section)

        settings_layout.addLayout(settings_form)
        settings_layout.addStretch()

        self.maxExtentSpinBox = QDoubleSpinBox()
        self.maxExtentSpinBox.setRange(0.01, 1000.0)
        self.maxExtentSpinBox.setValue(20.0)  # Default value
        self.maxExtentSpinBox.setSuffix(" mm")
        self.maxExtentSpinBox.setToolTip("Set the viewing area extent (±mm)")
        self.maxExtentSpinBox.valueChanged.connect(self.plot_sag)

        settings_form.addRow("View Extent:", self.maxExtentSpinBox)

        apply_button = QPushButton("Plot Sag")
        apply_button.clicked.connect(self.plot_sag)
        settings_layout.addWidget(apply_button)
        main_layout.addWidget(self.settings_area)

        # Initial setup
        self.connector.opticChanged.connect(self.update_surface_range)
        self.update_surface_range()
        self.plot_sag()
        self.update_theme()

    def _toggle_settings(self, checked):
        """Toggle the visibility of the settings panel."""
        self.settings_area.setVisible(checked)

    def on_mouse_move_on_plot(self, event):
        """Displays the cursor's coordinates on the plot."""
        if event.inaxes:
            # Determine which axis the cursor is over for a more informative label
            axis_label = "Pos"
            if event.inaxes.get_xlabel() == "X-coordinate":
                axis_label = "(X, Sag)"
            elif event.inaxes.get_ylabel() == "Y-coordinate (mm)":
                axis_label = "(X, Y)"
            elif event.inaxes.get_xlabel() == "Sag (z)":
                axis_label = "(Sag, Y)"

            x_coord = f"{event.xdata:.3f}" if event.xdata is not None else "---"
            y_coord = f"{event.ydata:.3f}" if event.ydata is not None else "---"
            self.cursor_coord_label.setText(f"{axis_label} = ({x_coord}, {y_coord})")
            self.cursor_coord_label.adjustSize()
            # Position at the bottom-left of the canvas
            self.cursor_coord_label.move(
                5, self.canvas.height() - self.cursor_coord_label.height() - 5
            )
            self.cursor_coord_label.setVisible(True)
            self.cursor_coord_label.raise_()
        else:
            self.cursor_coord_label.setVisible(False)

    def update_surface_range(self):
        """Updates the range of the surface selector spinbox."""
        count = self.connector.get_surface_count()
        self.surface_selector.setRange(0, max(0, count - 1))

    def update_theme(self, theme="dark"):
        self.current_theme = theme
        self.settings_toggle_btn.setIcon(QIcon(f":/icons/{theme}/settings.svg"))
        self.toolbar.update_theme()
        self.plot_sag()

    @Slot()
    def plot_sag(self):
        gui_plot_utils.apply_gui_matplotlib_styles(theme=self.current_theme)
        optic = self.connector.get_optic()
        surface_index = self.surface_selector.value()
        self.figure.clear()

        if not optic or not (0 <= surface_index < optic.surface_group.num_surfaces):
            ax = self.figure.add_subplot(111)
            ax.text(
                0.5,
                0.5,
                f"Invalid Surface Index: {surface_index}",
                ha="center",
                va="center",
            )
            self.canvas.draw()
            return

        # Use the existing backend SurfaceSagViewer class
        viewer = SurfaceSagViewer(optic)

        # Call its view method, passing our figure to be plotted on
        viewer.view(
            surface_index=surface_index,
            y_cross_section=self.y_cross_section.value(),
            x_cross_section=self.x_cross_section.value(),
            max_extent=self.maxExtentSpinBox.value(),
            fig_to_plot_on=self.figure,
        )
        gui_plot_utils.apply_theme_to_existing_figure(self.figure)

        # Redraw our canvas
        self.canvas.draw()


class ViewerPanel(QWidget):
    """
    A widget that contains multiple viewers for the optical system.

    This panel uses a QTabWidget to host different types of viewers, such as
    a 2D plot and a 3D rendering of the system.

    Attributes:
        connector (OptilandConnector): The connector to the main application logic.
        tabWidget (QTabWidget): The widget hosting the different viewer tabs.
        viewer2D (MatplotlibViewer): The 2D viewer widget.
        viewer3D (VTKViewer or QLabel): The 3D viewer widget, or a label if VTK
                                        is unavailable.
    """

    def __init__(self, connector: OptilandConnector, parent=None):
        """
        Initializes the ViewerPanel.

        Args:
            connector (OptilandConnector): The connector to the main application logic.
            parent (QWidget, optional): The parent widget. Defaults to None.
        """
        super().__init__(parent)
        self.connector = connector
        self.settings = QSettings(ORGANIZATION_NAME, APPLICATION_NAME)
        self.current_theme = "dark"

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        self.tabWidget = QTabWidget()

        # Create 2D Viewer Tab
        self.viewer2D = MatplotlibViewer(self.connector)
        self.viewer2D.settingsApplied.connect(self._render_3d_from_2d_settings)
        viewer2d_container = self._create_2d_viewer_tab()
        self.tabWidget.addTab(viewer2d_container, "2D Layout")

        # Create 3D Viewer Tab
        self.viewer3D = None
        self._pending_3d_render = False
        self._creating_3d_viewer = False
        self._rendering_3d = False
        self._scheduled_3d_activation = False
        self._viewer3d_tab_index = -1
        if VTK_AVAILABLE:
            _3d_tab = self._create_3d_viewer_tab()
            self._viewer3d_tab_index = self.tabWidget.addTab(_3d_tab, "3D Layout")

        # Create Sag Viewer Tab
        self.sagViewer = SagViewer(self.connector, self)
        self.tabWidget.addTab(self.sagViewer, "Sag")

        main_layout.addWidget(self.tabWidget)
        self.tabWidget.currentChanged.connect(self._render_pending_3d_if_visible)

        self.connector.opticLoaded.connect(self.reset_original_views)
        self.connector.opticChanged.connect(self.update_viewers)

    def _create_3d_viewer_tab(self) -> QWidget:
        """Create the 3D tab container with toolbar and content area."""
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(2)

        # Toolbar row — same layout style as the 2D tab
        toolbar_layout = QHBoxLayout()
        toolbar_layout.setContentsMargins(0, 0, 0, 0)

        self._btn_3d_refresh = QPushButton("⟳  Refresh")
        self._btn_3d_refresh.setToolTip("Re-render the 3D view")
        self._btn_3d_refresh.clicked.connect(lambda _=None: self._render_3d_now())

        self._chk_3d_stop = QCheckBox("Stop Aperture")
        self._chk_3d_stop.setToolTip("Show the stop surface aperture")
        self._chk_3d_stop.setChecked(True)
        self._chk_3d_stop.toggled.connect(lambda _: self._render_3d_from_2d_settings())

        self._chk_3d_non_stop = QCheckBox("Other Apertures")
        self._chk_3d_non_stop.setToolTip("Show non-stop surface apertures")
        self._chk_3d_non_stop.setChecked(True)
        self._chk_3d_non_stop.toggled.connect(lambda _: self._render_3d_from_2d_settings())

        toolbar_layout.addWidget(self._btn_3d_refresh)
        toolbar_layout.addWidget(self._chk_3d_stop)
        toolbar_layout.addWidget(self._chk_3d_non_stop)
        toolbar_layout.addStretch()
        layout.addLayout(toolbar_layout)

        # Content area — starts with placeholder; VTK widget is injected here
        self._3d_content_widget = QWidget()
        self._3d_content_layout = QVBoxLayout(self._3d_content_widget)
        self._3d_content_layout.setContentsMargins(0, 0, 0, 0)
        placeholder_lbl = QLabel("3D view is prepared when this tab is opened.")
        placeholder_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._3d_content_layout.addWidget(placeholder_lbl)
        layout.addWidget(self._3d_content_widget, 1)

        return container

    def _ensure_3d_viewer(self) -> bool:
        """Create the VTK viewer lazily when the 3D tab is activated."""
        if self.viewer3D is not None:
            return True
        if self._creating_3d_viewer:
            return False
        if not VTK_AVAILABLE or self._viewer3d_tab_index < 0:
            return False

        self._creating_3d_viewer = True
        try:
            viewer3d = VTKViewer(self.connector)
            viewer3d.update_theme(self.current_theme, render=False)
            # Swap out the placeholder label for the real VTK widget
            while self._3d_content_layout.count():
                item = self._3d_content_layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            self._3d_content_layout.addWidget(viewer3d)
            self.viewer3D = viewer3d
            return True
        finally:
            self._creating_3d_viewer = False

    def _create_2d_viewer_tab(self):
        """Creates the container widget for the 2D viewer."""
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.addWidget(self.viewer2D)
        return container

    @Slot()
    def update_viewers(self):
        """Updates all active viewers with the current optic data."""
        if self.viewer2D:
            preserve = self.viewer2D.preserve_zoom_checkbox.isChecked()
            self.viewer2D.plot_optic(preserve_zoom=preserve)
        self._render_3d_from_2d_settings()

    @Slot()
    def reset_original_views(self):
        """Reset all viewer tabs to their original framing after loading a system."""
        if self.viewer2D:
            self.viewer2D.reset_view()
        self._render_3d_from_2d_settings()
        if self.sagViewer:
            self.sagViewer.update_surface_range()
            self.sagViewer.plot_sag()

    @Slot()
    def _render_3d_from_2d_settings(self):
        """Render 3D rays with sampling derived from the 2D view settings."""
        if not self.viewer2D:
            return
        if not self._is_3d_tab_active():
            self._pending_3d_render = True
            return
        self._render_3d_now()

    def _is_3d_tab_active(self) -> bool:
        """Return whether the VTK viewer tab is currently visible."""
        return bool(
            self._viewer3d_tab_index >= 0
            and self.tabWidget.currentIndex() == self._viewer3d_tab_index
        )

    def _render_3d_now(self) -> None:
        """Render the 3D view immediately from the current 2D sampling state."""
        if self._rendering_3d:
            self._pending_3d_render = True
            return
        if not (self.viewer2D and self._ensure_3d_viewer() and self.viewer3D):
            return
        num_rays, distribution = self.viewer2D.ray_sampling_for_3d()
        show_stop = self._chk_3d_stop.isChecked() if hasattr(self, "_chk_3d_stop") else True
        show_non_stop = self._chk_3d_non_stop.isChecked() if hasattr(self, "_chk_3d_non_stop") else True
        self._rendering_3d = True
        try:
            self.viewer3D.render_optic(
                num_rays=num_rays,
                distribution=distribution,
                show_stop_apertures=show_stop,
                show_non_stop_apertures=show_non_stop,
            )
            self._pending_3d_render = False
        finally:
            self._rendering_3d = False

    @Slot(int)
    def _render_pending_3d_if_visible(self, _index: int) -> None:
        """Render delayed 3D updates once the 3D tab becomes visible."""
        if self._is_3d_tab_active() and (self._pending_3d_render or not self.viewer3D):
            self._schedule_3d_activation()

    def _schedule_3d_activation(self) -> None:
        """Queue 3D creation/render after the tab-change event returns."""
        if self._scheduled_3d_activation:
            return
        self._scheduled_3d_activation = True
        QTimer.singleShot(0, self._activate_3d_view)

    @Slot()
    def _activate_3d_view(self) -> None:
        """Create and render the 3D view outside the tab-change signal stack."""
        self._scheduled_3d_activation = False
        if self._is_3d_tab_active():
            self._render_3d_now()

    def update_theme(self, theme_name: str):
        """Updates the theme for all viewers in this panel."""
        self.current_theme = theme_name
        if self.viewer2D:
            self.viewer2D.update_theme(theme_name)
        if self.viewer3D:
            self.viewer3D.update_theme(theme_name, render=self._is_3d_tab_active())
            if not self._is_3d_tab_active():
                self._pending_3d_render = True
        elif VTK_AVAILABLE:
            self._pending_3d_render = True
        if self.sagViewer:
            self.sagViewer.update_theme(theme_name)


_GRAB_RADIUS_PX = 8  # pixel radius for grabbing/snapping to a measurement dot


class _DraggablePanel(QLabel):
    """Measurement value panel that the user can drag by left-clicking."""

    def __init__(self, parent) -> None:
        super().__init__("", parent)
        self._drag_offset: QPoint | None = None
        self._on_right_click = None  # callable, set by the viewer after creation
        self._user_moved = False  # True once the user has dragged this panel manually

    def enterEvent(self, event) -> None:
        self.setCursor(Qt.CursorShape.SizeAllCursor)

    def leaveEvent(self, event) -> None:
        self.setCursor(Qt.CursorShape.ArrowCursor)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.pos()
            self.grabMouse()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        elif event.button() == Qt.MouseButton.RightButton:
            if self._on_right_click:
                self._on_right_click()

    def mouseMoveEvent(self, event) -> None:
        if self._drag_offset is not None:
            new_pos = self.mapToParent(event.pos()) - self._drag_offset
            p = self.parent()
            new_x = max(0, min(new_pos.x(), p.width() - self.width()))
            new_y = max(0, min(new_pos.y(), p.height() - self.height()))
            self.move(new_x, new_y)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._drag_offset is not None:
            self._user_moved = True
            self._drag_offset = None
            self.releaseMouse()
            self.setCursor(Qt.CursorShape.SizeAllCursor)


class _MeasureOverlay(QWidget):
    """Transparent canvas overlay that draws the measurement dot and line."""

    def __init__(self, viewer: "MatplotlibViewer") -> None:
        super().__init__(viewer.canvas)
        self._viewer = viewer
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.resize(viewer.canvas.size())
        self.raise_()

    def paintEvent(self, _event) -> None:
        v = self._viewer
        has_active = v._measure_anchor is not None
        has_kept = bool(v._kept_measurements)
        if not has_active and not has_kept:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = 4

        # Draw all kept measurements (dimmed, behind active)
        if has_kept:
            pen = QPen(QColor(160, 160, 160, 140))
            pen.setWidth(1)
            pen.setStyle(Qt.PenStyle.DashLine)
            for ka, kt in v._kept_measurements:
                try:
                    kapx, kapy = v._data_to_canvas_pixel(*ka)
                    ktpx, ktpy = v._data_to_canvas_pixel(*kt)
                except Exception:
                    continue
                painter.setPen(pen)
                painter.drawLine(kapx, kapy, ktpx, ktpy)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(160, 160, 160, 160))
                painter.drawEllipse(kapx - r, kapy - r, 2 * r, 2 * r)
                painter.drawEllipse(ktpx - r, ktpy - r, 2 * r, 2 * r)

        # Draw active measurement (yellow)
        if not has_active:
            painter.end()
            return

        try:
            apx, apy = v._data_to_canvas_pixel(*v._measure_anchor)
        except Exception:
            painter.end()
            return

        tpx = tpy = None
        if v._measure_target is not None:
            try:
                tpx, tpy = v._data_to_canvas_pixel(*v._measure_target)
            except Exception:
                pass
        elif v._cursor_pixel is not None:
            tpx, tpy = v._cursor_pixel

        if tpx is not None:
            pen = QPen(QColor(255, 210, 0, 200))
            pen.setWidth(1)
            pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.drawLine(apx, apy, tpx, tpy)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 210, 0, 230))
        painter.drawEllipse(apx - r, apy - r, 2 * r, 2 * r)

        if v._measure_target is not None and tpx is not None:
            painter.drawEllipse(tpx - r, tpy - r, 2 * r, 2 * r)

        painter.end()


class MatplotlibViewer(QWidget):
    """
    A widget for displaying a 2D plot of the optical system using Matplotlib.

    This viewer includes a Matplotlib canvas, a custom toolbar, and a settings
    panel for controlling the plot, such as the number of rays to trace.

    Attributes:
        figure (Figure): The Matplotlib figure object.
        canvas (FigureCanvas): The canvas widget that displays the figure.
        ax (Axes): The Matplotlib axes object for plotting.
        toolbar (CustomMatplotlibToolbar): The toolbar for plot navigation.
        settings_area (QWidget): The panel for viewer-specific settings.
    """

    settingsApplied = Signal()

    def __init__(self, connector: OptilandConnector, parent=None):
        """
        Initializes the MatplotlibViewer.

        Args:
            connector (OptilandConnector): The connector to the main application logic.
            parent (QWidget, optional): The parent widget. Defaults to None.
        """
        super().__init__(parent)
        self.connector = connector
        self.settings = QSettings(ORGANIZATION_NAME, APPLICATION_NAME)
        self.current_theme = "dark"
        self._preserve_xy_ratio = False

        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(5)

        viewer_widget = QWidget()
        self.layout = QVBoxLayout(viewer_widget)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(2)
        main_layout.addWidget(viewer_widget, 1)

        self.toolbar_container = QWidget()
        self.toolbar_container.setObjectName("ViewerToolbarContainer")
        toolbar_layout = QHBoxLayout(self.toolbar_container)
        toolbar_layout.setContentsMargins(5, 0, 5, 0)
        self.layout.addWidget(self.toolbar_container)

        plot_container = QWidget()
        plot_container.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        plot_layout = QVBoxLayout(plot_container)
        plot_layout.setContentsMargins(0, 0, 0, 0)
        self.layout.addWidget(plot_container, 1)

        self.figure = Figure(figsize=(5, 4), dpi=100)
        self.canvas = FigureCanvas(self.figure)
        self.canvas.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        plot_layout.addWidget(self.canvas)
        self.ax = self.figure.add_subplot(111)

        self._busy_overlay = BusyOverlay(viewer_widget)

        self._is_plotting = False
        self._user_initiated_view_change = False

        self.toolbar = CustomMatplotlibToolbar(self.canvas, self.toolbar_container)
        self.toolbar.on_view_limits_changed = self._handle_toolbar_view_limits_changed
        toolbar_layout.addWidget(self.toolbar)
        toolbar_layout.addStretch()

        for action in self.toolbar.actions():
            if action.toolTip() == "Reset original view":
                # Disconnect the default trigger
                action.triggered.disconnect()
                # Connect our full plot refresh method
                action.triggered.connect(self.reset_view)
                break

        self.settings_area = QWidget()
        self.settings_area.setObjectName("ViewerSettingsArea")
        self.settings_area.setFixedWidth(200)
        self.settings_area.setVisible(False)
        settings_layout = QVBoxLayout(self.settings_area)
        self.settings_form_layout = QFormLayout()

        self.num_rays_spinbox = QSpinBox()
        self.num_rays_spinbox.setRange(1, 300)
        self.num_rays_spinbox.setValue(
            self.settings.value("Viewer2D/NumRays", 3, type=int)
        )
        self.num_rays_spinbox.valueChanged.connect(
            lambda value: self.settings.setValue("Viewer2D/NumRays", int(value))
        )
        self.settings_form_layout.addRow("Num Rays:", self.num_rays_spinbox)

        _DIST_DESCRIPTIONS = {
            "line_y":    "Fan of rays along the Y axis (vertical cross-section).",
            "line_x":    "Fan of rays along the X axis (horizontal cross-section).",
            "hexapolar": "Rays in concentric hexagonal rings across the pupil.",
            "random":    "Uniformly random ray positions across the entrance pupil.",
        }
        self.dist_combo = QComboBox()
        self.dist_combo.addItems(list(_DIST_DESCRIPTIONS.keys()))
        self.settings_form_layout.addRow("Distribution:", self.dist_combo)

        self.dist_desc_label = QLabel(_DIST_DESCRIPTIONS.get(self.dist_combo.currentText(), ""))
        self.dist_desc_label.setWordWrap(True)
        self.dist_desc_label.setStyleSheet("color:#8A9BAD;font-size:8pt;padding:2px 0 4px 0;")
        self.dist_combo.currentTextChanged.connect(
            lambda text: self.dist_desc_label.setText(_DIST_DESCRIPTIONS.get(text, ""))
        )

        self.preserve_zoom_checkbox = QCheckBox()
        self.preserve_zoom_checkbox.setToolTip(
            "Lock the current zoom and pan level when the system updates."
        )
        self.preserve_zoom_checkbox.setChecked(
            self.settings.value("Viewer2D/PreserveZoom", False, type=bool)
        )
        self.preserve_zoom_checkbox.toggled.connect(
            lambda checked: self.settings.setValue("Viewer2D/PreserveZoom", bool(checked))
        )
        self.settings_form_layout.addRow("Preserve Zoom:", self.preserve_zoom_checkbox)

        self.preserve_xy_ratio_checkbox = QCheckBox()
        self.preserve_xy_ratio_checkbox.setToolTip(
            "Keep equal scaling between the X and Y axes in the 2D layout."
        )
        self.preserve_xy_ratio_checkbox.setChecked(
            self.settings.value("Viewer2D/PreserveXYRatio", False, type=bool)
        )
        self._preserve_xy_ratio = self.preserve_xy_ratio_checkbox.isChecked()
        self.preserve_xy_ratio_checkbox.toggled.connect(self.set_preserve_xy_ratio)
        self.preserve_xy_ratio_checkbox.toggled.connect(
            lambda checked: self.settings.setValue("Viewer2D/PreserveXYRatio", bool(checked))
        )
        self.settings_form_layout.addRow("Preserve XY Ratio:", self.preserve_xy_ratio_checkbox)

        self.center_line_checkbox = QCheckBox()
        self.center_line_checkbox.setChecked(
            self.settings.value("Viewer2D/ShowCenterLine", False, type=bool)
        )
        self.center_line_checkbox.toggled.connect(self._on_center_line_toggled)
        self.settings_form_layout.addRow("Show Center Line:", self.center_line_checkbox)

        apply_button = QPushButton("Apply")
        apply_button.clicked.connect(self.apply_settings)

        settings_layout.addLayout(self.settings_form_layout)
        settings_layout.addWidget(self.dist_desc_label)

        measurement_header = QLabel("Measurement")
        measurement_header.setStyleSheet(
            "font-weight:bold;padding-top:8px;padding-bottom:2px;"
            "border-bottom:1px solid #3A4551;"
        )
        settings_layout.addWidget(measurement_header)

        measurement_form = QFormLayout()
        self.snap_combo = QComboBox()
        self.snap_combo.addItems(["Off", "10 px", "20 px", "30 px", "40 px"])
        self.snap_combo.setCurrentText(
            self.settings.value("Viewer2D/SnapToSurface", "Off", type=str)
        )
        self.snap_combo.currentTextChanged.connect(
            lambda text: self.settings.setValue("Viewer2D/SnapToSurface", text)
        )
        measurement_form.addRow("Snap to:", self.snap_combo)
        settings_layout.addLayout(measurement_form)

        snap_desc = QLabel(
            "Snaps the measurement anchor to the nearest surface axial (Z) position "
            "when right-clicking within the selected screen distance."
        )
        snap_desc.setWordWrap(True)
        snap_desc.setStyleSheet("color:#8A9BAD;font-size:8pt;padding:3px 0;")
        settings_layout.addWidget(snap_desc)

        settings_layout.addStretch()
        settings_layout.addWidget(apply_button)
        main_layout.addWidget(self.settings_area)

        self.settings_toggle_btn = QToolButton()
        self.settings_toggle_btn.setToolTip("Toggle Viewer Settings")
        self.settings_toggle_btn.setCheckable(True)
        self.settings_toggle_btn.toggled.connect(self.settings_area.setVisible)
        self.toolbar.addWidget(self.settings_toggle_btn)

        self.cursor_coord_label = QLabel("", self.canvas)
        self.cursor_coord_label.setObjectName("CursorCoordLabel")
        self.cursor_coord_label.setStyleSheet(
            "background-color:rgba(0,0,0,0.65);color:white;padding:2px 4px;"
            "border-radius:3px;"
        )
        self.cursor_coord_label.setVisible(False)
        self.cursor_coord_label.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents
        )

        self._measure_anchor = None   # (xdata, ydata) — first right-click (active)
        self._measure_target = None   # (xdata, ydata) — second right-click (locks panel)
        self._cursor_pixel = None     # current cursor in Qt canvas coords (px, py)
        self._dragging_point = None   # "anchor" | "target" | "kept_anchor" | "kept_target" | None
        self._dragging_kept_idx = None  # index into _kept_measurements when dragging a kept dot
        self._kept_measurements: list[tuple] = []  # list of (anchor, target), max 10, FIFO

        _KEPT_MAX = 10

        self._measure_panel = _DraggablePanel(self.canvas)
        self._measure_panel.setObjectName("MeasurePanelLabel")
        self._measure_panel.setStyleSheet(
            "background-color:rgba(0,0,0,0.75);color:white;padding:4px 8px;"
            "border-radius:4px;"
        )
        self._measure_panel.setVisible(False)
        self._measure_panel._on_right_click = self._show_measurement_context_menu

        _kept_style = (
            "background-color:rgba(0,0,0,0.65);color:#AAAAAA;padding:4px 8px;"
            "border-radius:4px;border:1px solid #555555;"
        )
        self._kept_measure_panels: list[_DraggablePanel] = []
        for _ in range(_KEPT_MAX):
            _p = _DraggablePanel(self.canvas)
            _p.setObjectName("KeptMeasurePanelLabel")
            _p.setStyleSheet(_kept_style)
            _p.setVisible(False)
            self._kept_measure_panels.append(_p)
        for _p in self._kept_measure_panels:
            _p._on_right_click = lambda panel=_p: self._on_kept_panel_right_click(panel)

        self._measure_overlay = _MeasureOverlay(self)
        self.canvas.mpl_connect("draw_event", lambda _: self._refresh_measure_display())

        self.canvas.mpl_connect("motion_notify_event", self.on_mouse_move_on_plot)
        self.canvas.mpl_connect("scroll_event", self.on_scroll_zoom)

        # Add new event connections for panning
        self.canvas.mpl_connect("button_press_event", self.on_mouse_button_press)
        self.canvas.mpl_connect("button_release_event", self.on_mouse_button_release)
        self.canvas.mpl_connect("resize_event", self._on_canvas_resize)
        self.ax.callbacks.connect("xlim_changed", self.on_ax_limit_changed)
        self.ax.callbacks.connect("ylim_changed", self.on_ax_limit_changed)

        # Initialize panning state variables
        self._active_pan_button = None
        self._is_panning = False
        self._enforce_equal_xy_on_toolbar_release = False
        self._adjusting_equal_xy_limits = False

        self.plot_optic()
        self.update_theme()

    def _notify_missing_stop_surface(self) -> None:
        """Warn once that rays cannot be shown until a stop surface is defined."""
        if getattr(self.connector, "_missing_stop_surface_warned", False):
            return
        setattr(self.connector, "_missing_stop_surface_warned", True)
        message = (
            "No stop surface is defined. The optical layout is shown, but rays are hidden."
        )
        toast_manager = getattr(self.connector, "toast_manager", None)
        if toast_manager is not None:
            toast_manager.notify(message, "warning")
        else:
            logger.warning(message)

    def on_ax_limit_changed(self, ax):
        """Callback for when axis limits change, to detect user interaction."""
        if self._adjusting_equal_xy_limits:
            return
        if not self._is_plotting:
            self._user_initiated_view_change = True
        if (
            self._enforce_equal_xy_on_toolbar_release
            and self._toolbar_navigation_mode_active()
            and (self._preserve_xy_ratio or bool(QApplication.keyboardModifiers() & Qt.KeyboardModifier.ControlModifier))
        ):
            self._adjusting_equal_xy_limits = True
            try:
                self._apply_equal_xy_limits(self.ax.get_xlim(), self.ax.get_ylim())
                self.canvas.draw_idle()
            finally:
                self._adjusting_equal_xy_limits = False

    def _on_canvas_resize(self, event) -> None:
        """Re-apply equal X/Y limits after the canvas pixel size changes.

        Matplotlib fires this after FigureCanvas.resizeEvent() has updated
        figure.get_figwidth()/get_figheight(), so box_ratio in
        _apply_equal_xy_limits already reflects the new pixel dimensions.
        """
        self._measure_overlay.resize(self.canvas.size())
        if not self._preserve_xy_ratio or self._is_plotting or self._adjusting_equal_xy_limits:
            return
        self._adjusting_equal_xy_limits = True
        try:
            self._apply_equal_xy_limits(self.ax.get_xlim(), self.ax.get_ylim())
            self.canvas.draw_idle()
        finally:
            self._adjusting_equal_xy_limits = False

    def reset_view(self):
        """Resets the view to the default zoom and panel-filling framing."""
        self._user_initiated_view_change = False
        self.plot_optic(preserve_zoom=False)

    def _toolbar_navigation_mode_active(self) -> bool:
        """Return whether Matplotlib's own pan/zoom tool currently owns drag input."""
        return bool(getattr(self.toolbar, "mode", ""))

    def _ctrl_modifier_active(self, event) -> bool:
        """Return whether Ctrl is currently active for a Matplotlib mouse event."""
        key = str(getattr(event, "key", "") or "").lower()
        if "ctrl" in key or "control" in key:
            return True
        return bool(
            QApplication.keyboardModifiers() & Qt.KeyboardModifier.ControlModifier
        )

    def _data_to_canvas_pixel(self, data_x: float, data_y: float) -> tuple[int, int]:
        """Convert axes data coordinates to Qt canvas pixel coordinates."""
        disp = self.ax.transData.transform((data_x, data_y))
        return int(disp[0]), int(self.canvas.height() - disp[1])

    def _update_locked_measure_panel(self) -> None:
        """Populate and (if not user-moved) reposition the active measurement panel."""
        if self._measure_anchor is None or self._measure_target is None:
            return
        az, ay = self._measure_anchor
        tz, ty = self._measure_target
        dz = tz - az
        dy = ty - ay
        length = math.hypot(dz, dy)
        angle = math.degrees(math.atan2(dy, dz))
        self._measure_panel.setText(
            f"ΔZ = {dz:+.3f} mm\nΔY = {dy:+.3f} mm\n"
            f"L  = {length:.3f} mm\n∠X = {angle:.1f}°"
        )
        self._measure_panel.adjustSize()
        if not self._measure_panel._user_moved:
            try:
                tpx, tpy = self._data_to_canvas_pixel(tz, ty)
            except Exception:
                self._measure_panel.setVisible(False)
                return
            px = tpx + 15
            py = tpy + 5
            px = min(px, self.canvas.width() - self._measure_panel.width() - 4)
            py = min(py, self.canvas.height() - self._measure_panel.height() - 4)
            py = max(py, 4)
            self._measure_panel.move(px, py)
        self._measure_panel.setVisible(True)
        self._measure_panel.raise_()

    def _update_kept_measure_panels(self) -> None:
        """Populate all kept measurement panels; reposition unless user-moved."""
        for i, (ka, kt) in enumerate(self._kept_measurements):
            panel = self._kept_measure_panels[i]
            az, ay = ka
            tz, ty = kt
            dz = tz - az
            dy = ty - ay
            length = math.hypot(dz, dy)
            angle = math.degrees(math.atan2(dy, dz))
            panel.setText(
                f"ΔZ = {dz:+.3f} mm\nΔY = {dy:+.3f} mm\n"
                f"L  = {length:.3f} mm\n∠X = {angle:.1f}°"
            )
            panel.adjustSize()
            if not panel._user_moved:
                try:
                    tpx, tpy = self._data_to_canvas_pixel(tz, ty)
                except Exception:
                    panel.setVisible(False)
                    continue
                px = tpx + 15
                py = tpy + 5
                px = min(px, self.canvas.width() - panel.width() - 4)
                py = min(py, self.canvas.height() - panel.height() - 4)
                py = max(py, 4)
                panel.move(px, py)
            panel.setVisible(True)
            panel.raise_()
        for i in range(len(self._kept_measurements), len(self._kept_measure_panels)):
            self._kept_measure_panels[i].setVisible(False)

    def _refresh_measure_display(self) -> None:
        """Repaint overlay and reposition locked panel after a canvas redraw."""
        self._measure_overlay.update()
        if self._measure_target is not None:
            self._update_locked_measure_panel()
        if self._kept_measurements:
            self._update_kept_measure_panels()

    def _snap_anchor(self, pixel_x: float, pixel_y: float, data_x: float, data_y: float) -> tuple[float, float]:
        """Snap anchor to nearest surface Z and/or Y=0 when within the pixel threshold."""
        snap_text = self.snap_combo.currentText()
        if snap_text == "Off":
            return data_x, data_y
        threshold_px = int(snap_text.split()[0])

        # Snap X to nearest surface Z
        optic = self.connector.get_effective_optic()
        snapped_x = data_x
        if optic is not None and optic.surface_group.num_surfaces > 0:
            best_dist = float("inf")
            for surf in optic.surface_group.surfaces:
                try:
                    z = float(surf.geometry.cs.z)
                except Exception:
                    continue
                surf_px = self.ax.transData.transform((z, 0.0))[0]
                dist = abs(pixel_x - surf_px)
                if dist < threshold_px and dist < best_dist:
                    best_dist = dist
                    snapped_x = z

        # Snap Y to 0 when close — both pixel_y (event.y) and zero_display_y are in
        # matplotlib display coords (origin bottom-left), so subtract directly.
        snapped_y = data_y
        zero_display_y = self.ax.transData.transform((data_x, 0.0))[1]
        if abs(pixel_y - zero_display_y) < threshold_px:
            snapped_y = 0.0

        return snapped_x, snapped_y

    def _is_near_dot(self, event_x: float, event_y: float, data_x: float, data_y: float) -> bool:
        """Return True if matplotlib display coords are within grab radius of the data point."""
        try:
            disp = self.ax.transData.transform((data_x, data_y))
            return math.hypot(event_x - disp[0], event_y - disp[1]) <= _GRAB_RADIUS_PX
        except Exception:
            return False

    def _clear_measurement(self) -> None:
        """Clear all measurement state (active and kept) and hide all UI."""
        self._measure_anchor = None
        self._measure_target = None
        self._cursor_pixel = None
        self._dragging_point = None
        self._dragging_kept_idx = None
        self._kept_measurements.clear()
        self._measure_panel._user_moved = False
        self._measure_panel.setVisible(False)
        for p in self._kept_measure_panels:
            p._user_moved = False
            p.setVisible(False)
        self._measure_overlay.update()

    def _on_kept_panel_right_click(self, panel: "_DraggablePanel") -> None:
        """Delete the kept measurement whose panel was right-clicked."""
        try:
            i = self._kept_measure_panels.index(panel)
        except ValueError:
            return
        menu = QMenu(self)
        delete_action = menu.addAction("Delete")
        if menu.exec(QCursor.pos()) == delete_action and i < len(self._kept_measurements):
            self._kept_measurements.pop(i)
            # Panels from i upward now show a different measurement → reset their positions
            for j in range(i, len(self._kept_measurements)):
                self._kept_measure_panels[j]._user_moved = False
            self._update_kept_measure_panels()
            self._measure_overlay.update()

    def _show_measurement_context_menu(self) -> None:
        """Show Keep/Delete context menu for the active measurement."""
        menu = QMenu(self)
        keep_action = menu.addAction("Keep")
        delete_action = menu.addAction("Delete")
        chosen = menu.exec(QCursor.pos())
        if chosen == keep_action:
            # Evict oldest if at capacity (all slots shift → reset all positions)
            evicted = len(self._kept_measurements) >= len(self._kept_measure_panels)
            if evicted:
                self._kept_measurements.pop(0)
                for p in self._kept_measure_panels:
                    p._user_moved = False
            self._kept_measurements.append((self._measure_anchor, self._measure_target))
            # Transfer the active panel's user position (if any) to the kept slot
            new_panel = self._kept_measure_panels[len(self._kept_measurements) - 1]
            if self._measure_panel._user_moved:
                new_panel._user_moved = True
                new_panel.move(self._measure_panel.pos())
            else:
                new_panel._user_moved = False
            self._update_kept_measure_panels()
            # Clear active so next right-click starts fresh
            self._measure_anchor = None
            self._measure_target = None
            self._measure_panel.setVisible(False)
            self._measure_overlay.update()
        elif chosen == delete_action:
            # Clear only the active measurement
            self._measure_anchor = None
            self._measure_target = None
            self._cursor_pixel = None
            self._dragging_point = None
            self._measure_panel.setVisible(False)
            self._measure_overlay.update()

    def on_mouse_button_press(self, event):
        """
        Handles mouse button press events to initiate panning.

        Args:
            event: The Matplotlib mouse button press event.
        """
        if self._toolbar_navigation_mode_active():
            self._enforce_equal_xy_on_toolbar_release = bool(
                event.inaxes
                and event.button == 3
                and (self._preserve_xy_ratio or self._ctrl_modifier_active(event))
            )
            return

        if event.button == 3 and event.inaxes:
            # Right-click near active target dot → Keep/Delete menu
            near_active_target = (
                self._measure_target is not None
                and self._is_near_dot(event.x, event.y, *self._measure_target)
            )
            if near_active_target:
                self._show_measurement_context_menu()
                return

            # Right-click near any kept target dot → Delete-only menu
            for i, (ka, kt) in enumerate(self._kept_measurements):
                near = self._is_near_dot(event.x, event.y, *kt)
                if near:
                    menu = QMenu(self)
                    delete_action = menu.addAction("Delete")
                    if menu.exec(QCursor.pos()) == delete_action:
                        self._kept_measurements.pop(i)
                        for j in range(i, len(self._kept_measurements)):
                            self._kept_measure_panels[j]._user_moved = False
                        self._update_kept_measure_panels()
                        self._measure_overlay.update()
                    return

            # State machine
            if self._measure_anchor is None or self._measure_target is not None:
                # State 0 / State 2 → State 1: start new measurement
                snap_x, snap_y = self._snap_anchor(event.x, event.y, event.xdata, event.ydata)
                self._measure_anchor = (snap_x, snap_y)
                self._measure_target = None
                self._measure_panel.setVisible(False)
            else:
                # State 1 → State 2: lock target
                snap_x, snap_y = self._snap_anchor(event.x, event.y, event.xdata, event.ydata)
                self._measure_target = (snap_x, snap_y)
                self._measure_panel._user_moved = False  # fresh placement for new target
                self._update_locked_measure_panel()
            self._measure_overlay.update()
            return

        if event.button == 1 and event.inaxes:
            # Left-click near a dot → start drag instead of pan
            if self._measure_anchor is not None and self._is_near_dot(event.x, event.y, *self._measure_anchor):
                self._dragging_point = "anchor"
                self.canvas.setCursor(Qt.CursorShape.ClosedHandCursor)
                return
            if self._measure_target is not None and self._is_near_dot(event.x, event.y, *self._measure_target):
                self._dragging_point = "target"
                self.canvas.setCursor(Qt.CursorShape.ClosedHandCursor)
                return
            for i, (ka, kt) in enumerate(self._kept_measurements):
                if self._is_near_dot(event.x, event.y, *ka):
                    self._dragging_point = "kept_anchor"
                    self._dragging_kept_idx = i
                    self.canvas.setCursor(Qt.CursorShape.ClosedHandCursor)
                    return
                if self._is_near_dot(event.x, event.y, *kt):
                    self._dragging_point = "kept_target"
                    self._dragging_kept_idx = i
                    self.canvas.setCursor(Qt.CursorShape.ClosedHandCursor)
                    return

            # Normal pan
            event.inaxes.start_pan(event.x, event.y, event.button)
            self._active_pan_button = event.button
            self._is_panning = True
            self.canvas.setCursor(Qt.CursorShape.ClosedHandCursor)

    def on_mouse_button_release(self, event):
        """
        Handles mouse button release events to stop panning.

        Args:
            event: The Matplotlib mouse button release event.
        """
        if self._toolbar_navigation_mode_active():
            if event.button == 3 and self._enforce_equal_xy_on_toolbar_release:
                self._apply_equal_xy_limits(self.ax.get_xlim(), self.ax.get_ylim())
                self.canvas.draw_idle()
            self._enforce_equal_xy_on_toolbar_release = False
            return

        if event.button == 1:
            if self._dragging_point is not None:
                self._dragging_point = None
                self._dragging_kept_idx = None
                self.canvas.setCursor(Qt.CursorShape.ArrowCursor)
                return

            if self._is_panning and event.inaxes:
                event.inaxes.end_pan()
                if self._preserve_xy_ratio:
                    self._apply_equal_xy_limits(self.ax.get_xlim(), self.ax.get_ylim())
                    self.canvas.draw_idle()
            self._is_panning = False
            self._active_pan_button = None
            self.canvas.setCursor(Qt.CursorShape.ArrowCursor)

    def on_mouse_move_on_plot(self, event):
        """
        Displays the cursor's coordinates on the plot and handles panning.

        Args:
            event: The Matplotlib motion notify event.
        """
        # Always track cursor pixel for the overlay
        if event.inaxes:
            self._cursor_pixel = (int(event.x), self.canvas.height() - int(event.y))

        # Handle drag mode — move anchor or target with snap
        if self._dragging_point is not None and event.inaxes:
            snap_x, snap_y = self._snap_anchor(event.x, event.y, event.xdata, event.ydata)
            if self._dragging_point == "anchor":
                self._measure_anchor = (snap_x, snap_y)
                if self._measure_target is not None:
                    self._update_locked_measure_panel()
                else:
                    self._measure_panel.setVisible(False)
            elif self._dragging_point == "target":
                self._measure_target = (snap_x, snap_y)
                self._update_locked_measure_panel()
            elif self._dragging_point == "kept_anchor" and self._dragging_kept_idx is not None:
                i = self._dragging_kept_idx
                _, kt = self._kept_measurements[i]
                self._kept_measurements[i] = ((snap_x, snap_y), kt)
                self._update_kept_measure_panels()
            elif self._dragging_point == "kept_target" and self._dragging_kept_idx is not None:
                i = self._dragging_kept_idx
                ka, _ = self._kept_measurements[i]
                self._kept_measurements[i] = (ka, (snap_x, snap_y))
                self._update_kept_measure_panels()
            self._measure_overlay.update()
            return

        if self._is_panning and event.inaxes and self._active_pan_button is not None:
            event.inaxes.drag_pan(self._active_pan_button, event.key, event.x, event.y)
            self.canvas.draw_idle()
            if self._measure_anchor is not None and self._measure_target is None:
                self._measure_overlay.update()
            return

        # Update overlay while in State 1 (anchor set, target not yet locked)
        if self._measure_anchor is not None and self._measure_target is None:
            self._measure_overlay.update()

        # Cursor: open hand when hovering over any grabbable dot, arrow otherwise
        if event.inaxes:
            near_any = (
                (self._measure_anchor is not None and self._is_near_dot(event.x, event.y, *self._measure_anchor))
                or (self._measure_target is not None and self._is_near_dot(event.x, event.y, *self._measure_target))
                or any(
                    self._is_near_dot(event.x, event.y, *ka) or self._is_near_dot(event.x, event.y, *kt)
                    for ka, kt in self._kept_measurements
                )
            )
            self.canvas.setCursor(
                Qt.CursorShape.OpenHandCursor if near_any else Qt.CursorShape.ArrowCursor
            )
        else:
            self.canvas.setCursor(Qt.CursorShape.ArrowCursor)

        # Coordinate display
        if event.inaxes:
            x_coord = f"{event.xdata:.3f}"
            y_coord = f"{event.ydata:.3f}"
            self.cursor_coord_label.setText(f"(Z, Y) = ({x_coord}, {y_coord})")
            self.cursor_coord_label.adjustSize()
            self.cursor_coord_label.move(5, 5)
            self.cursor_coord_label.setVisible(True)
            self.cursor_coord_label.raise_()
        else:
            self.cursor_coord_label.setVisible(False)

        # Measurement panel: only track cursor in State 1
        if self._measure_anchor is not None and self._measure_target is None:
            if event.inaxes:
                az, ay = self._measure_anchor
                dz = event.xdata - az
                dy = event.ydata - ay
                length = math.hypot(dz, dy)
                angle = math.degrees(math.atan2(dy, dz))
                self._measure_panel.setText(
                    f"ΔZ = {dz:+.3f} mm\nΔY = {dy:+.3f} mm\n"
                    f"L  = {length:.3f} mm\n∠X = {angle:.1f}°"
                )
                self._measure_panel.adjustSize()
                px = int(event.x) + 15
                py = self.canvas.height() - int(event.y) + 5
                px = min(px, self.canvas.width() - self._measure_panel.width() - 4)
                py = min(py, self.canvas.height() - self._measure_panel.height() - 4)
                py = max(py, 4)
                self._measure_panel.move(px, py)
                self._measure_panel.setVisible(True)
                self._measure_panel.raise_()
            else:
                self._measure_panel.setVisible(False)

    def on_scroll_zoom(self, event):
        """
        Implements zoom functionality using the mouse scroll wheel.

        Args:
            event: The Matplotlib scroll event.
        """
        if not event.inaxes:
            return

        ax = event.inaxes
        scale_factor = 1.1 if event.step < 0 else 1 / 1.1

        cur_xlim = ax.get_xlim()
        cur_ylim = ax.get_ylim()

        xdata = event.xdata
        ydata = event.ydata

        new_width = (cur_xlim[1] - cur_xlim[0]) * scale_factor
        new_height = (cur_ylim[1] - cur_ylim[0]) * scale_factor

        rel_x = (cur_xlim[1] - xdata) / (cur_xlim[1] - cur_xlim[0])
        rel_y = (cur_ylim[1] - ydata) / (cur_ylim[1] - cur_ylim[0])

        ax.set_xlim([xdata - new_width * (1 - rel_x), xdata + new_width * rel_x])
        ax.set_ylim([ydata - new_height * (1 - rel_y), ydata + new_height * rel_y])
        if self._preserve_xy_ratio:
            self._apply_equal_xy_limits(ax.get_xlim(), ax.get_ylim())
        ax.figure.canvas.draw_idle()

    def update_theme(self, theme="dark"):
        """
        Updates the theme of the Matplotlib plot.

        Args:
            theme (str, optional): The theme name ('dark' or 'light').
                                   Defaults to "dark".
        """
        if self.current_theme != theme:
            self.current_theme = theme
            gui_plot_utils.apply_gui_matplotlib_styles(theme=self.current_theme)
            self.plot_optic()
        else:
            gui_plot_utils.apply_gui_matplotlib_styles(theme=self.current_theme)
            gui_plot_utils.apply_theme_to_existing_figure(self.figure)
            self.canvas.draw_idle()
        self.settings_toggle_btn.setIcon(QIcon(f":/icons/{theme}/settings.svg"))
        self.toolbar.update_theme()

    def set_preserve_xy_ratio(self, preserve: bool) -> None:
        """Toggle equal X/Y scaling for the 2D layout plot."""
        self._preserve_xy_ratio = bool(preserve)
        self.plot_optic()

    def ray_count(self) -> int:
        """Return the currently selected 2D layout ray count."""
        return int(self.num_rays_spinbox.value())

    def ray_distribution(self) -> str:
        """Return the currently selected 2D layout ray distribution."""
        return self.dist_combo.currentText()

    def ray_distribution_for_3d(self) -> str:
        """Return a full-pupil distribution for the 3D layout."""
        distribution = self.ray_distribution()
        if distribution in {"line_x", "line_y"}:
            return "hexapolar"
        return distribution

    def ray_sampling_for_3d(self) -> tuple[int, str]:
        """Return 3D layout sampling without changing distribution semantics."""
        distribution = self.ray_distribution_for_3d()
        num_rays = self.ray_count()
        if self.ray_distribution() in {"line_x", "line_y"}:
            return self._hexapolar_rings_for_target_ray_count(num_rays), distribution
        return num_rays, distribution

    @staticmethod
    def _hexapolar_rings_for_target_ray_count(target_count: int) -> int:
        """Map a desired total ray count to hexapolar rings."""
        target_count = max(1, int(target_count))
        rings = round((math.sqrt(12 * target_count - 3) - 3) / 6)
        return max(1, int(rings))

    def _on_center_line_toggled(self, checked: bool) -> None:
        self.settings.setValue("Viewer2D/ShowCenterLine", bool(checked))
        self.plot_optic()

    @Slot()
    def apply_settings(self) -> None:
        """Apply 2D layout settings and notify coupled viewers."""
        self.plot_optic()
        self.settingsApplied.emit()

    def _apply_equal_xy_limits(
        self, xlim: tuple[float, float], ylim: tuple[float, float]
    ) -> None:
        """Expand the narrower axis span so one X unit matches one Y unit on screen."""
        bbox = self.ax.get_position()
        figure_width = max(float(self.figure.get_figwidth()), 1.0)
        figure_height = max(float(self.figure.get_figheight()), 1.0)
        box_ratio = max((bbox.width * figure_width) / (bbox.height * figure_height), 1e-6)

        x0, x1 = xlim
        y0, y1 = ylim
        x_span = max(abs(x1 - x0), 1e-9)
        y_span = max(abs(y1 - y0), 1e-9)
        target_x_span = y_span * box_ratio

        if target_x_span >= x_span:
            x_center = (x0 + x1) / 2.0
            x_half = target_x_span / 2.0
            self.ax.set_xlim(x_center - x_half, x_center + x_half)
            self.ax.set_ylim(y0, y1)
            return

        target_y_span = x_span / box_ratio
        y_center = (y0 + y1) / 2.0
        y_half = target_y_span / 2.0
        self.ax.set_xlim(x0, x1)
        self.ax.set_ylim(y_center - y_half, y_center + y_half)

    def _handle_toolbar_view_limits_changed(self) -> None:
        """Re-apply equal X/Y scaling after Matplotlib toolbar zoom changes limits."""
        if not self._preserve_xy_ratio:
            return
        self._apply_equal_xy_limits(self.ax.get_xlim(), self.ax.get_ylim())
        self.canvas.draw_idle()

    def plot_optic(self, preserve_zoom=False):
        """Redraws the 2D optical layout.

        Matplotlib's Qt backend creates QObjects during rendering and must stay
        on the main thread.  We show the BusyOverlay, then defer the actual
        plot by one event-loop cycle so the overlay paints before blocking.
        """
        if self._is_plotting:
            return
        self._is_plotting = True
        self._pending_preserve_zoom = preserve_zoom
        self._busy_overlay.show_busy()
        QTimer.singleShot(60, self._plot_optic_sync)

    def _plot_optic_sync(self, preserve_zoom=None):
        """Synchronous matplotlib render — must stay on the main thread."""
        if preserve_zoom is None:
            preserve_zoom = getattr(self, "_pending_preserve_zoom", False)
        try:
            gui_plot_utils.apply_gui_matplotlib_styles(theme=self.current_theme)
            should_preserve_limits = preserve_zoom or self._user_initiated_view_change
            xlim = self.ax.get_xlim() if should_preserve_limits else None
            ylim = self.ax.get_ylim() if should_preserve_limits else None
            self.ax.clear()
            face_color = matplotlib.rcParams["figure.facecolor"]
            self.figure.set_facecolor(face_color)
            self.ax.set_facecolor(face_color)
            optic = self.connector.get_effective_optic()
            num_rays = self.num_rays_spinbox.value()
            distribution = self.dist_combo.currentText()
            if optic and optic.surface_group.num_surfaces > 0:
                try:
                    rays2d_plotter = Rays2D(optic)
                    system_plotter = OptilandOpticalSystemPlotter(
                        optic, rays2d_plotter, projection="2d"
                    )
                    from optiland.visualization.themes import get_active_theme
                    theme = get_active_theme()
                    try:
                        rays2d_plotter.plot(
                            self.ax,
                            fields="all",
                            wavelengths="primary",
                            num_rays=num_rays,
                            distribution=distribution,
                            theme=theme,
                        )
                        setattr(self.connector, "_missing_stop_surface_warned", False)
                    except ValueError as exc:
                        if "No stop surface found." not in str(exc):
                            raise
                        self._notify_missing_stop_surface()
                    system_plotter.plot(self.ax, theme=theme)
                    self.ax.set_title(
                        f"System: {optic.name} (2D)",
                        color=matplotlib.rcParams["text.color"],
                    )
                    self.ax.set_xlabel("Z-axis (mm)")
                    self.ax.set_ylabel("Y-axis (mm)")
                    self.ax.grid(True, linestyle="--", alpha=0.7)
                    self.ax.set_aspect("auto")
                    if should_preserve_limits and xlim is not None and ylim is not None:
                        self.ax.set_xlim(xlim)
                        self.ax.set_ylim(ylim)
                    else:
                        self.ax.relim()
                        self.ax.autoscale_view()
                        self.ax.margins(x=0.03, y=0.08)
                    self.figure.subplots_adjust(
                        left=0.06, right=0.995, top=0.92, bottom=0.12
                    )
                    if self._preserve_xy_ratio:
                        self._apply_equal_xy_limits(self.ax.get_xlim(), self.ax.get_ylim())
                    if self.center_line_checkbox.isChecked():
                        self.ax.axhline(
                            y=0, color="yellow", linestyle="-.",
                            linewidth=0.9, alpha=0.85, zorder=1,
                        )
                except Exception:
                    self.ax.text(
                        0.5, 0.5, "Error plotting system", ha="center", va="center"
                    )
            else:
                self.ax.text(0.5, 0.5, "No system loaded", ha="center", va="center")
                self.figure.subplots_adjust(
                    left=0.06, right=0.995, top=0.92, bottom=0.12
                )
            gui_plot_utils.apply_theme_to_existing_figure(self.figure)
            self.canvas.draw()
        finally:
            self._is_plotting = False
            self._busy_overlay.hide_busy()


class VTKViewer(QWidget):
    """
    A widget for displaying a 3D rendering of the optical system using VTK.

    This viewer embeds a QVTKRenderWindowInteractor to provide an interactive
    3D view of the optical system and traced rays.

    Attributes:
        vtkWidget (QVTKRenderWindowInteractor): The VTK render window interactor widget.
        renderer (vtkRenderer): The VTK renderer for the scene.
        iren (vtkRenderWindowInteractor): The interactor for camera manipulation.
    """

    def __init__(self, connector: OptilandConnector, parent=None):
        """
        Initializes the VTKViewer.

        Args:
            connector (OptilandConnector): The connector to the main application logic.
            parent (QWidget, optional): The parent widget. Defaults to None.
        """
        super().__init__(parent)

        self.connector = connector
        self._last_num_rays = 24
        self._last_distribution = "ring"
        self._show_stop_apertures = True
        self._show_non_stop_apertures = True
        if not VTK_AVAILABLE:
            self.layout = QVBoxLayout(self)
            self.layout.addWidget(QLabel("VTK is not available."))
            return

        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.vtkWidget = QVTKRenderWindowInteractor(self)
        self.layout.addWidget(self.vtkWidget)

        self.renderer = vtk.vtkRenderer()
        self.vtkWidget.GetRenderWindow().AddRenderer(self.renderer)
        self.iren = self.vtkWidget.GetRenderWindow().GetInteractor()
        self.iren.SetInteractorStyle(vtk.vtkInteractorStyleTrackballCamera())
        self.setup_default_camera()
        self.iren.Initialize()
        self._busy_overlay = BusyOverlay(self)

    def setup_default_camera(self):
        """Sets up the default camera position and orientation for the 3D view."""
        self.renderer.SetBackground(0.1, 0.2, 0.4)
        camera = self.renderer.GetActiveCamera()
        if camera:
            camera.SetPosition(0.2, 0, 0)
            camera.SetFocalPoint(0, 0, 0)
            camera.SetViewUp(0, 1, 0)
            self.renderer.ResetCamera()
            camera.Elevation(0)
            camera.Azimuth(150)

    def update_theme(self, theme="dark", render: bool = True):
        """
        Updates the background color of the VTK renderer based on the theme.

        Args:
            theme (str, optional): The theme name ('dark' or 'light').
                                   Defaults to "dark".
        """
        from matplotlib.colors import to_rgb

        from optiland.visualization.themes import get_active_theme, set_theme

        set_theme(theme)
        active_theme = get_active_theme()
        background = to_rgb(active_theme.parameters["axes.facecolor"])
        self.renderer.SetBackground(*background)
        if render:
            self.render_optic()
        else:
            self.vtkWidget.GetRenderWindow().Render()

    def _notify_missing_stop_surface(self) -> None:
        """Warn once that 3D rays cannot be shown until a stop surface is defined."""
        if getattr(self.connector, "_missing_stop_surface_warned", False):
            return
        setattr(self.connector, "_missing_stop_surface_warned", True)
        message = (
            "No stop surface is defined. The optical layout is shown, but rays are hidden."
        )
        toast_manager = getattr(self.connector, "toast_manager", None)
        if toast_manager is not None:
            toast_manager.notify(message, "warning")
        else:
            logger.warning(message)

    def render_optic(
        self,
        num_rays: int | None = None,
        distribution: str | None = None,
        show_stop_apertures: bool | None = None,
        show_non_stop_apertures: bool | None = None,
    ):
        """Re-renders the 3D optical system on the main thread.

        VTK compiles OpenGL shaders eagerly when actors are added to a renderer,
        so it cannot run off the main thread.  We show the BusyOverlay, then
        defer the actual render by one event-loop cycle so the overlay paints
        before the (blocking) VTK call begins.
        """
        if num_rays is None:
            num_rays = self._last_num_rays
        if distribution is None:
            distribution = self._last_distribution
        if show_stop_apertures is not None:
            self._show_stop_apertures = show_stop_apertures
        if show_non_stop_apertures is not None:
            self._show_non_stop_apertures = show_non_stop_apertures
        self._last_num_rays = int(num_rays)
        self._last_distribution = distribution
        if not VTK_AVAILABLE:
            return

        self._busy_overlay.show_busy()
        # A short delay lets Qt process the overlay paint before we block.
        QTimer.singleShot(60, self._render_optic_sync)

    def _render_optic_sync(self):
        """Synchronous VTK render — must stay on the main thread (OpenGL context)."""
        try:
            self.renderer.RemoveAllViewProps()
            optic = self.connector.get_effective_optic()
            if (
                optic
                and optic.surface_group.num_surfaces > 0
                and hasattr(optic, "aperture")
                and optic.aperture is not None
            ):
                try:
                    from optiland.visualization.themes import get_active_theme
                    rays3d_plotter = Rays3D(optic)
                    system_plotter = OptilandOpticalSystemPlotter(
                        optic, rays3d_plotter, projection="3d"
                    )
                    theme = get_active_theme()
                    try:
                        rays3d_plotter.plot(
                            self.renderer,
                            fields="all",
                            wavelengths="primary",
                            num_rays=self._last_num_rays,
                            distribution=self._last_distribution,
                            theme=theme,
                        )
                        setattr(self.connector, "_missing_stop_surface_warned", False)
                    except ValueError as exc:
                        if "No stop surface found." not in str(exc):
                            raise
                        self._notify_missing_stop_surface()
                    system_plotter.plot(
                        self.renderer,
                        theme=theme,
                        show_stop_apertures=self._show_stop_apertures,
                        show_non_stop_apertures=self._show_non_stop_apertures,
                    )
                    if not self.renderer.GetActiveCamera():
                        self.setup_default_camera()
                    else:
                        self.renderer.ResetCameraClippingRange()
                        self.renderer.ResetCamera()
                except Exception as e:
                    print(f"VTKViewer Error: {e}")
                    textActor = vtk.vtkTextActor()
                    textActor.SetInput(f"Error rendering 3D view:\n{e}")
                    textActor.GetTextProperty().SetColor(1, 0, 0)
                    self.renderer.AddActor2D(textActor)
            else:
                if (
                    optic
                    and optic.surface_group.num_surfaces > 0
                    and (not hasattr(optic, "aperture") or optic.aperture is None)
                ):
                    textActor = vtk.vtkTextActor()
                    textActor.SetInput("Please set an aperture in System Properties.")
                    textActor.GetTextProperty().SetColor(1, 0, 0)
                    self.renderer.AddActor2D(textActor)
                sphereSource = vtk.vtkSphereSource()
                sphereSource.SetRadius(0.1)
                mapper = vtk.vtkPolyDataMapper()
                mapper.SetInputConnection(sphereSource.GetOutputPort())
                actor = vtk.vtkActor()
                actor.SetMapper(mapper)
                self.renderer.AddActor(actor)
                if not self.renderer.GetActiveCamera():
                    self.setup_default_camera()
                else:
                    self.renderer.ResetCamera()
            self.vtkWidget.GetRenderWindow().Render()
        finally:
            self._busy_overlay.hide_busy()
