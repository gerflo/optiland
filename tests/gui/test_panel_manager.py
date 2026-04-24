from __future__ import annotations

from unittest.mock import MagicMock

from optiland_gui.panel_manager import PanelManager


def test_panel_manager_update_theme_propagates_to_all_theme_aware_panels() -> None:
    manager = PanelManager(MagicMock(), MagicMock())
    manager.sidebar_content_widget = MagicMock()
    manager.lens_editor = MagicMock()
    manager.catalogs_panel = MagicMock()
    manager.analysis_panel = MagicMock()
    manager.viewer_panel = MagicMock()
    manager.python_terminal = MagicMock()
    manager.optimization_panel = MagicMock()
    manager.system_properties = MagicMock()

    manager.update_theme("light")

    manager.sidebar_content_widget.update_icons.assert_called_once_with("light")
    manager.lens_editor.update_theme.assert_called_once_with("light")
    manager.catalogs_panel.update_theme.assert_called_once_with("light")
    manager.analysis_panel.update_theme.assert_called_once_with("light")
    manager.viewer_panel.update_theme.assert_called_once_with("light")
    manager.python_terminal.set_theme.assert_called_once_with("light")
    manager.optimization_panel.update_theme.assert_called_once_with("light")
    manager.system_properties.update_theme.assert_called_once_with("light")
