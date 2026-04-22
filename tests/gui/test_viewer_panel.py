from __future__ import annotations

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
    qapp, minimal_optic
) -> None:
    panel = ViewerPanel(_ConnectorStub(minimal_optic))

    assert panel.viewer2D.ax.get_aspect() == "auto"

    panel.preserve_xy_ratio_checkbox.setChecked(True)

    assert panel.viewer2D._preserve_xy_ratio is True
    assert panel.viewer2D.ax.get_aspect() == 1.0

    panel.preserve_xy_ratio_checkbox.setChecked(False)

    assert panel.viewer2D._preserve_xy_ratio is False
    assert panel.viewer2D.ax.get_aspect() == "auto"
