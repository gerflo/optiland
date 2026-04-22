from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QObject, Signal

from optiland_gui.viewer_panel import ViewerPanel


class _ConnectorStub(QObject):
    opticLoaded = Signal()
    opticChanged = Signal()

    def __init__(self, optic) -> None:
        super().__init__()
        self._optic = optic

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
    assert panel.viewer2D._pan_start_x is None
    assert panel.viewer2D._pan_start_y is None
