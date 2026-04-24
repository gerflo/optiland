from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace

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

    def get_surface_count(self) -> int:
        return self._optic.surface_group.num_surfaces


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

    panel.preserve_xy_ratio_checkbox.setChecked(True)

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

    panel.preserve_xy_ratio_checkbox.setChecked(False)

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

    assert panel.preserve_zoom_checkbox.isChecked() is True
    assert panel.preserve_xy_ratio_checkbox.isChecked() is True
    assert panel.viewer2D._preserve_xy_ratio is True
    assert panel.viewer2D.num_rays_spinbox.value() == 9

    panel.preserve_zoom_checkbox.setChecked(False)
    panel.preserve_xy_ratio_checkbox.setChecked(False)
    panel.viewer2D.num_rays_spinbox.setValue(7)

    assert settings_store["Viewer2D/PreserveZoom"] is False
    assert settings_store["Viewer2D/PreserveXYRatio"] is False
    assert settings_store["Viewer2D/NumRays"] == 7


def test_rays2d_annular_line_y_skips_blocked_center(minimal_optic) -> None:
    from optiland.physical_apertures import RadialAperture

    minimal_optic.surfaces.surfaces[1].aperture = RadialAperture(r_max=3.8, r_min=2.4)
    minimal_optic.updater.update()
    rays = Rays2D(minimal_optic)

    rays._trace((0.0, 0.0), 0.55, 8, "line_y")

    start_y = rays.y[0]
    finite_start_y = start_y[~be.isnan(start_y)]
    assert finite_start_y.size == 8
    assert all(abs(float(value)) >= (2.4 / 3.8) - 1e-9 for value in finite_start_y)


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
    panel.preserve_xy_ratio_checkbox.setChecked(True)

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
    panel.preserve_xy_ratio_checkbox.setChecked(True)
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
