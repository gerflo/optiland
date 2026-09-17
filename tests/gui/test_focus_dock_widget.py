"""Regression test: focusing a tabified dock must bring its tab to the front.

``MainWindow.focus_dock_widget`` looked for a ``QTabWidget`` parent, but
``QMainWindow`` tabifies docks with an internal tab bar and keeps the main
window as their parent, so a sidebar click on a dock that shared a tab
group with another dock (Analysis next to Non-Sequential, for instance)
showed nothing.
"""

from __future__ import annotations

from PySide6.QtCore import QDeadlineTimer, QEventLoop, Qt
from PySide6.QtWidgets import QDockWidget, QLabel, QMainWindow

from optiland_gui.main_window import MainWindow


def _settle(qapp, ms: int = 150) -> None:
    deadline = QDeadlineTimer(ms)
    while not deadline.hasExpired():
        qapp.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 20)


def test_focus_dock_widget_raises_a_tabified_dock(qapp) -> None:
    window = QMainWindow()
    first = QDockWidget("First", window)
    first.setWidget(QLabel("first"))
    second = QDockWidget("Second", window)
    second.setWidget(QLabel("second"))
    window.addDockWidget(Qt.RightDockWidgetArea, first)
    window.addDockWidget(Qt.RightDockWidgetArea, second)
    window.tabifyDockWidget(first, second)
    window.resize(600, 400)
    window.show()
    first.raise_()
    _settle(qapp)
    # Tabified docks stay "visible" in Qt's sense; the one behind the
    # current tab simply has no visible region.
    assert not first.visibleRegion().isEmpty()
    assert second.visibleRegion().isEmpty()

    MainWindow.focus_dock_widget(window, second)
    _settle(qapp)

    assert not second.visibleRegion().isEmpty()
    assert first.visibleRegion().isEmpty()
    window.close()
