"""Regression tests for console noise during normal GUI use.

Three sources, all observed in a real session while editing a heavily
vignetted design:

1. ``invalid value encountered in sqrt`` from the lens overlap check,
   which samples a zero-extent surface over its neighbour's full extent
   and therefore past its geometric validity domain (NaN there is
   expected and already dropped via a finite mask).
2. ``QAbstractItemView::commitData called with an editor that does not
   belong to this view`` / ``edit: editing failed`` when the lens table is
   rebuilt while a cell editor is open.
3. ``Lens surfaces overlap`` printed on every single repaint instead of
   being reported once in the GUI.
"""

from __future__ import annotations

import warnings
from unittest.mock import MagicMock

import pytest

import optiland.backend as be
from optiland.optic import Optic
from optiland.visualization.system.lens import Lens2D
from optiland.visualization.system.surface import Surface2D


def _steep_optic() -> Optic:
    """A schematic-eye-like element with a 1.155 mm radius front surface."""
    optic = Optic()
    optic.surfaces.add(index=0, radius=be.inf, thickness=be.inf)
    optic.surfaces.add(index=1, radius=1.155, thickness=2.032, material="N-BK7")
    optic.surfaces.add(index=2, radius=-1.248, thickness=5.0)
    optic.set_aperture(aperture_type="EPD", value=2.0)
    optic.fields.set_type("angle")
    optic.fields.add(y=0.0)
    optic.wavelengths.add(value=0.55, is_primary=True)
    optic.updater.update()
    return optic


class TestOverlapCheckWarnings:
    def test_zero_extent_surface_emits_no_sqrt_warning(self, qapp) -> None:
        """Regression: a surface with no ray extent is sampled over its
        neighbour's extent, reaching past its sag domain."""
        optic = _steep_optic()
        # extent 0 (fully vignetted) next to a wide neighbour
        surfaces = [
            Surface2D(optic.surfaces.surfaces[1], 0.0),
            Surface2D(optic.surfaces.surfaces[2], 12.0),
        ]

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            Lens2D(surfaces)

        sqrt_warnings = [w for w in caught if "sqrt" in str(w.message)]
        assert sqrt_warnings == []

    def test_overlap_detection_still_works(self, qapp) -> None:
        """The warning suppression must not hide genuine overlaps."""
        optic = Optic()
        optic.surfaces.add(index=0, radius=be.inf, thickness=be.inf)
        # Strongly biconvex with a far too thin centre: at r ~ 4.9 the two
        # caps sag ~4 mm each and therefore intersect.
        optic.surfaces.add(index=1, radius=5.0, thickness=0.5, material="N-BK7")
        optic.surfaces.add(index=2, radius=-5.0, thickness=10.0)
        optic.set_aperture(aperture_type="EPD", value=2.0)
        optic.fields.set_type("angle")
        optic.fields.add(y=0.0)
        optic.wavelengths.add(value=0.55, is_primary=True)
        optic.updater.update()
        surfaces = [
            Surface2D(optic.surfaces.surfaces[1], 4.9),
            Surface2D(optic.surfaces.surfaces[2], 4.9),
        ]

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            Lens2D(surfaces)

        assert any("overlap" in str(w.message).lower() for w in caught)


class TestLensEditorEditorLifecycle:
    def _make_editor(self, mock_connector):
        from optiland_gui.lens_editor import LensEditor

        editor = LensEditor(mock_connector)
        editor.load_data()
        return editor

    def test_open_editor_is_closed_before_table_rebuild(
        self, qapp, mock_connector
    ) -> None:
        """Regression: rebuilding the table under an open editor orphaned it,
        which Qt reports as 'commitData ... does not belong to this view'."""
        from PySide6.QtWidgets import QAbstractItemView

        editor = self._make_editor(mock_connector)
        table = editor.tableWidget
        item = table.item(1, mock_connector.COL_RADIUS)
        assert item is not None

        table.editItem(item)
        assert table.state() == QAbstractItemView.State.EditingState

        editor.load_data()

        assert table.state() != QAbstractItemView.State.EditingState

    def test_close_active_cell_editor_is_safe_without_open_editor(
        self, qapp, mock_connector
    ) -> None:
        editor = self._make_editor(mock_connector)
        editor._close_active_cell_editor()  # must not raise
        assert editor.tableWidget.rowCount() > 0


class TestDrawingWarningReporting:
    def _make_panel(self):
        """A stand-in exercising the reporting logic with a real toast sink."""
        from optiland_gui.viewer_panel import MatplotlibViewer

        panel = MatplotlibViewer.__new__(MatplotlibViewer)
        panel.connector = MagicMock()
        panel.connector.toast_manager = MagicMock()
        panel._reported_drawing_warnings = set()
        return panel

    def _warning(self, text: str):
        entry = MagicMock()
        entry.message = text
        return entry

    def test_repeated_warning_is_reported_once(self, qapp) -> None:
        panel = self._make_panel()
        caught = [self._warning("Lens surfaces overlap.")]

        for _ in range(5):  # five repaints of the same design
            panel._report_drawing_warnings(caught)

        assert panel.connector.toast_manager.notify.call_count == 1

    def test_new_warning_is_reported(self, qapp) -> None:
        panel = self._make_panel()
        panel._report_drawing_warnings([self._warning("Lens surfaces overlap.")])
        panel._report_drawing_warnings(
            [self._warning("Lens surfaces overlap."), self._warning("Other problem")]
        )

        messages = [
            call.args[0] for call in panel.connector.toast_manager.notify.call_args_list
        ]
        assert messages == ["Lens surfaces overlap.", "Other problem"]

    def test_warning_reappears_after_being_resolved(self, qapp) -> None:
        panel = self._make_panel()
        overlap = [self._warning("Lens surfaces overlap.")]

        panel._report_drawing_warnings(overlap)
        panel._report_drawing_warnings([])  # user fixed the design
        panel._report_drawing_warnings(overlap)  # and broke it again

        assert panel.connector.toast_manager.notify.call_count == 2

    def test_falls_back_to_logging_without_toast_manager(self, qapp, caplog) -> None:
        panel = self._make_panel()
        panel.connector.toast_manager = None

        with caplog.at_level("WARNING"):
            panel._report_drawing_warnings([self._warning("Lens surfaces overlap.")])

        assert "Lens surfaces overlap." in caplog.text


@pytest.fixture()
def mock_connector(minimal_optic, qapp):
    conn = MagicMock()
    conn._optic = minimal_optic
    conn.toast_manager = MagicMock()
    conn.COL_TYPE = 0
    conn.COL_COMMENT = 1
    conn.COL_RADIUS = 2
    conn.COL_THICKNESS = 3
    conn.COL_MATERIAL = 4
    conn.COL_CONIC = 5
    conn.COL_SEMI_DIAMETER = 6
    conn.get_column_headers.return_value = [
        "Type", "Comment", "Radius", "Thickness", "Material", "Conic",
        "Semi-Diameter",
    ]
    conn.get_surface_count.return_value = 4
    conn.get_optimization_variables.return_value = []
    conn.get_surface_type_info.return_value = {
        "display_text": "Standard", "is_changeable": True,
        "has_extra_params": False,
    }
    conn.get_surface_geometry_params.return_value = {}
    conn.get_surface_aperture_config.return_value = {"type": "none"}
    conn.get_surface_data.return_value = ""
    conn.get_available_surface_types.return_value = ["standard", "aspheric"]
    conn.get_surface_group_metadata.return_value = {
        "group_id": None, "group_name": None, "group_role": None,
    }
    conn.get_group_rows.return_value = []
    conn.get_disabled_surface_indices.return_value = set()
    return conn
