"""Tests for the non-sequential panel and its document service."""

from __future__ import annotations

import logging
import time
import warnings
from unittest.mock import MagicMock

import numpy as np
import pytest
from PySide6.QtCore import QCoreApplication

from optiland_gui.nsq_panel import NSQPanel
from optiland_gui.services.nsq_service import NSQService


def _connector() -> MagicMock:
    connector = MagicMock()
    connector.toast_manager = MagicMock()
    return connector


def _wait_for(predicate, timeout_s: float = 60.0) -> bool:
    """Spin the Qt event loop until *predicate* holds or the timeout passes."""
    deadline = time.monotonic() + timeout_s
    while not predicate():
        QCoreApplication.processEvents()
        if time.monotonic() > deadline:
            return False
        time.sleep(0.01)
    return True


class TestNSQService:
    def test_load_sample_builds_a_scene_and_clears_the_result(self, qapp):
        service = NSQService()
        changed = []
        service.sceneChanged.connect(lambda: changed.append(True))

        service.load_sample("beam_splitter")

        assert service.scene is not None
        assert service.scene_label == "Beam splitter: one beam, two arms"
        assert service.result is None
        assert changed == [True]

    def test_trace_sync_returns_a_result_and_emits(self, qapp):
        service = NSQService()
        service.load_sample("beam_splitter")
        finished = []
        service.traceFinished.connect(finished.append)

        result = service.trace_sync(num_rays=512, seed=3, record_paths=100)

        assert service.result is result
        assert finished == [result]
        assert set(result.detectors) == {"transmitted", "reflected"}
        assert result.total_flux_detected == pytest.approx(1.0, abs=1e-9)
        assert result.ray_paths is not None

    def test_split_depth_makes_the_arm_powers_exact(self, qapp):
        service = NSQService()
        service.load_sample("beam_splitter")
        service.set_sampling(1)
        result = service.trace_sync(num_rays=256, seed=1, record_paths=0)
        assert result.detectors["transmitted"].total_flux_float == pytest.approx(0.5)
        assert result.detectors["reflected"].total_flux_float == pytest.approx(0.5)
        assert result.ray_paths is None

    def test_save_and_load_round_trip(self, qapp, tmp_path):
        service = NSQService()
        service.load_sample("side_illumination")
        path = tmp_path / "scene.json"

        service.save_file(str(path))
        assert service.scene_path == str(path)
        assert service.scene_label == "scene.json"

        other = NSQService()
        other.load_file(str(path))
        assert other.scene.detector_names == service.scene.detector_names
        assert other.scene.source_names == ["illumination", "object"]

    def test_trace_without_scene_raises(self, qapp):
        service = NSQService()
        with pytest.raises(RuntimeError):
            service.trace_sync(num_rays=10)
        assert service.trace_async(num_rays=10) is False

    def test_trace_async_delivers_on_the_gui_thread(self, qapp):
        service = NSQService()
        service.load_sample("beam_splitter")
        finished = []
        service.traceFinished.connect(finished.append)

        assert service.trace_async(num_rays=2000, seed=2, record_paths=50)
        assert service.is_tracing
        # A second start while running is refused rather than queued.
        assert service.trace_async(num_rays=10) is False
        assert _wait_for(lambda: finished)
        assert service.wait()

        assert not service.is_tracing
        assert service.result is finished[0]
        assert finished[0].num_rays_total == 2000

    def test_summary_rows_cover_detectors_and_energy_balance(self, qapp):
        service = NSQService()
        assert service.summary_rows() == []
        service.load_sample("beam_splitter")
        service.trace_sync(num_rays=128, seed=1, record_paths=0)
        labels = [label for label, _ in service.summary_rows()]
        assert "Detector 'transmitted'" in labels
        assert "Detector 'reflected'" in labels
        assert "Conservation error" in labels
        assert "Trace time" in labels


class TestNSQPanel:
    @pytest.fixture()
    def panel(self, qapp):
        panel = NSQPanel(_connector())
        panel.resize(1000, 700)
        yield panel
        panel.close()

    def test_panel_starts_with_the_first_sample_scene(self, panel):
        assert panel.service.scene is not None
        assert panel.scene_combo.currentData() == "beam_splitter"
        # The pull-down names the system; there is no separate label.
        assert panel.scene_combo.currentText() == "Beam splitter: one beam, two arms"
        # The layout is drawn even before any trace: components and
        # detectors show up as lines.
        ax = panel.layout_figure.axes[0]
        assert len(ax.get_lines()) >= 3

    def test_selecting_a_sample_reloads_the_scene(self, panel):
        index = panel.scene_combo.findData("side_illumination")
        panel.scene_combo.setCurrentIndex(index)
        panel.scene_combo.activated.emit(index)

        assert panel.service.scene_label.startswith("Side illumination")
        assert set(panel.service.scene.detector_names) == {
            "sample",
            "camera",
            "illumination_dump",
            "return",
        }

    def test_sync_trace_fills_all_three_tabs(self, panel):
        panel.rays_spin.setValue(1000)
        panel.paths_spin.setValue(100)
        panel.split_spin.setValue(1)

        result = panel.run_trace_sync()

        assert result.detectors["transmitted"].total_flux_float == pytest.approx(0.5)
        # Layout: rays overlaid on top of the scene lines.
        layout_ax = panel.layout_figure.axes[0]
        assert len(layout_ax.get_lines()) > 20
        # Detectors: one image per irradiance map.
        images = [ax for ax in panel.detector_figure.axes if ax.get_images()]
        assert len(images) == 2
        # Summary: detector rows and diagnostics report.
        labels = [
            panel.summary_table.item(r, 0).text()
            for r in range(panel.summary_table.rowCount())
        ]
        assert "Detector 'transmitted'" in labels
        assert "Detector 'reflected'" in labels
        assert panel.report_text.toPlainText() != ""

    def test_layout_axes_fill_the_canvas(self, panel):
        """Equal scale must expand the data limits, not shrink the axes."""
        panel.rays_spin.setValue(500)
        panel.run_trace_sync()
        panel.layout_figure.set_size_inches(12, 5)
        panel.layout_canvas.draw()

        ax = panel.layout_figure.axes[0]
        box = ax.get_position()
        full = ax.get_position(original=True)
        assert box.width == pytest.approx(full.width, rel=0.02)
        assert box.height == pytest.approx(full.height, rel=0.02)
        assert ax.get_aspect() == 1.0

    def test_zoomed_view_redraws_without_aspect_warnings(self, panel, caplog):
        """O2: a zoom or pan fixes the limits, and every redraw of the
        equal-scale layout logged "Ignoring fixed y limits to fulfill fixed
        data aspect with adjustable data limits"."""
        panel.layout_figure.set_size_inches(10, 5)
        panel.layout_canvas.draw()
        ax = panel.layout_figure.axes[0]
        (x0, x1), (y0, y1) = ax.get_xlim(), ax.get_ylim()
        ax.set_xlim(x0 + 0.2 * (x1 - x0), x1 - 0.2 * (x1 - x0))
        ax.set_ylim(y0 + 0.1 * (y1 - y0), y1 - 0.3 * (y1 - y0))

        with caplog.at_level(logging.WARNING, logger="matplotlib"):
            panel.layout_canvas.draw()
            panel.navigation.remember_view(ax)
            view = panel.navigation._view
            panel._draw_layout(preserve_view=True)
            panel.layout_canvas.draw()

        assert [r.getMessage() for r in caplog.records] == []
        ax = panel.layout_figure.axes[0]
        box, full = ax.get_position(), ax.get_position(original=True)
        assert box.width == pytest.approx(full.width, rel=0.02)
        assert box.height == pytest.approx(full.height, rel=0.02)
        assert np.mean(ax.get_xlim()) == pytest.approx(np.mean(view[0]))
        assert np.mean(ax.get_ylim()) == pytest.approx(np.mean(view[1]))

    def test_detector_maps_stay_centred_on_a_flat_canvas(self, panel):
        """O5: on a flat Detectors tab (690 x 140 px) each map was pushed to
        the right edge of its cell, because ``colorbar(ax=ax)`` re-anchors
        the equal-aspect map there, and the right title ran off the figure."""
        panel.rays_spin.setValue(1000)
        panel.run_trace_sync()
        figure = panel.detector_figure
        figure.set_size_inches(690 / figure.dpi, 140 / figure.dpi)
        panel.detector_canvas.draw()

        renderer = panel.detector_canvas.get_renderer()
        maps = [ax for ax in figure.axes if ax.get_images()]
        assert len(maps) == 2
        for ax in maps:
            box, cell = ax.get_position(), ax.get_position(original=True)
            # Centred in its layout cell and as tall as the cell allows.
            assert (box.x0 + box.x1) / 2 == pytest.approx((cell.x0 + cell.x1) / 2)
            assert box.height == pytest.approx(cell.height, rel=0.02)
            # The colour bar sits right next to the map.
            (cax,) = ax.child_axes
            gap = cax.get_position().x0 - box.x1
            assert 0.0 < gap < 0.05
            title = ax.title.get_window_extent(renderer)
            assert title.x0 >= 0.0
            assert title.x1 <= figure.bbox.width

    def test_masks_stay_red_in_the_active_path(self, panel):
        """O4: masks are red in the System view like in the 2D/3D layout;
        highlighting the active path thickens them but keeps the colour."""
        from matplotlib.colors import same_color

        from optiland.nonsequential.system import MultiAxisSystem
        from optiland.visualization.system.system import MASK_COLOR
        from tests.nonsequential.test_nsq_surface_rendering import masked_optic

        system = MultiAxisSystem.from_optic(masked_optic(), "Masked")
        panel.service.set_system(system, "masked")
        panel.activate_path("Masked")
        assert panel.service.active_path == "Masked"

        lines = {
            line.get_label(): line for line in panel.layout_figure.axes[0].get_lines()
        }
        for name in ("S1.mask", "S2.obscuration"):
            assert same_color(lines[name].get_color(), MASK_COLOR), name
            assert lines[name].get_linewidth() == 3.0
        assert not same_color(lines["S1.rim"].get_color(), MASK_COLOR)
        assert lines["S1.rim"].get_linewidth() == 3.0

    def test_title_stays_inside_after_the_canvas_shrinks(self, panel):
        """A dock made shorter after the first draw must not clip the title."""
        panel.layout_figure.set_size_inches(8, 6)
        panel.layout_canvas.draw()
        panel.layout_figure.set_size_inches(8, 2.2)
        panel.layout_canvas.draw()

        ax = panel.layout_figure.axes[0]
        assert ax.get_title()
        renderer = panel.layout_canvas.get_renderer()
        title_top = ax.title.get_window_extent(renderer).y1
        assert title_top <= panel.layout_figure.bbox.height + 0.5
        tick_bottom = min(
            label.get_window_extent(renderer).y0 for label in ax.get_xticklabels()
        )
        assert tick_bottom >= -0.5

    def test_projection_change_redraws_the_layout(self, panel):
        before = panel.layout_figure.axes[0].get_xlabel()
        panel.projection_combo.setCurrentText("YZ")
        after = panel.layout_figure.axes[0].get_xlabel()
        assert before == "Z [mm]"
        assert after == "Z [mm]"
        assert panel.layout_figure.axes[0].get_ylabel() == "Y [mm]"

    def test_theme_update_redraws_without_error(self, panel):
        panel.run_trace_sync()
        panel.update_theme("light")
        assert panel.current_theme == "light"
        assert panel.layout_figure.axes

    def test_async_trace_reenables_the_button(self, panel):
        panel.rays_spin.setValue(1500)
        panel.paths_spin.setValue(50)
        finished = []
        panel.service.traceFinished.connect(finished.append)

        panel.trace_button.click()
        assert not panel.trace_button.isEnabled()
        assert _wait_for(lambda: finished)
        assert panel.service.wait()
        QCoreApplication.processEvents()

        assert panel.trace_button.isEnabled()
        assert panel.summary_table.rowCount() > 0
        transmitted = panel.service.result.detectors["transmitted"].irradiance
        assert np.asarray(transmitted).sum() > 0.0


# ---------------------------------------------------------------------------
# Rendering: no collapsed constrained layouts
# ---------------------------------------------------------------------------


class TestCanvasRendering:
    """Regression (2026-09-22 session log): "constrained_layout not applied
    because axes sizes collapsed to zero" after every edit in the Lens Data
    Editor. Every rebuild rendered both figures, also while the System view
    or the Detectors tab was hidden, at the size the canvas had when it was
    last laid out; and the Detectors placeholder text counted for the
    layout, so any canvas narrower than the text (~330 px) collapsed."""

    @staticmethod
    def _collapse_warnings(qapp, action) -> list:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            action()
            _settle(qapp)
        return [
            w for w in caught if "constrained_layout not applied" in str(w.message)
        ]

    @staticmethod
    def _record_draws(panel) -> list[str]:
        drawn: list[str] = []
        panel.layout_canvas.mpl_connect(
            "draw_event", lambda _event: drawn.append("layout")
        )
        panel.detector_canvas.mpl_connect(
            "draw_event", lambda _event: drawn.append("detectors")
        )
        return drawn

    def test_hidden_canvases_are_not_rendered_on_redraw(self, qapp):
        panel = NSQPanel(_connector())
        try:
            _settle(qapp)
            # Figure sizes a canvas kept from its last layout in a small dock.
            panel.layout_figure.set_size_inches(2.5, 0.5)
            panel.detector_figure.set_size_inches(2.5, 2.0)
            drawn = self._record_draws(panel)

            caught = self._collapse_warnings(qapp, panel.redraw)

            assert caught == []
            assert drawn == []
        finally:
            panel.close()

    def test_a_hidden_canvas_is_rendered_when_it_is_shown(self, qapp):
        panel = NSQPanel(_connector())
        panel.resize(1000, 700)
        try:
            panel.redraw()
            drawn = self._record_draws(panel)

            panel.show()
            _settle(qapp)
            assert "layout" in drawn
            assert "detectors" not in drawn  # its tab is still hidden

            panel.tabs.setCurrentIndex(1)
            _settle(qapp)
            assert "detectors" in drawn
        finally:
            panel.close()

    def test_the_detector_placeholder_fits_a_narrow_canvas(self, qapp):
        panel = NSQPanel(_connector())
        try:
            panel.detector_figure.set_size_inches(2.5, 3.0)

            caught = self._collapse_warnings(qapp, panel.detector_canvas.draw)

            assert caught == []
            box = panel.detector_figure.axes[0].get_position()
            assert box.width > 0.8
            assert box.height > 0.8
        finally:
            panel.close()


# ---------------------------------------------------------------------------
# Compact controls: the System view is a tab of the System Viewer now
# ---------------------------------------------------------------------------


def _app_style_sheet() -> str:
    """The style sheet the main window applies (default theme)."""
    from optiland_gui.config import build_control_size_override
    from optiland_gui.theme_manager import (
        DEFAULT_THEME_ID,
        build_palette_override,
        get_theme,
    )

    theme = get_theme(DEFAULT_THEME_ID)
    with open(theme.base_path, encoding="utf-8") as handle:
        base = handle.read()
    return "\n".join(
        (base, build_palette_override(theme), build_control_size_override())
    )


def _settle(qapp, ms: int = 80) -> None:
    from PySide6.QtCore import QDeadlineTimer, QEventLoop

    deadline = QDeadlineTimer(ms)
    while not deadline.hasExpired():
        qapp.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 10)


def _groups(panel) -> list:
    """The labelled fields (and buttons) of the trace/view row."""
    flow = panel.controls_widget.layout()
    return [flow.itemAt(i).widget() for i in range(flow.count())]


class TestCompactControls:
    @pytest.fixture()
    def styled(self, qapp):
        panel = NSQPanel(_connector())
        panel.setStyleSheet(_app_style_sheet())
        panel.show()
        yield panel
        panel.close()

    def _resize(self, qapp, panel, width: int, height: int = 800) -> None:
        panel.resize(width, height)
        _settle(qapp)

    def test_system_and_path_share_one_row(self, qapp, styled):
        self._resize(qapp, styled, 1000)

        scene = styled.scene_combo.geometry()
        path = styled.path_combo.geometry()
        assert scene.center().y() == path.center().y()
        assert scene.right() < path.left()

    def test_there_is_no_label_above_the_tabs(self, qapp, styled):
        from PySide6.QtWidgets import QLabel

        self._resize(qapp, styled, 1400)

        assert styled.findChild(QLabel, "NSQSceneLabel") is None
        assert not hasattr(styled, "scene_label")
        # Two rows of controls, then the Layout/Detectors/Summary tabs.
        spacing = styled.layout().spacing()
        controls_bottom = styled.controls_widget.geometry().bottom()
        assert styled.tabs.y() <= controls_bottom + spacing + 2

    def test_view_controls_share_the_trace_row_when_there_is_room(
        self, qapp, styled
    ):
        self._resize(qapp, styled, 1400)

        rays_row = styled.rays_spin.parentWidget().geometry()
        for widget in (
            styled.projection_combo.parentWidget(),
            styled.drawn_spin.parentWidget(),
            styled.reset_view_button,
        ):
            assert widget.geometry().center().y() == pytest.approx(
                rays_row.center().y(), abs=1
            )
        assert styled.controls_widget.height() < 2 * rays_row.height()
        assert (
            styled.trace_button.geometry().center().y()
            == pytest.approx(styled.controls_widget.geometry().center().y(), abs=2)
        )

    def test_controls_wrap_instead_of_widening_a_narrow_panel(self, qapp, styled):
        # The old panel could not get narrower than its trace row (1099 px).
        assert styled.minimumSizeHint().width() <= 700

        self._resize(qapp, styled, 700)

        box = styled.controls_widget.rect()
        assert styled.controls_widget.height() > 2 * styled.rays_spin.height()
        for widget in _groups(styled):
            assert box.contains(widget.geometry()), widget

    def test_spin_boxes_show_their_values(self, qapp, styled):
        from PySide6.QtWidgets import QLineEdit

        self._resize(qapp, styled, 1400)

        for spin, widest in (
            (styled.rays_spin, "20000000"),
            (styled.seed_spin, "999999"),
            (styled.depth_spin, "256"),
            (styled.split_spin, "8"),
            (styled.paths_spin, "50000"),
            (styled.drawn_spin, "5000"),
        ):
            edit = spin.findChild(QLineEdit)
            needed = edit.fontMetrics().horizontalAdvance(widest)
            assert edit.width() >= needed, spin.objectName()

    def test_the_layout_plot_gets_the_height_the_rows_gave_up(self, qapp, styled):
        self._resize(qapp, styled, 1400, 800)
        styled.layout_canvas.draw()

        # Two control rows, the tab bar and the plot toolbar: the canvas
        # has the rest of the panel.
        overhead = (
            styled.scene_combo.height()
            + styled.controls_widget.height()
            + styled.tabs.tabBar().height()
            + styled.layout_toolbar.height()
            + 60  # margins, spacing, tab frame
        )
        assert styled.layout_canvas.height() >= styled.height() - overhead
        box = styled.layout_figure.axes[0].get_position()
        assert box.width > 0.8 and box.height > 0.7

    def test_a_system_file_is_named_in_the_system_pull_down(
        self, qapp, styled, tmp_path
    ):
        from optiland.samples.nonsequential import SAMPLE_SCENES

        path = tmp_path / "bench.json"
        styled.service.save_file(str(path))
        styled.service.load_file(str(path))

        combo = styled.scene_combo
        assert combo.currentText() == "bench.json"
        assert combo.currentData() is None
        assert combo.count() == len(SAMPLE_SCENES) + 1

        styled.service.load_sample("side_illumination")

        assert combo.count() == len(SAMPLE_SCENES)
        assert combo.currentData() == "side_illumination"
