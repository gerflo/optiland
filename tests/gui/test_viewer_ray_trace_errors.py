"""The 2D layout must stay visible and explain itself when the ray trace fails.

Object-height fields with the object at infinity are the typical trigger:
``optic.trace`` raises ``ValueError("Object surface is at infinity.")`` and the
viewer used to swallow it into a bare "Error plotting system" placeholder.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QObject, Signal

from optiland_gui.viewer_panel import ViewerPanel


class _ToastRecorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def notify(self, message: str, level: str, **_kwargs) -> None:
        self.calls.append((message, level))


class _ConnectorStub(QObject):
    opticLoaded = Signal()
    opticChanged = Signal()

    def __init__(self, optic) -> None:  # noqa: ANN001
        super().__init__()
        self._optic = optic
        self.toast_manager = _ToastRecorder()

    def get_optic(self):  # noqa: ANN201
        return self._optic

    def get_effective_optic(self):  # noqa: ANN201
        return self._optic

    def get_surface_count(self) -> int:
        return self._optic.surfaces.num_surfaces


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


@pytest.fixture
def viewer(qapp, minimal_optic, monkeypatch):
    """The 2D viewer of a ViewerPanel plus its connector stub."""
    monkeypatch.setattr("optiland_gui.viewer_panel.QSettings", _DefaultSettings)
    connector = _ConnectorStub(minimal_optic)
    panel = ViewerPanel(connector)
    return panel.viewer2D, connector


def _ray_toasts(connector) -> list[tuple[str, str]]:  # noqa: ANN001
    return [
        call
        for call in connector.toast_manager.calls
        if "object surface is at infinity" in call[0]
    ]


def _axes_texts(viewer2d) -> list[str]:  # noqa: ANN001
    return [text.get_text() for text in viewer2d.ax.texts]


def test_object_height_with_infinite_object_keeps_layout_and_explains(
    viewer, minimal_optic
) -> None:
    viewer2d, connector = viewer
    minimal_optic.fields.set_type("object_height")

    viewer2d._plot_optic_sync()

    assert viewer2d.ax.get_title() == f"System: {minimal_optic.name} (2D)"
    texts = _axes_texts(viewer2d)
    assert not any(text.startswith("Error plotting system") for text in texts)
    assert any(
        text.startswith("Rays hidden: Object surface is at infinity")
        for text in texts
    )

    toasts = _ray_toasts(connector)
    assert len(toasts) == 1
    message, level = toasts[0]
    assert level == "warning"
    assert "finite object distance" in message


def test_ray_trace_failure_is_reported_once_until_it_changes(
    viewer, minimal_optic
) -> None:
    viewer2d, connector = viewer
    minimal_optic.fields.set_type("object_height")

    viewer2d._plot_optic_sync()
    viewer2d._plot_optic_sync()
    assert len(_ray_toasts(connector)) == 1

    # Fixing the system clears the notice and removes the in-plot hint ...
    minimal_optic.fields.set_type("angle")
    viewer2d._plot_optic_sync()
    assert not any(text.startswith("Rays hidden") for text in _axes_texts(viewer2d))

    # ... so the same problem is announced again if it comes back.
    minimal_optic.fields.set_type("object_height")
    viewer2d._plot_optic_sync()
    assert len(_ray_toasts(connector)) == 2
