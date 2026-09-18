"""Tests for the non-sequential panel and its document service."""

from __future__ import annotations

import time
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
        assert panel.scene_label.text() == "Beam splitter: one beam, two arms"
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
