"""The System Viewer: System view as first tab, detachable viewer tabs.

The System view (the whole multi-axis system) is the first tab of the
System Viewer, next to the 2D and 3D layouts and the sag plot. Every tab
can be moved into a window of its own. The shared 2D/3D settings panel
follows the layout the user works in, docked or detached, and the 3D view
renders in its own window as it does in its tab.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QDeadlineTimer, QEventLoop, QObject, Signal
from PySide6.QtWidgets import QLabel, QMainWindow, QTabBar, QToolButton

from optiland_gui.panel_manager import PanelManager
from optiland_gui.viewer_panel import ViewerPanel
from optiland_gui.widgets.detachable_tabs import DetachableTabWidget


class _ConnectorStub(QObject):
    opticLoaded = Signal()
    opticChanged = Signal()

    def __init__(self, optic) -> None:  # noqa: ANN001
        super().__init__()
        self._optic = optic
        self.toast_manager = None

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

    def setValue(self, _key: str, _value) -> None:  # noqa: ANN001, N802
        return None


def _settle(qapp, ms: int = 80) -> None:
    deadline = QDeadlineTimer(ms)
    while not deadline.hasExpired():
        qapp.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 10)


@pytest.fixture()
def viewer(qapp, minimal_optic, monkeypatch):
    """A System Viewer with a System tab, shown in a main window."""
    monkeypatch.setattr("optiland_gui.viewer_panel.QSettings", _DefaultSettings)
    # No real VTK view: these tests are about where the tabs and panels
    # go (the 3D view in a detached window was checked in the running GUI).
    monkeypatch.setattr(ViewerPanel, "_render_3d_now", lambda self: None)
    window = QMainWindow()
    system = QLabel("system view")
    panel = ViewerPanel(_ConnectorStub(minimal_optic), system_panel=system)
    window.setCentralWidget(panel)
    window.resize(1000, 700)
    window.show()
    _settle(qapp)
    yield panel
    panel.tabWidget.attach_all()
    window.close()
    window.deleteLater()


def test_the_system_view_is_the_first_tab(viewer) -> None:
    tabs = viewer.tabWidget
    assert isinstance(tabs, DetachableTabWidget)
    assert tabs.widget(0) is viewer.system_panel
    assert tabs.tabText(0) == "System"
    assert tabs.keys()[0] == ViewerPanel.SYSTEM_TAB
    names = [tabs.tabText(i) for i in range(tabs.count())]
    assert names[1] == "2D Layout"
    assert names[-1] == "Sag"


def test_without_a_system_view_the_layout_comes_first(qapp, minimal_optic, monkeypatch):
    monkeypatch.setattr("optiland_gui.viewer_panel.QSettings", _DefaultSettings)
    panel = ViewerPanel(_ConnectorStub(minimal_optic))

    assert panel.tabWidget.tabText(0) == "2D Layout"
    assert panel.tabWidget.page(ViewerPanel.SYSTEM_TAB) is None


def test_every_viewer_tab_has_a_detach_button(viewer) -> None:
    tabs = viewer.tabWidget
    for index in range(tabs.count()):
        button = tabs.tabBar().tabButton(index, QTabBar.ButtonPosition.RightSide)
        assert isinstance(button, QToolButton), tabs.tabText(index)


def test_show_view_raises_a_detached_system_view(viewer, qapp) -> None:
    tabs = viewer.tabWidget
    tabs.detach_tab(ViewerPanel.SYSTEM_TAB)
    tabs.detached_window(ViewerPanel.SYSTEM_TAB).hide()

    viewer.show_view(ViewerPanel.SYSTEM_TAB)
    _settle(qapp)

    assert tabs.detached_window(ViewerPanel.SYSTEM_TAB).isVisible()


def test_the_settings_panel_follows_a_detached_2d_layout(viewer, qapp) -> None:
    tabs = viewer.tabWidget
    settings = viewer.settings_area
    page_2d = tabs.page(ViewerPanel.LAYOUT_2D_TAB)
    tabs.setCurrentWidget(page_2d)
    viewer.viewer2D.settings_toggle_btn.setChecked(True)
    assert settings.isVisible()

    tabs.detach_tab(ViewerPanel.LAYOUT_2D_TAB)
    _settle(qapp)

    # The 2D layout took its settings along into the window.
    window = tabs.detached_window(ViewerPanel.LAYOUT_2D_TAB)
    assert settings.window() is window
    assert settings.isVisible()

    # The Sag tab in the viewer has settings of its own; the window keeps
    # showing the layout settings.
    tabs.setCurrentWidget(viewer.sagViewer)
    _settle(qapp)
    assert settings.window() is window
    assert settings.isVisible()

    # Docked again behind the Sag tab: nothing on show needs the panel.
    tabs.attach_tab(ViewerPanel.LAYOUT_2D_TAB)
    _settle(qapp)
    assert settings.isHidden()


@pytest.mark.skipif(
    not ViewerPanel.__init__.__globals__["VTK_AVAILABLE"], reason="VTK missing"
)
def test_the_settings_panel_moves_to_the_layout_in_use(viewer, qapp) -> None:
    tabs = viewer.tabWidget
    settings = viewer.settings_area
    viewer.viewer2D.settings_toggle_btn.setChecked(True)
    tabs.detach_tab(ViewerPanel.LAYOUT_2D_TAB)
    window_2d = tabs.detached_window(ViewerPanel.LAYOUT_2D_TAB)
    _settle(qapp)  # the new window becomes active (asynchronously)

    # Working in the docked 3D layout brings the settings there ...
    tabs.setCurrentWidget(tabs.page(ViewerPanel.LAYOUT_3D_TAB))
    assert settings.parentWidget() is tabs.page(ViewerPanel.LAYOUT_3D_TAB)
    assert settings.isVisible()

    # ... and activating the 2D window takes them back.
    window_2d.activated.emit(ViewerPanel.LAYOUT_2D_TAB)
    assert settings.window() is window_2d
    assert settings.isVisible()


@pytest.mark.skipif(
    not ViewerPanel.__init__.__globals__["VTK_AVAILABLE"], reason="VTK missing"
)
def test_a_detached_3d_layout_renders_in_its_window(viewer, qapp, monkeypatch) -> None:
    tabs = viewer.tabWidget
    tabs.setCurrentWidget(viewer.system_panel)
    renders: list[bool] = []
    monkeypatch.setattr(viewer, "_render_3d_now", lambda: renders.append(True))
    viewer.update_viewers()  # the 3D tab is not on show: the render waits
    assert viewer._pending_3d_render
    assert not viewer._is_3d_tab_active()

    tabs.detach_tab(ViewerPanel.LAYOUT_3D_TAB)
    _settle(qapp)

    assert viewer._is_3d_tab_active()
    assert renders, "the pending 3D render did not run in the detached window"


# ---------------------------------------------------------------------------
# Panel manager
# ---------------------------------------------------------------------------


def _manager_with_tabs(qapp) -> tuple[PanelManager, DetachableTabWidget]:
    manager = PanelManager(MagicMock(), MagicMock())
    tabs = DetachableTabWidget()
    tabs.setObjectName("SystemViewerTabs")
    for key in (ViewerPanel.SYSTEM_TAB, ViewerPanel.LAYOUT_2D_TAB, "sag"):
        tabs.add_page(QLabel(key), key, key)
    manager.viewer_panel = SimpleNamespace(tabWidget=tabs, show_view=MagicMock())
    manager.viewer_dock = MagicMock()
    return manager, tabs


def test_show_system_panel_focuses_the_viewer_dock(qapp) -> None:
    manager, _tabs = _manager_with_tabs(qapp)

    manager.show_system_panel()

    manager.main_window.focus_dock_widget.assert_called_once_with(manager.viewer_dock)
    manager.viewer_panel.show_view.assert_called_once_with(ViewerPanel.SYSTEM_TAB)


def test_show_system_panel_leaves_the_dock_alone_when_detached(qapp) -> None:
    manager, tabs = _manager_with_tabs(qapp)
    tabs.detach_tab(ViewerPanel.SYSTEM_TAB)

    manager.show_system_panel()

    manager.main_window.focus_dock_widget.assert_not_called()
    manager.viewer_panel.show_view.assert_called_once_with(ViewerPanel.SYSTEM_TAB)
    tabs.attach_all()


def test_the_sidebar_system_button_shows_the_system_tab(qapp) -> None:
    manager, _tabs = _manager_with_tabs(qapp)

    manager.on_sidebar_menu_selected("nonsequential")

    manager.viewer_panel.show_view.assert_called_once_with(ViewerPanel.SYSTEM_TAB)


def test_tab_state_is_keyed_by_the_tab_widget(qapp) -> None:
    manager, tabs = _manager_with_tabs(qapp)
    tabs.detach_tab(ViewerPanel.LAYOUT_2D_TAB)

    state = manager.save_tab_state(include_remembered=False)
    manager.attach_all_tabs()
    assert tabs.detached_keys() == []
    manager.restore_tab_state(state)

    assert set(state) == {"SystemViewerTabs"}
    assert tabs.detached_keys() == [ViewerPanel.LAYOUT_2D_TAB]

    # A layout without tab data (saved before tabs could be detached)
    # docks everything.
    manager.restore_tab_state({})
    assert tabs.detached_keys() == []


def test_the_default_layout_docks_every_tab(qapp) -> None:
    manager, tabs = _manager_with_tabs(qapp)
    for name in (
        "sidebar",
        "lens_editor_dock",
        "system_properties_dock",
        "analysis_dock",
        "optimization_dock",
        "catalog_browser_dock",
        "terminal_dock",
        "catalogs_panel",
    ):
        setattr(manager, name, MagicMock())
    manager.all_docks = [manager.sidebar, manager.viewer_dock]
    tabs.detach_tab(ViewerPanel.SYSTEM_TAB)

    manager.setup_default_layout()

    assert tabs.detached_keys() == []


def test_hiding_detached_windows_keeps_them_detached(qapp) -> None:
    manager, tabs = _manager_with_tabs(qapp)
    tabs.detach_tab("sag")

    manager.hide_detached_windows()

    assert tabs.detached_keys() == ["sag"]
    assert not tabs.detached_window("sag").isVisible()
    tabs.attach_all()
