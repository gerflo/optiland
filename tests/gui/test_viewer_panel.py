from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace

import numpy as np
import pytest
import optiland.backend as be
from PySide6.QtCore import QObject, Signal

from optiland_gui.viewer_panel import ViewerPanel
from optiland.visualization.system.rays import Rays2D


class _ConnectorStub(QObject):
    opticLoaded = Signal()
    opticChanged = Signal()

    def __init__(self, optic) -> None:
        super().__init__()
        self._optic = optic
        self.toast_manager = None

    def get_optic(self):  # noqa: ANN201
        return self._optic

    def get_effective_optic(self):  # noqa: ANN201
        return self._optic

    def get_surface_count(self) -> int:
        return self._optic.surfaces.num_surfaces


def test_viewer_panel_preserve_xy_ratio_checkbox_updates_2d_aspect(
    qapp, minimal_optic, monkeypatch
) -> None:
    class _DefaultSettings:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def value(self, _key: str, default=None, *, type=None):  # noqa: A002, ANN001
            if type is bool:
                return bool(default)
            if type is int:
                return int(default)
            return default

        def setValue(self, _key: str, _value) -> None:  # noqa: ANN001
            return None

    monkeypatch.setattr("optiland_gui.viewer_panel.QSettings", _DefaultSettings)
    panel = ViewerPanel(_ConnectorStub(minimal_optic))

    assert panel.viewer2D.ax.get_aspect() == "auto"

    panel.viewer2D.preserve_xy_ratio_checkbox.setChecked(True)
    panel.viewer2D._plot_optic_sync()

    assert panel.viewer2D._preserve_xy_ratio is True
    assert panel.viewer2D.ax.get_aspect() == "auto"
    x0, x1 = panel.viewer2D.ax.get_xlim()
    y0, y1 = panel.viewer2D.ax.get_ylim()
    bbox = panel.viewer2D.ax.get_position()
    figure_width = panel.viewer2D.figure.get_figwidth()
    figure_height = panel.viewer2D.figure.get_figheight()
    box_ratio = (bbox.width * figure_width) / (bbox.height * figure_height)
    data_ratio = abs((x1 - x0) / (y1 - y0))
    assert data_ratio == pytest.approx(box_ratio, rel=1e-3)

    panel.viewer2D.preserve_xy_ratio_checkbox.setChecked(False)

    assert panel.viewer2D._preserve_xy_ratio is False
    assert panel.viewer2D.ax.get_aspect() == "auto"


def test_viewer_panel_restores_persistent_2d_settings(
    qapp, minimal_optic, monkeypatch
) -> None:
    settings_store: dict[str, object] = {
        "Viewer2D/PreserveZoom": True,
        "Viewer2D/PreserveXYRatio": True,
        "Viewer2D/NumRays": 9,
    }

    class _FakeSettings:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def value(
            self,
            key: str,
            default=None,  # noqa: ANN001
            *,
            type: Callable | None = None,  # noqa: A002
        ):
            value = settings_store.get(key, default)
            if type is bool:
                return bool(value)
            if type is int:
                return int(value)
            return value

        def setValue(self, key: str, value) -> None:  # noqa: ANN001
            settings_store[key] = value

    monkeypatch.setattr("optiland_gui.viewer_panel.QSettings", _FakeSettings)

    panel = ViewerPanel(_ConnectorStub(minimal_optic))

    assert panel.viewer2D.preserve_zoom_checkbox.isChecked() is True
    assert panel.viewer2D.preserve_xy_ratio_checkbox.isChecked() is True
    assert panel.viewer2D._preserve_xy_ratio is True
    assert panel.viewer2D.num_rays_spinbox.value() == 9

    panel.viewer2D.preserve_zoom_checkbox.setChecked(False)
    panel.viewer2D.preserve_xy_ratio_checkbox.setChecked(False)
    panel.viewer2D.num_rays_spinbox.setValue(7)

    assert settings_store["Viewer2D/PreserveZoom"] is False
    assert settings_store["Viewer2D/PreserveXYRatio"] is False
    assert settings_store["Viewer2D/NumRays"] == 7


def test_rays2d_annular_line_y_uses_one_uniform_real_trace() -> None:
    from optiland.optic import Optic
    from optiland.physical_apertures import RadialAperture

    optic = Optic()
    optic.surfaces.add(index=0, radius=be.inf, thickness=be.inf)
    optic.surfaces.add(
        index=1,
        radius=be.inf,
        thickness=20.0,
        is_stop=True,
        aperture=RadialAperture(r_max=3.6, r_min=2.44),
    )
    optic.surfaces.add(index=2, radius=be.inf, thickness=0.0)
    optic.set_aperture(aperture_type="EPD", value=20.0)
    optic.fields.set_type("angle")
    optic.fields.add(y=0.0)
    optic.wavelengths.add(value=0.55, is_primary=True)
    optic.updater.update()

    rays = Rays2D(optic)
    num_rays = 31
    rays._trace((0.0, 0.0), 0.55, num_rays, "line_y")

    stop_y = be.to_numpy(rays.y[1])
    image_i = be.to_numpy(rays.i[2])
    expected_stop_y = np.linspace(-10.0, 10.0, num_rays)

    transmitted = (np.abs(stop_y) >= 2.44) & (np.abs(stop_y) <= 3.6)

    assert stop_y.size == num_rays
    assert np.allclose(stop_y, expected_stop_y)
    assert np.any(transmitted)
    assert np.all(image_i[transmitted] > 0)
    assert np.all(image_i[~transmitted] == 0)


def test_viewer_pan_does_not_start_while_toolbar_zoom_mode_is_active(
    qapp, minimal_optic, monkeypatch
) -> None:
    class _DefaultSettings:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def value(self, _key: str, default=None, *, type=None):  # noqa: A002, ANN001
            if type is bool:
                return bool(default)
            if type is int:
                return int(default)
            return default

        def setValue(self, _key: str, _value) -> None:  # noqa: ANN001
            return None

    monkeypatch.setattr("optiland_gui.viewer_panel.QSettings", _DefaultSettings)
    panel = ViewerPanel(_ConnectorStub(minimal_optic))
    panel.viewer2D.toolbar.mode = "zoom rect"

    event = SimpleNamespace(button=1, inaxes=panel.viewer2D.ax, xdata=10.0, ydata=2.0)
    panel.viewer2D.on_mouse_button_press(event)

    assert panel.viewer2D._is_panning is False
    assert panel.viewer2D._active_pan_button is None


def test_viewer_toolbar_zoom_keeps_preserve_xy_ratio(
    qapp, minimal_optic, monkeypatch
) -> None:
    class _DefaultSettings:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def value(self, _key: str, default=None, *, type=None):  # noqa: A002, ANN001
            if type is bool:
                return bool(default)
            if type is int:
                return int(default)
            return default

        def setValue(self, _key: str, _value) -> None:  # noqa: ANN001
            return None

    monkeypatch.setattr("optiland_gui.viewer_panel.QSettings", _DefaultSettings)
    panel = ViewerPanel(_ConnectorStub(minimal_optic))
    panel.viewer2D.preserve_xy_ratio_checkbox.setChecked(True)

    panel.viewer2D.ax.set_xlim(10.0, 70.0)
    panel.viewer2D.ax.set_ylim(-2.0, 8.0)
    panel.viewer2D._handle_toolbar_view_limits_changed()

    x0, x1 = panel.viewer2D.ax.get_xlim()
    y0, y1 = panel.viewer2D.ax.get_ylim()
    bbox = panel.viewer2D.ax.get_position()
    figure_width = panel.viewer2D.figure.get_figwidth()
    figure_height = panel.viewer2D.figure.get_figheight()
    box_ratio = (bbox.width * figure_width) / (bbox.height * figure_height)
    data_ratio = abs((x1 - x0) / (y1 - y0))

    assert data_ratio == pytest.approx(box_ratio, rel=1e-3)


def test_viewer_free_drag_uses_matplotlib_pan_helpers(
    qapp, minimal_optic, monkeypatch
) -> None:
    class _DefaultSettings:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def value(self, _key: str, default=None, *, type=None):  # noqa: A002, ANN001
            if type is bool:
                return bool(default)
            if type is int:
                return int(default)
            return default

        def setValue(self, _key: str, _value) -> None:  # noqa: ANN001
            return None

    monkeypatch.setattr("optiland_gui.viewer_panel.QSettings", _DefaultSettings)
    panel = ViewerPanel(_ConnectorStub(minimal_optic))
    calls: list[tuple[str, tuple[object, ...]]] = []

    monkeypatch.setattr(
        panel.viewer2D.ax,
        "start_pan",
        lambda x, y, button: calls.append(("start", (x, y, button))),
    )
    monkeypatch.setattr(
        panel.viewer2D.ax,
        "drag_pan",
        lambda button, key, x, y: calls.append(("drag", (button, key, x, y))),
    )
    monkeypatch.setattr(
        panel.viewer2D.ax,
        "end_pan",
        lambda: calls.append(("end", ())),
    )

    panel.viewer2D.on_mouse_button_press(
        SimpleNamespace(
            button=1,
            inaxes=panel.viewer2D.ax,
            x=120,
            y=80,
            xdata=10.0,
            ydata=2.0,
        )
    )
    panel.viewer2D.on_mouse_move_on_plot(
        SimpleNamespace(
            inaxes=panel.viewer2D.ax,
            x=140,
            y=90,
            xdata=12.0,
            ydata=3.0,
            key=None,
        )
    )
    panel.viewer2D.on_mouse_button_release(
        SimpleNamespace(button=1, inaxes=panel.viewer2D.ax)
    )

    assert calls == [
        ("start", (120, 80, 1)),
        ("drag", (1, None, 140, 90)),
        ("end", ()),
    ]


def test_viewer_toolbar_pan_zoom_keeps_ratio_while_dragging(
    qapp, minimal_optic, monkeypatch
) -> None:
    class _DefaultSettings:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def value(self, _key: str, default=None, *, type=None):  # noqa: A002, ANN001
            if type is bool:
                return bool(default)
            if type is int:
                return int(default)
            return default

        def setValue(self, _key: str, _value) -> None:  # noqa: ANN001
            return None

    monkeypatch.setattr("optiland_gui.viewer_panel.QSettings", _DefaultSettings)
    panel = ViewerPanel(_ConnectorStub(minimal_optic))
    panel.viewer2D.preserve_xy_ratio_checkbox.setChecked(True)
    panel.viewer2D.toolbar.mode = "pan/zoom"
    panel.viewer2D._enforce_equal_xy_on_toolbar_release = True

    panel.viewer2D.ax.set_xlim(5.0, 45.0)
    panel.viewer2D.ax.set_ylim(-1.0, 7.0)
    panel.viewer2D.on_ax_limit_changed(panel.viewer2D.ax)

    x0, x1 = panel.viewer2D.ax.get_xlim()
    y0, y1 = panel.viewer2D.ax.get_ylim()
    bbox = panel.viewer2D.ax.get_position()
    figure_width = panel.viewer2D.figure.get_figwidth()
    figure_height = panel.viewer2D.figure.get_figheight()
    box_ratio = (bbox.width * figure_width) / (bbox.height * figure_height)
    data_ratio = abs((x1 - x0) / (y1 - y0))

    assert data_ratio == pytest.approx(box_ratio, rel=1e-3)


def test_viewer_without_stop_surface_keeps_layout_and_warns(
    qapp, minimal_optic, monkeypatch
) -> None:
    class _DefaultSettings:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def value(self, _key: str, default=None, *, type=None):  # noqa: A002, ANN001
            if type is bool:
                return bool(default)
            if type is int:
                return int(default)
            return default

        def setValue(self, _key: str, _value) -> None:  # noqa: ANN001
            return None

    class _ToastRecorder:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str]] = []

        def notify(self, message: str, level: str) -> None:
            self.calls.append((message, level))

    monkeypatch.setattr("optiland_gui.viewer_panel.QSettings", _DefaultSettings)
    for surface in minimal_optic.surfaces:
        surface.is_stop = False
    connector = _ConnectorStub(minimal_optic)
    connector.toast_manager = _ToastRecorder()

    panel = ViewerPanel(connector)
    panel.viewer2D._plot_optic_sync()

    assert panel.viewer2D.ax.get_title() == f"System: {minimal_optic.name} (2D)"
    assert "Error plotting system" not in {
        text.get_text() for text in panel.viewer2D.ax.texts
    }
    assert connector.toast_manager.calls
    assert "No stop surface is defined" in connector.toast_manager.calls[0][0]
    assert connector.toast_manager.calls[0][1] == "warning"


def test_sag_viewer_rethemes_existing_figure_after_plot(
    qapp, minimal_optic, monkeypatch
) -> None:
    class _DefaultSettings:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def value(self, _key: str, default=None, *, type=None):  # noqa: A002, ANN001
            if type is bool:
                return bool(default)
            if type is int:
                return int(default)
            return default

        def setValue(self, _key: str, _value) -> None:  # noqa: ANN001
            return None

    monkeypatch.setattr("optiland_gui.viewer_panel.QSettings", _DefaultSettings)
    calls: list[object] = []
    monkeypatch.setattr(
        "optiland_gui.viewer_panel.gui_plot_utils.apply_theme_to_existing_figure",
        lambda figure: calls.append(figure),
    )

    panel = ViewerPanel(_ConnectorStub(minimal_optic))
    panel.sagViewer.plot_sag()

    assert calls


def test_viewer_panel_resets_original_views_when_optic_is_loaded(
    qapp, minimal_optic, monkeypatch
) -> None:
    class _DefaultSettings:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def value(self, _key: str, default=None, *, type=None):  # noqa: A002, ANN001
            if type is bool:
                return bool(default)
            if type is int:
                return int(default)
            return default

        def setValue(self, _key: str, _value) -> None:  # noqa: ANN001
            return None

    monkeypatch.setattr("optiland_gui.viewer_panel.QSettings", _DefaultSettings)
    panel = ViewerPanel(_ConnectorStub(minimal_optic))
    calls: list[str] = []

    monkeypatch.setattr(
        panel.viewer2D,
        "reset_view",
        lambda: calls.append("2d-reset"),
    )
    if panel._viewer3d_tab_index >= 0:
        monkeypatch.setattr(
            "optiland_gui.viewer_panel.VTKViewer.render_optic",
            lambda self, *args, **kwargs: calls.append(("3d-render", args, kwargs)),
        )
    monkeypatch.setattr(
        panel.sagViewer,
        "update_surface_range",
        lambda: calls.append("sag-range"),
    )
    monkeypatch.setattr(
        panel.sagViewer,
        "plot_sag",
        lambda: calls.append("sag-plot"),
    )

    panel.connector.opticLoaded.emit()

    assert "2d-reset" in calls
    assert "sag-range" in calls
    assert "sag-plot" in calls
    if panel._viewer3d_tab_index >= 0:
        assert not any(
            call[0] == "3d-render" for call in calls if isinstance(call, tuple)
        )
        assert panel._pending_3d_render is True
        panel.tabWidget.setCurrentIndex(panel._viewer3d_tab_index)
        panel._activate_3d_view()
        assert any(call[0] == "3d-render" for call in calls if isinstance(call, tuple))


def test_viewer_panel_optic_changed_updates_without_forcing_view_reset(
    qapp, minimal_optic, monkeypatch
) -> None:
    class _DefaultSettings:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def value(self, _key: str, default=None, *, type=None):  # noqa: A002, ANN001
            if type is bool:
                return bool(default)
            if type is int:
                return int(default)
            return default

        def setValue(self, _key: str, _value) -> None:  # noqa: ANN001
            return None

    monkeypatch.setattr("optiland_gui.viewer_panel.QSettings", _DefaultSettings)
    panel = ViewerPanel(_ConnectorStub(minimal_optic))
    calls: list[object] = []

    monkeypatch.setattr(
        panel.viewer2D,
        "reset_view",
        lambda: calls.append("2d-reset"),
    )
    monkeypatch.setattr(
        panel.viewer2D,
        "plot_optic",
        lambda preserve_zoom=False: calls.append(("2d-update", preserve_zoom)),
    )
    if panel._viewer3d_tab_index >= 0:
        monkeypatch.setattr(
            "optiland_gui.viewer_panel.VTKViewer.render_optic",
            lambda self, *args, **kwargs: calls.append(("3d-render", args, kwargs)),
        )
    monkeypatch.setattr(
        panel.sagViewer,
        "plot_sag",
        lambda: calls.append("sag-plot"),
    )

    panel.connector.opticChanged.emit()

    assert "2d-reset" not in calls
    assert "sag-plot" not in calls
    assert ("2d-update", panel.viewer2D.preserve_zoom_checkbox.isChecked()) in calls
    if panel._viewer3d_tab_index >= 0:
        assert not any(
            call[0] == "3d-render" for call in calls if isinstance(call, tuple)
        )
        assert panel._pending_3d_render is True
        panel.tabWidget.setCurrentIndex(panel._viewer3d_tab_index)
        panel._activate_3d_view()
        assert any(call[0] == "3d-render" for call in calls if isinstance(call, tuple))


def test_viewer_panel_passes_2d_ray_count_and_full_pupil_distribution_to_3d_renderer(
    qapp, minimal_optic, monkeypatch
) -> None:
    class _DefaultSettings:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def value(self, _key: str, default=None, *, type=None):  # noqa: A002, ANN001
            if type is bool:
                return bool(default)
            if type is int:
                return int(default)
            return default

        def setValue(self, _key: str, _value) -> None:  # noqa: ANN001
            return None

    monkeypatch.setattr("optiland_gui.viewer_panel.QSettings", _DefaultSettings)
    panel = ViewerPanel(_ConnectorStub(minimal_optic))
    if panel._viewer3d_tab_index < 0:
        pytest.skip("VTK is not available")
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        "optiland_gui.viewer_panel.VTKViewer.render_optic",
        lambda self, **kwargs: calls.append(kwargs),
    )
    panel.tabWidget.setCurrentIndex(panel._viewer3d_tab_index)
    panel._activate_3d_view()
    calls.clear()

    panel.viewer2D.num_rays_spinbox.setValue(17)
    panel.viewer2D.dist_combo.setCurrentText("line_x")
    panel._render_3d_from_2d_settings()

    assert calls[-1] == {
        "num_rays": 2,
        "distribution": "hexapolar",
        "show_stop_apertures": True,
        "show_non_stop_apertures": True,
        "hide_vignetted": False,
    }


def test_viewer_panel_apply_2d_settings_refreshes_coupled_3d_renderer(
    qapp, minimal_optic, monkeypatch
) -> None:
    class _DefaultSettings:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def value(self, _key: str, default=None, *, type=None):  # noqa: A002, ANN001
            if type is bool:
                return bool(default)
            if type is int:
                return int(default)
            return default

        def setValue(self, _key: str, _value) -> None:  # noqa: ANN001
            return None

    monkeypatch.setattr("optiland_gui.viewer_panel.QSettings", _DefaultSettings)
    panel = ViewerPanel(_ConnectorStub(minimal_optic))
    if panel._viewer3d_tab_index < 0:
        pytest.skip("VTK is not available")
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        "optiland_gui.viewer_panel.VTKViewer.render_optic",
        lambda self, **kwargs: calls.append(kwargs),
    )
    monkeypatch.setattr(panel.viewer2D, "plot_optic", lambda *args, **kwargs: None)
    panel.tabWidget.setCurrentIndex(panel._viewer3d_tab_index)
    panel._activate_3d_view()
    calls.clear()

    panel.viewer2D.num_rays_spinbox.setValue(23)
    panel.viewer2D.dist_combo.setCurrentText("random")
    panel.viewer2D.apply_settings()

    assert calls[-1] == {
        "num_rays": 23,
        "distribution": "random",
        "show_stop_apertures": True,
        "show_non_stop_apertures": True,
        "hide_vignetted": False,
    }


def test_viewer_panel_maps_2d_line_sections_to_full_pupil_3d_distribution(
    qapp, minimal_optic, monkeypatch
) -> None:
    class _DefaultSettings:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def value(self, _key: str, default=None, *, type=None):  # noqa: A002, ANN001
            if type is bool:
                return bool(default)
            if type is int:
                return int(default)
            return default

        def setValue(self, _key: str, _value) -> None:  # noqa: ANN001
            return None

    monkeypatch.setattr("optiland_gui.viewer_panel.QSettings", _DefaultSettings)
    panel = ViewerPanel(_ConnectorStub(minimal_optic))

    panel.viewer2D.dist_combo.setCurrentText("line_y")
    assert panel.viewer2D.ray_distribution() == "line_y"
    assert panel.viewer2D.ray_distribution_for_3d() == "hexapolar"
    panel.viewer2D.num_rays_spinbox.setValue(30)
    assert panel.viewer2D.ray_sampling_for_3d() == (3, "hexapolar")

    panel.viewer2D.dist_combo.setCurrentText("line_x")
    assert panel.viewer2D.ray_distribution_for_3d() == "hexapolar"
    panel.viewer2D.num_rays_spinbox.setValue(100)
    assert panel.viewer2D.ray_sampling_for_3d() == (5, "hexapolar")

    panel.viewer2D.dist_combo.setCurrentText("random")
    assert panel.viewer2D.ray_distribution_for_3d() == "random"
    assert panel.viewer2D.ray_sampling_for_3d() == (100, "random")


# ---------------------------------------------------------------------------
# Axes limit callbacks survive ax.clear()
# ---------------------------------------------------------------------------


class _StubSettings:
    # QSettings stand-in that always answers with the default value.
    def __init__(self, *_args, **_kwargs) -> None:
        pass

    def value(self, _key: str, default=None, *, type=None):  # noqa: A002, ANN001
        if type is bool:
            return bool(default)
        if type is int:
            return int(default)
        return default

    def setValue(self, _key: str, _value) -> None:  # noqa: ANN001
        return None


def _make_2d_viewer(monkeypatch, optic):  # noqa: ANN001, ANN202
    monkeypatch.setattr("optiland_gui.viewer_panel.QSettings", _StubSettings)
    viewer = ViewerPanel(_ConnectorStub(optic)).viewer2D
    viewer._plot_optic_sync()  # ax.clear() inside used to drop the callbacks
    return viewer


def _box_ratio(viewer) -> float:  # noqa: ANN001
    bbox = viewer.ax.get_position()
    return (bbox.width * viewer.figure.get_figwidth()) / (
        bbox.height * viewer.figure.get_figheight()
    )


def _data_ratio(viewer) -> float:  # noqa: ANN001
    x0, x1 = viewer.ax.get_xlim()
    y0, y1 = viewer.ax.get_ylim()
    return abs((x1 - x0) / (y1 - y0))


def test_viewer_user_zoom_after_a_redraw_is_kept_until_reset(
    qapp, minimal_optic, monkeypatch
) -> None:
    viewer = _make_2d_viewer(monkeypatch, minimal_optic)
    assert viewer._user_initiated_view_change is False

    viewer.ax.set_xlim(10.0, 30.0)
    assert viewer._user_initiated_view_change is True

    viewer._plot_optic_sync(preserve_zoom=False)
    assert viewer.ax.get_xlim() == (10.0, 30.0)

    viewer.reset_view()
    assert viewer._user_initiated_view_change is False
    viewer._plot_optic_sync(preserve_zoom=False)
    assert viewer.ax.get_xlim() != (10.0, 30.0)


def test_viewer_redraw_itself_is_not_a_user_view_change(
    qapp, minimal_optic, monkeypatch
) -> None:
    viewer = _make_2d_viewer(monkeypatch, minimal_optic)

    viewer._plot_optic_sync()
    viewer._plot_optic_sync()

    assert viewer._user_initiated_view_change is False


def test_viewer_scroll_zoom_and_drag_pan_count_as_user_view_changes(
    qapp, minimal_optic, monkeypatch
) -> None:
    viewer = _make_2d_viewer(monkeypatch, minimal_optic)

    viewer.on_scroll_zoom(
        SimpleNamespace(inaxes=viewer.ax, step=-1, xdata=10.0, ydata=0.0)
    )
    assert viewer._user_initiated_view_change is True

    viewer.reset_view()
    viewer._plot_optic_sync(preserve_zoom=False)
    assert viewer._user_initiated_view_change is False
    viewer.on_mouse_button_press(
        SimpleNamespace(button=1, inaxes=viewer.ax, x=120, y=80, xdata=10.0, ydata=2.0)
    )
    viewer.on_mouse_move_on_plot(
        SimpleNamespace(inaxes=viewer.ax, x=160, y=90, xdata=14.0, ydata=3.0, key=None)
    )
    viewer.on_mouse_button_release(SimpleNamespace(button=1, inaxes=viewer.ax))
    assert viewer._user_initiated_view_change is True


def test_viewer_toolbar_right_drag_keeps_ratio_live_after_a_redraw(
    qapp, minimal_optic, monkeypatch
) -> None:
    viewer = _make_2d_viewer(monkeypatch, minimal_optic)
    viewer.preserve_xy_ratio_checkbox.setChecked(True)
    viewer._plot_optic_sync()
    viewer.toolbar.mode = "pan/zoom"
    viewer._enforce_equal_xy_on_toolbar_release = True

    # What drag_pan does on every mouse move during a right-button zoom: the
    # callback alone must restore the ratio, without a manual call.
    viewer.ax.set_xlim(5.0, 45.0)
    viewer.ax.set_ylim(-1.0, 7.0)

    assert _data_ratio(viewer) == pytest.approx(_box_ratio(viewer), rel=1e-3)


def test_viewer_resize_with_equal_ratio_is_not_a_user_view_change(
    qapp, minimal_optic, monkeypatch
) -> None:
    viewer = _make_2d_viewer(monkeypatch, minimal_optic)
    viewer.preserve_xy_ratio_checkbox.setChecked(True)
    viewer._plot_optic_sync()
    assert viewer._user_initiated_view_change is False

    viewer._on_canvas_resize(None)

    assert viewer._user_initiated_view_change is False
    assert _data_ratio(viewer) == pytest.approx(_box_ratio(viewer), rel=1e-3)


# ---------------------------------------------------------------------------
# Z-spacing dimension annotations below the 2D layout
# ---------------------------------------------------------------------------

_DIMENSION_COLOR = "#8A9BAD"


def _dimension_artists(viewer):  # noqa: ANN001, ANN202
    # minimal_optic: lens 0-5 mm, then 45 mm to the image plane.
    lines = [line for line in viewer.ax.lines if line.get_color() == _DIMENSION_COLOR]
    labels = [text for text in viewer.ax.texts if text.get_text() in {"5.00", "45.00"}]
    return lines, labels


def _make_2d_viewer_with_dimensions(monkeypatch, optic):  # noqa: ANN001, ANN202
    viewer = _make_2d_viewer(monkeypatch, optic)
    viewer.preserve_xy_ratio_checkbox.setChecked(False)
    viewer.display_y_measures_checkbox.setChecked(True)
    viewer._plot_optic_sync()
    return viewer


def _assert_inside_axes(viewer, artists) -> None:  # noqa: ANN001
    renderer = viewer.canvas.get_renderer()
    axes_box = viewer.ax.bbox
    for artist in artists:
        assert artist.get_clip_on()
        extent = artist.get_window_extent(renderer)
        assert axes_box.y0 <= extent.y0
        assert extent.y1 <= axes_box.y1


def test_viewer_dimensions_sit_just_below_the_optic_inside_the_axes(
    qapp, minimal_optic, monkeypatch
) -> None:
    viewer = _make_2d_viewer_with_dimensions(monkeypatch, minimal_optic)
    viewer.canvas.draw()
    lines, labels = _dimension_artists(viewer)
    assert len(lines) == 2
    assert len(labels) == 2

    renderer = viewer.canvas.get_renderer()
    optic_bottom_px = min(
        artist.get_window_extent(renderer).y0 for artist in viewer._layout_artists
    )
    for line in lines:
        gap_px = optic_bottom_px - line.get_window_extent(renderer).y1
        assert 0.0 < gap_px <= 20.0
    _assert_inside_axes(viewer, (*lines, *labels))


def test_viewer_dimensions_stay_inside_the_axes_when_the_optic_leaves_the_view(
    qapp, minimal_optic, monkeypatch
) -> None:
    viewer = _make_2d_viewer_with_dimensions(monkeypatch, minimal_optic)
    lines, labels = _dimension_artists(viewer)

    # Zoomed in on the image plane with the optic below, then above the view.
    for ylim in ((20.0, 40.0), (-40.0, -20.0)):
        viewer.ax.set_xlim(40.0, 55.0)
        viewer.ax.set_ylim(*ylim)
        viewer.canvas.draw()

        _assert_inside_axes(viewer, (*lines, *labels))


def test_viewer_bottom_margin_keeps_its_height_when_the_viewer_grows(
    qapp, minimal_optic, monkeypatch
) -> None:
    viewer = _make_2d_viewer_with_dimensions(monkeypatch, minimal_optic)
    axes_bottom_px = viewer.ax.bbox.y0

    viewer.figure.set_size_inches(5.0, 8.0, forward=False)
    viewer._on_canvas_resize(None)
    viewer.canvas.draw()

    # The extra height goes to the axes, not to the strip below them ...
    assert viewer.ax.bbox.y0 == pytest.approx(axes_bottom_px, abs=1.0)
    # ... which only holds the x-axis tick labels and label.
    renderer = viewer.canvas.get_renderer()
    assert 0.0 <= viewer.ax.xaxis.label.get_window_extent(renderer).y0 <= 15.0


# ---------------------------------------------------------------------------
# The 3D layout follows the 2D "Rays Reach Image" setting
# ---------------------------------------------------------------------------


def test_viewer_panel_rays_reach_image_hides_vignetted_rays_in_3d_too(
    qapp, minimal_optic, monkeypatch
) -> None:
    # Regression: the 3D layout ignored "Rays Reach Image", so rays blocked by an
    # aperture were drawn up to the blocking surface in 3D while hidden in 2D.
    monkeypatch.setattr("optiland_gui.viewer_panel.QSettings", _StubSettings)
    panel = ViewerPanel(_ConnectorStub(minimal_optic))
    if panel._viewer3d_tab_index < 0:
        pytest.skip("VTK is not available")
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        "optiland_gui.viewer_panel.VTKViewer.render_optic",
        lambda self, **kwargs: calls.append(kwargs),
    )
    monkeypatch.setattr(panel.viewer2D, "plot_optic", lambda *args, **kwargs: None)
    panel.tabWidget.setCurrentIndex(panel._viewer3d_tab_index)
    panel._activate_3d_view()

    assert calls[-1]["hide_vignetted"] is False

    # Toggling the checkbox alone must refresh the coupled 3D view.
    calls.clear()
    panel.viewer2D.rays_reach_image_checkbox.setChecked(True)
    assert calls
    assert calls[-1]["hide_vignetted"] is True

    calls.clear()
    panel.viewer2D.rays_reach_image_checkbox.setChecked(False)
    assert calls
    assert calls[-1]["hide_vignetted"] is False


def test_vtk_viewer_forwards_hide_vignetted_to_rays3d(
    qapp, minimal_optic, monkeypatch
) -> None:
    monkeypatch.setattr("optiland_gui.viewer_panel.QSettings", _StubSettings)
    panel = ViewerPanel(_ConnectorStub(minimal_optic))
    if panel._viewer3d_tab_index < 0 or not panel._ensure_3d_viewer():
        pytest.skip("VTK is not available")
    viewer = panel.viewer3D
    captured: list[dict[str, object]] = []
    monkeypatch.setattr(
        "optiland_gui.viewer_panel.Rays3D.plot",
        lambda self, *args, **kwargs: captured.append(kwargs),
    )
    monkeypatch.setattr(
        "optiland_gui.viewer_panel.OptilandOpticalSystemPlotter.plot",
        lambda self, *args, **kwargs: None,
    )
    # Render synchronously: no deferred timer, no OpenGL draw.
    monkeypatch.setattr(
        "optiland_gui.viewer_panel.QTimer",
        SimpleNamespace(singleShot=lambda *args, **kwargs: None),
    )
    monkeypatch.setattr(
        viewer.vtkWidget,
        "GetRenderWindow",
        lambda: SimpleNamespace(Render=lambda: None),
    )

    viewer.render_optic(num_rays=2, distribution="hexapolar", hide_vignetted=True)
    viewer._render_optic_sync()
    assert captured[-1]["hide_vignetted"] is True
    assert captured[-1]["num_rays"] == 2
    assert captured[-1]["distribution"] == "hexapolar"

    # Omitting the flag keeps the last value; passing it overrides.
    viewer.render_optic()
    viewer._render_optic_sync()
    assert captured[-1]["hide_vignetted"] is True

    viewer.render_optic(hide_vignetted=False)
    viewer._render_optic_sync()
    assert captured[-1]["hide_vignetted"] is False
    assert captured[-1]["num_rays"] == 2
