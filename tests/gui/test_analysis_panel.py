"""Tests for the AnalysisPanel (analysis_panel.py) bug fixes."""

from __future__ import annotations

import inspect
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QToolButton


@pytest.fixture()
def mock_connector(minimal_optic, qapp):
    conn = MagicMock()
    conn._optic = minimal_optic
    conn.get_optic.return_value = minimal_optic
    conn.get_effective_optic.return_value = minimal_optic
    conn.toast_manager = MagicMock()
    conn.get_analysis_registry.return_value = []
    return conn


@pytest.fixture()
def panel(mock_connector, qapp):
    from optiland_gui.analysis_panel import AnalysisPanel

    return AnalysisPanel(mock_connector)


class TestMtfStringLiteralFix:
    """Verify the string-literal bug in the MTF max_freq condition is fixed."""

    def test_mtf_condition_uses_constants_not_strings(self, panel):
        """The MTF check must reference class constants, not quoted literals."""
        src = inspect.getsource(panel._prepare_filtered_args)
        # The fixed code should not contain the buggy string literals
        assert '"self.GEOMETRIC_MTF"' not in src
        assert '"self.FFT_MTF"' not in src


class TestFieldWavelengthDefaults:
    """Verify field/wavelength defaults are injected for wavefront/PSF analyses."""

    def test_defaults_injected_for_opd(self, panel, minimal_optic):
        """Missing field/wavelength are defaulted for OPD; given values are kept."""
        from optiland.wavefront import OPD

        filtered, _final = panel._prepare_filtered_args(minimal_optic, OPD, "OPD", {})
        assert filtered["optic"] is minimal_optic
        assert filtered["field"] == (0.0, 0.0)
        assert filtered["wavelength"] == "primary"

        filtered, _final = panel._prepare_filtered_args(
            minimal_optic, OPD, "OPD", {"field": (0.0, 1.0), "wavelength": 0.55}
        )
        assert filtered["field"] == (0.0, 1.0)
        assert filtered["wavelength"] == 0.55

    def test_opd_signature_has_field_and_wavelength(self):
        """OPD.__init__ must declare field and wavelength for injection to work."""
        import inspect

        from optiland.wavefront import OPD

        params = inspect.signature(OPD.__init__).parameters
        assert "field" in params
        assert "wavelength" in params

    def test_fft_psf_signature_has_field_and_wavelength(self):
        """FFTPSF must declare field and wavelength (via __new__ for factory types)."""
        import inspect

        from optiland.psf import FFTPSF

        # Factory-dispatch classes expose their real signature on __new__
        init_params = inspect.signature(FFTPSF.__init__).parameters
        new_params = inspect.signature(FFTPSF.__new__).parameters
        all_params = set(init_params) | set(new_params)
        assert "field" in all_params
        assert "wavelength" in all_params

    def test_zernike_opd_signature_has_field_and_wavelength(self):
        """ZernikeOPD must declare field and wavelength for injection to work."""
        import inspect

        try:
            from optiland.wavefront import ZernikeOPD
        except ImportError:
            pytest.skip("ZernikeOPD not available")

        params = inspect.signature(ZernikeOPD.__init__).parameters
        assert "field" in params
        assert "wavelength" in params


class TestAnalysisErrorsUseToast:
    """Verify analysis errors emit toasts instead of modal QMessageBoxes."""

    def test_analysis_error_calls_toast_not_msgbox(self, panel, mock_connector):
        """When an analysis raises, the toast manager should be called."""
        from optiland.analysis import SpotDiagram

        # Provide a valid optic so validation passes
        mock_connector.get_optic.return_value = mock_connector._optic

        # Patch SpotDiagram to raise on instantiation
        with patch.object(
            SpotDiagram, "__init__", side_effect=RuntimeError("test error")
        ):
            with patch("optiland_gui.analysis_panel.QMessageBox") as mock_msgbox:
                panel._execute_analysis(SpotDiagram, "Spot Diagram")
                # Toast must have been notified
                mock_connector.toast_manager.notify.assert_called()
                # QMessageBox.critical must NOT have been called
                mock_msgbox.critical.assert_not_called()

    def test_validation_uses_toast_for_empty_system(self, qapp):
        """System with no surfaces should trigger a toast, not a dialog."""
        from optiland.optic import Optic
        from optiland_gui.analysis_panel import AnalysisPanel

        empty_optic = Optic()
        conn = MagicMock()
        conn._optic = empty_optic
        conn.toast_manager = MagicMock()
        conn.get_analysis_registry.return_value = []

        p = AnalysisPanel(conn)
        with patch("optiland_gui.analysis_panel.QMessageBox") as mock_msgbox:
            result = p._validate_system_for_analysis(empty_optic)
            assert result is False
            conn.toast_manager.notify.assert_called()
            mock_msgbox.warning.assert_not_called()


class TestAnalysisViewArgFiltering:
    def test_draw_plot_filters_unknown_view_args(self, panel):
        """Canvas draw should not forward unsupported view kwargs to an analysis."""

        class _FakeCanvas:
            def __init__(self):
                from matplotlib.figure import Figure

                self.figure = Figure(figsize=(7, 5), dpi=100)

        class _FakeAnalysis:
            def __init__(self):
                self.called = None

            def view(self, fig_to_plot_on=None, cmap=None):  # noqa: ANN001
                self.called = {"fig_to_plot_on": fig_to_plot_on, "cmap": cmap}
                ax = fig_to_plot_on.add_subplot(111)
                return ax

        analysis = _FakeAnalysis()
        canvas = _FakeCanvas()

        panel._draw_plot_on_canvas(
            analysis,
            canvas,
            {"cmap": "viridis", "add_airy_disk": True},
        )

        assert analysis.called is not None
        assert analysis.called["fig_to_plot_on"] is canvas.figure
        assert analysis.called["cmap"] == "viridis"

    def test_draw_plot_rethemes_existing_figure(self, panel, monkeypatch):
        """Embedded analysis draws should retheme an existing figure after plotting."""

        class _FakeCanvas:
            def __init__(self):
                from matplotlib.figure import Figure

                self.figure = Figure(figsize=(7, 5), dpi=100)

        class _FakeAnalysis:
            def view(self, fig_to_plot_on=None):  # noqa: ANN001
                ax = fig_to_plot_on.add_subplot(111)
                return ax

        calls: list[object] = []
        monkeypatch.setattr(
            "optiland_gui.analysis_panel.gui_plot_utils.apply_theme_to_existing_figure",
            lambda figure: calls.append(figure),
        )

        canvas = _FakeCanvas()
        panel._draw_plot_on_canvas(_FakeAnalysis(), canvas, {})

        assert calls == [canvas.figure]


class TestAnalysisToolbarThemeing:
    def test_analysis_icon_only_buttons_match_viewer_button_type(self, panel):
        """Icon-only analysis controls should use the same tool button class as viewer toolbars."""
        assert isinstance(panel.btnRun, QToolButton)
        assert isinstance(panel.btnRunAll, QToolButton)
        assert isinstance(panel.btnStop, QToolButton)
        assert isinstance(panel.btnRefreshPlot, QToolButton)
        assert isinstance(panel.toggleSettingsButton, QToolButton)

    def test_embedded_analysis_toolbar_uses_expected_object_name(self, panel):
        """Embedded analysis backend toolbar should expose the QSS hook object name."""
        canvas = panel._create_new_plot_canvas({"figsize": (7, 5)})

        panel._setup_plot_toolbar(canvas)

        assert panel.active_mpl_toolbar_widget is not None
        assert panel.active_mpl_toolbar_widget.objectName() == "AnalysisPlotToolbarTitle"
        assert panel.active_mpl_toolbar_widget.isHidden() is True

    def test_embedded_analysis_toolbar_applies_local_fixed_button_geometry(self, panel):
        """Analysis should render a local left-aligned QToolButton strip for MPL actions."""
        from optiland_gui.config import CONTROL_HEIGHT_PX

        canvas = panel._create_new_plot_canvas({"figsize": (7, 5)})
        panel._setup_plot_toolbar(canvas)
        toolbar = panel.active_mpl_toolbar_widget

        assert toolbar is not None
        assert panel.active_mpl_toolbar_buttons

        for button in panel.active_mpl_toolbar_buttons:
            assert button.minimumWidth() == CONTROL_HEIGHT_PX
            assert button.maximumWidth() == CONTROL_HEIGHT_PX
            assert button.minimumHeight() == CONTROL_HEIGHT_PX
            assert button.maximumHeight() == CONTROL_HEIGHT_PX
            assert button.parent() is panel.mpl_toolbar_in_titlebar_container

    def test_plot_title_bar_layout_uses_vertical_padding(self, panel):
        """Analysis plot title bar should keep some vertical breathing room."""
        margins = panel.plot_area_title_bar_layout.contentsMargins()

        assert margins.top() == 2
        assert margins.bottom() == 2
        assert panel.plot_area_title_bar_layout.spacing() == 6

    def test_viewer_toolbar_qss_keeps_padding_and_radius_in_final_override(self):
        """Final viewer-toolbar QSS overrides should preserve the shared button geometry."""
        styles_dir = (
            Path(__file__).resolve().parents[2]
            / "optiland_gui"
            / "resources"
            / "styles"
        )

        for theme_name in ("dark_theme.qss", "light_theme.qss"):
            content = (styles_dir / theme_name).read_text(encoding="utf-8")
            final_block = content.rsplit(
                "#ViewerToolbarContainer QToolButton,\nQToolBar#QuickActionsToolbar QToolButton {",
                1,
            )[-1]
            assert "#ViewerToolbarContainer QToolButton {\n    padding: 1px;\n    border-radius: 4px;\n}" in final_block

    def test_shared_control_override_matches_analysis_and_viewer_toolbar_geometry(self):
        """The shared control override should enforce identical geometry for viewer and analysis toolbars."""
        config_path = (
            Path(__file__).resolve().parents[2] / "optiland_gui" / "config.py"
        )
        content = config_path.read_text(encoding="utf-8")

        assert "#ViewerToolbarContainer QToolButton {{" in content
        assert "QToolBar#AnalysisPlotToolbarTitle QToolButton {{" in content

    def test_dark_analysis_toolbar_qss_uses_full_toolbutton_height(self):
        """Dark analysis toolbar should not clamp the embedded MPL toolbar too short."""
        styles_path = (
            Path(__file__).resolve().parents[2]
            / "optiland_gui"
            / "resources"
            / "styles"
            / "dark_theme.qss"
        )
        content = styles_path.read_text(encoding="utf-8")

        assert "QToolBar#AnalysisPlotToolbarTitle" in content
        assert "min-height: 26px;" in content
        assert "max-height: 26px;" in content

    def test_dark_analysis_toolbar_qss_targets_visible_button_strip(self):
        """Dark MPL toolbar styling must hit the reparented visible buttons."""
        styles_path = (
            Path(__file__).resolve().parents[2]
            / "optiland_gui"
            / "resources"
            / "styles"
            / "dark_theme.qss"
        )
        content = styles_path.read_text(encoding="utf-8")

        assert (
            "QWidget#MPLToolbarInTitlebarContainer QToolButton,\n"
            "AnalysisPanel QFrame#PlotDisplayFrame QToolBar#AnalysisPlotToolbarTitle"
            " QToolButton {"
        ) in content
        assert (
            "QWidget#MPLToolbarInTitlebarContainer QToolButton:hover,\n"
            "AnalysisPanel QFrame#PlotDisplayFrame QToolBar#AnalysisPlotToolbarTitle"
            " QToolButton:hover {"
        ) in content
        assert (
            "QWidget#MPLToolbarInTitlebarContainer QToolButton:checked,\n"
            "AnalysisPanel QFrame#PlotDisplayFrame QToolBar#AnalysisPlotToolbarTitle"
            " QToolButton:pressed"
        ) in content

    def test_light_analysis_toolbar_qss_matches_toolbar_height(self):
        """Light analysis toolbar should use the same explicit toolbar height."""
        styles_path = (
            Path(__file__).resolve().parents[2]
            / "optiland_gui"
            / "resources"
            / "styles"
            / "light_theme.qss"
        )
        content = styles_path.read_text(encoding="utf-8")

        assert "QToolBar#AnalysisPlotToolbarTitle" in content
        assert "min-height: 26px;" in content
        assert "max-height: 26px;" in content

    def test_toolbar_uses_application_palette_for_icon_tint(self, qapp):
        """Toolbar icon tint should follow the live theme's text color."""
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
        from matplotlib.figure import Figure

        from optiland_gui.analysis_panel import CustomMatplotlibToolbar

        figure = Figure(figsize=(4, 3), dpi=100)
        canvas = FigureCanvas(figure)
        toolbar = CustomMatplotlibToolbar(canvas)

        qapp.setProperty("activeThemeId", "tokyo_night")

        widget_palette = toolbar.palette()
        widget_palette.setColor(QPalette.ColorRole.ButtonText, QColor("#050505"))
        toolbar.setPalette(widget_palette)

        tint = toolbar._toolbar_foreground_color()

        assert tint.name().lower() == "#c0caf5"


class _LinePlotAnalysis:
    """Minimal embeddable analysis drawing a single subplot."""

    def view(self, fig_to_plot_on=None):  # noqa: ANN001
        ax = fig_to_plot_on.add_subplot(111)
        ax.plot([0.0, 1.0], [0.0, 1.0])
        return ax


def _plot_page(name="Line Plot", **extra):
    return {
        "name": name,
        "analysis_instance": _LinePlotAnalysis(),
        "plot_type": "embedded_mpl",
        "view_args": {},
        "constructor_args_used": {},
        **extra,
    }


def _send_wheel(widget, x, y, delta_y=-120):
    """Deliver a mouse-wheel step at widget-local (x, y), with Qt propagation."""
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtWidgets import QApplication

    local = QPointF(x, y)
    event = QWheelEvent(
        local,
        widget.mapToGlobal(local),
        QPoint(0, 0),
        QPoint(0, delta_y),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    QApplication.sendEvent(widget, event)


@pytest.fixture()
def shown_panel(panel, qapp):
    """The panel on screen, so the plot scroll area has a real viewport size."""
    panel.resize(900, 700)
    panel.show()
    qapp.processEvents()
    yield panel
    panel.resize_timer.stop()
    panel.close()


class TestPlotZoom:
    def test_zoom_slider_appears_with_a_plot(self, panel):
        """The toolbar zoom slider spans 100-400 % and shows only for a plot."""
        assert panel.plotZoomSlider.minimum() == 100
        assert panel.plotZoomSlider.maximum() == 400
        assert panel.plot_zoom_container.isHidden()

        panel.analysis_results_pages.append(_plot_page())
        panel.switch_plot_page(0)

        assert not panel.plot_zoom_container.isHidden()
        assert panel.plotZoomSlider.value() == 100
        assert panel.plotZoomLabel.text() == "100%"

    def test_zoom_enlarges_the_canvas_beyond_the_viewport(self, shown_panel, qapp):
        """Zooming gives the figure more pixels and makes the plot scrollable."""
        panel = shown_panel
        panel.analysis_results_pages.append(_plot_page())
        panel.switch_plot_page(0)
        qapp.processEvents()
        area = panel.plot_zoom_area
        canvas = panel.active_mpl_canvas_widget
        viewport = area.maximumViewportSize()
        assert canvas.size() == viewport

        panel.plotZoomSlider.setValue(250)
        # The enlarged figure is laid out again once the resize settles.
        assert panel.resize_timer.isActive()
        qapp.processEvents()

        assert canvas.width() == round(viewport.width() * 2.5)
        assert canvas.height() == round(viewport.height() * 2.5)
        assert canvas.figure.bbox.width == pytest.approx(
            canvas.width() * canvas.device_pixel_ratio
        )
        assert area.verticalScrollBar().maximum() > 0
        assert panel.plotZoomLabel.text() == "250%"
        assert panel.analysis_results_pages[0]["zoom_percent"] == 250

    def test_zoom_is_remembered_per_page(self, shown_panel):
        """Each result page keeps its own zoom when switching between pages."""
        panel = shown_panel
        panel.analysis_results_pages.extend([_plot_page("A"), _plot_page("B")])
        panel.switch_plot_page(0)
        panel.plotZoomSlider.setValue(300)

        panel.switch_plot_page(1)
        viewport = panel.plot_zoom_area.maximumViewportSize()
        assert panel.plotZoomSlider.value() == 100
        assert panel.active_mpl_canvas_widget.size() == viewport

        panel.switch_plot_page(0)
        assert panel.plotZoomSlider.value() == 300
        assert panel.plotZoomLabel.text() == "300%"
        assert panel.active_mpl_canvas_widget.width() == round(viewport.width() * 3)

    def test_clone_and_rerun_keep_the_page_zoom(self, panel, monkeypatch):
        """Cloning a page and re-running its analysis must not reset the zoom."""
        panel.analysis_results_pages.append(_plot_page(zoom_percent=250))
        panel.switch_plot_page(0)

        panel._clone_analysis_page(0)
        assert panel.analysis_results_pages[1]["zoom_percent"] == 250

        monkeypatch.setattr(
            panel,
            "_execute_analysis_threaded",
            lambda *_args, on_complete, **_kwargs: on_complete(_plot_page()),
        )
        panel._apply_settings_and_rerun_analysis_slot()

        assert panel.analysis_results_pages[1]["zoom_percent"] == 250
        assert panel.plotZoomSlider.value() == 250

    def test_wheel_outside_axes_scrolls_the_enlarged_plot(self, shown_panel, qapp):
        """Off the axes the wheel scrolls the plot; over them it zooms the axes."""
        panel = shown_panel
        panel.analysis_results_pages.append(_plot_page(zoom_percent=300))
        panel.switch_plot_page(0)
        qapp.processEvents()
        canvas = panel.active_mpl_canvas_widget
        ax = canvas.figure.axes[0]
        bar = panel.plot_zoom_area.verticalScrollBar()
        assert bar.maximum() > 0
        limits = (ax.get_xlim(), ax.get_ylim())

        _send_wheel(canvas, 2, 2)

        assert bar.value() > 0
        assert (ax.get_xlim(), ax.get_ylim()) == limits

        bar.setValue(0)
        _send_wheel(canvas, canvas.width() / 2, canvas.height() / 2)

        assert bar.value() == 0
        assert (ax.get_xlim(), ax.get_ylim()) != limits


@pytest.fixture()
def surface_panel(mock_connector, minimal_optic, qapp):
    from optiland.analysis import FootprintDiagram, SpotDiagram
    from optiland_gui.analysis_panel import AnalysisPanel

    mock_connector._analysis_runner.get_analysis_registry.return_value = [
        ("Spot & Ray", "Spot Diagram", SpotDiagram),
        ("Illumination", "Footprint Diagram", FootprintDiagram),
    ]
    mock_connector.get_surface_count.return_value = minimal_optic.surfaces.num_surfaces
    mock_connector.get_disabled_surface_indices.return_value = set()
    return AnalysisPanel(mock_connector)


class TestSurfaceAnalyses:
    def test_surface_setting_is_numbered_like_the_editor(self, surface_panel):
        surface_panel._update_settings_ui("Footprint Diagram")

        widget = surface_panel.current_settings_widgets["surface_idx"]
        label = surface_panel.settings_form_layout.labelForField(widget)
        assert widget.minimum() == -1
        assert widget.value() == -1
        assert widget.specialValueText() == "Image"
        assert label.text() == "Surface:"

    def test_editor_surface_numbers_skip_disabled_surfaces(
        self, surface_panel, mock_connector, minimal_optic
    ):
        from optiland.analysis import FootprintDiagram

        mock_connector.get_disabled_surface_indices.return_value = {1}

        def analysed_surface(editor_number):
            filtered, _ = surface_panel._prepare_filtered_args(
                minimal_optic,
                FootprintDiagram,
                "Footprint Diagram",
                {"surface_idx": editor_number},
            )
            return filtered["surface_idx"]

        assert analysed_surface(2) == 1
        assert analysed_surface(-1) == -1
        with pytest.raises(ValueError, match="disabled"):
            analysed_surface(1)
        with pytest.raises(ValueError, match="object surface"):
            analysed_surface(0)
        with pytest.raises(ValueError, match="does not exist"):
            analysed_surface(4)

    def test_plot_names_the_surface_by_its_editor_row(
        self, surface_panel, minimal_optic
    ):
        minimal_optic.surfaces[2].comment = "Stop"
        # As computed on an effective optic without a disabled surface 1.
        instance = SimpleNamespace(
            surface_label="Surface 1: Stop", view=lambda fig_to_plot_on=None: None
        )

        surface_panel._finish_analysis(
            instance, "Footprint Diagram", {"surface_idx": 2}, {}, minimal_optic, {}
        )

        assert instance.surface_label == "Surface 2: Stop"

    def test_run_surface_analysis_opens_a_page_for_the_surface(
        self, surface_panel, minimal_optic, monkeypatch
    ):
        minimal_optic.surfaces[2].comment = "Stop"

        def run_now(
            analysis_class,
            analysis_name,
            constructor_args=None,
            view_args=None,
            on_complete=None,
        ):
            on_complete(
                surface_panel._execute_analysis(
                    analysis_class, analysis_name, constructor_args, view_args
                )
            )

        monkeypatch.setattr(surface_panel, "_execute_analysis_threaded", run_now)

        surface_panel.run_surface_analysis("Footprint Diagram", 2)

        page = surface_panel.analysis_results_pages[-1]
        figure = surface_panel.active_mpl_canvas_widget.figure
        assert surface_panel.analysisTypeCombo.currentText() == "Footprint Diagram"
        assert page["constructor_args_used"]["surface_idx"] == 2
        assert "Surface 2: Stop" in figure.get_suptitle()
