"""Tests for themed toolbar/menu action icons.

Verifies that the icon base names wired onto Quick Actions toolbar actions
resolve to real bundled resources (guarding against typos / missing files) and
that :meth:`ActionManager.apply_theme_icons` assigns them for a given theme mode.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from optiland_gui.resources import resources_rc  # noqa: F401  (registers :/icons)

# Icon base names referenced by the Quick Actions toolbar actions.
TOOLBAR_ICON_BASES = ["add", "load_settings", "save_settings", "dash", "refresh"]


@pytest.mark.parametrize("mode", ["dark", "light"])
@pytest.mark.parametrize("base", TOOLBAR_ICON_BASES)
def test_toolbar_icon_resource_exists(qapp, mode: str, base: str) -> None:
    from PySide6.QtGui import QIcon

    assert not QIcon(f":/icons/{mode}/{base}.svg").isNull()


def test_apply_theme_icons_assigns_declared_icons(qapp) -> None:
    from PySide6.QtGui import QAction

    from optiland_gui.action_manager import ActionManager

    manager = ActionManager(MagicMock(), MagicMock())
    action = QAction("Demo")
    manager.actions = {"demo": action}
    manager._action_icons = {"demo": "add"}

    manager.apply_theme_icons("dark")
    assert not action.icon().isNull()

    # Switching themes re-assigns the variant without error.
    manager.apply_theme_icons("light")
    assert not action.icon().isNull()
