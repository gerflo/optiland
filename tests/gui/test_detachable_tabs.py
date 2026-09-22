"""Tests for tabs that can be shown in windows of their own.

Covers :class:`optiland_gui.widgets.detachable_tabs.DetachableTabWidget`
and its use in the System Viewer: every tab has a button that moves it into
a separate window, the last docked tab has none, closing a window docks
its tab again at its old place, window positions are remembered, and the
arrangement survives a save/restore round trip (the data a window layout
stores).
"""

from __future__ import annotations

import json

import pytest
from PySide6.QtCore import QByteArray, QDeadlineTimer, QEventLoop, QRect
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QLabel, QMainWindow, QTabBar, QToolButton

from optiland_gui.widgets.detachable_tabs import (
    DETACH_BUTTON_NAME,
    DetachableTabWidget,
    decode_geometry,
    encode_geometry,
)


def _settle(qapp, ms: int = 50) -> None:
    deadline = QDeadlineTimer(ms)
    while not deadline.hasExpired():
        qapp.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 10)


def _button(tabs: DetachableTabWidget, index: int) -> QToolButton | None:
    button = tabs.tabBar().tabButton(index, QTabBar.ButtonPosition.RightSide)
    return button if isinstance(button, QToolButton) else None


@pytest.fixture()
def tabs(qapp):
    """Three tabs "a", "b", "c" in a shown main window (their windows' owner)."""
    window = QMainWindow()
    widget = DetachableTabWidget("Viewer")
    widget.setObjectName("TestTabs")
    for key in ("a", "b", "c"):
        widget.add_page(QLabel(f"page {key}"), key.upper(), key)
    window.setCentralWidget(widget)
    window.resize(700, 500)
    window.show()
    _settle(qapp)
    yield widget
    widget.attach_all()
    window.close()
    window.deleteLater()


def _tab_texts(tabs: DetachableTabWidget) -> list[str]:
    return [tabs.tabText(i) for i in range(tabs.count())]


class TestDetachButtons:
    def test_every_tab_has_a_detach_button(self, tabs):
        for index in range(tabs.count()):
            button = _button(tabs, index)
            assert button is not None
            assert button.objectName() == DETACH_BUTTON_NAME
            assert button.toolTip()

    def test_the_button_detaches_its_own_tab(self, tabs):
        _button(tabs, 1).click()

        assert tabs.is_detached("b")
        assert _tab_texts(tabs) == ["A", "C"]

    def test_the_last_docked_tab_cannot_be_detached(self, tabs):
        assert tabs.detach_tab("a")
        assert tabs.detach_tab("b")

        assert tabs.count() == 1
        assert _button(tabs, 0) is None
        assert not tabs.can_detach("c")
        assert not tabs.detach_tab("c")
        assert tabs.count() == 1
        assert tabs.currentWidget() is tabs.page("c")

    def test_the_button_comes_back_with_a_second_docked_tab(self, tabs):
        tabs.detach_tab("a")
        tabs.detach_tab("b")

        tabs.attach_tab("a")

        assert _tab_texts(tabs) == ["A", "C"]
        assert _button(tabs, 0) is not None
        assert _button(tabs, 1) is not None


class TestDetachAndAttach:
    def test_detaching_moves_the_page_into_a_visible_window(self, tabs, qapp):
        page = tabs.page("b")

        assert tabs.detach_tab("b")
        _settle(qapp)

        window = tabs.detached_window("b")
        assert window is not None and window.isWindow()
        assert window.isVisible()
        assert page.window() is window
        assert page.isVisible()
        assert window.windowTitle() == "B — Viewer"
        assert tabs.indexOf(page) == -1
        assert tabs.is_page_visible(page)

    def test_a_detached_window_belongs_to_the_main_window(self, tabs):
        tabs.detach_tab("b")

        # Owned by the main window: it stays above it and goes with it.
        assert tabs.detached_window("b").parentWidget() is tabs.window()

    def test_the_main_window_shortcuts_work_in_a_detached_window(self, tabs):
        main = tabs.window()
        save = QAction("Save", main)
        save.setShortcut(QKeySequence("Ctrl+S"))
        plain = QAction("No shortcut", main)
        # A panel's own shortcut (a table's Delete, say) stays with it.
        nested = QAction("Delete row", tabs.page("a"))
        nested.setShortcut(QKeySequence("Del"))

        tabs.detach_tab("b")

        actions = tabs.detached_window("b").actions()
        assert save in actions
        assert plain not in actions
        assert nested not in actions

    def test_attaching_restores_the_original_order(self, tabs):
        tabs.detach_tab("a")
        tabs.detach_tab("b")
        assert _tab_texts(tabs) == ["C"]

        tabs.attach_tab("b")
        assert _tab_texts(tabs) == ["B", "C"]
        tabs.attach_tab("a")
        assert _tab_texts(tabs) == ["A", "B", "C"]

    def test_closing_the_window_docks_and_selects_the_tab(self, tabs, qapp):
        tabs.setCurrentIndex(0)
        tabs.detach_tab("b")
        window = tabs.detached_window("b")
        attached: list[str] = []
        tabs.tabAttached.connect(attached.append)

        window.close()
        _settle(qapp)

        assert not tabs.is_detached("b")
        assert _tab_texts(tabs) == ["A", "B", "C"]
        assert tabs.currentWidget() is tabs.page("b")
        assert attached == ["b"]

    def test_signals_report_detach_and_attach(self, tabs):
        detached: list[str] = []
        attached: list[str] = []
        tabs.tabDetached.connect(detached.append)
        tabs.tabAttached.connect(attached.append)

        tabs.detach_tab("c")
        tabs.attach_all()

        assert detached == ["c"]
        assert attached == ["c"]

    def test_show_page_raises_a_detached_window_or_selects_a_tab(self, tabs, qapp):
        tabs.detach_tab("b")
        tabs.detached_window("b").hide()

        tabs.show_page("b")
        tabs.show_page("c")
        _settle(qapp)

        assert tabs.detached_window("b").isVisible()
        assert tabs.currentWidget() is tabs.page("c")


class TestRememberedPositions:
    def test_a_window_reopens_where_it_was(self, tabs, qapp):
        tabs.detach_tab("b")
        window = tabs.detached_window("b")
        window.setGeometry(QRect(220, 180, 420, 310))
        _settle(qapp)
        placed = window.geometry()

        window.close()
        _settle(qapp)
        tabs.detach_tab("b")
        _settle(qapp)

        assert tabs.detached_window("b").geometry() == placed

    def test_a_new_window_opens_next_to_the_tabs_at_the_page_size(self, tabs, qapp):
        size = tabs.page("a").size()

        tabs.detach_tab("a")
        _settle(qapp)

        window = tabs.detached_window("a")
        assert window.size() == size
        origin = tabs.mapToGlobal(tabs.rect().topLeft())
        assert window.geometry().topLeft().x() > origin.x()
        assert window.geometry().topLeft().y() > origin.y()


class TestState:
    def test_state_round_trip_detaches_at_the_saved_geometry(self, tabs, qapp):
        tabs.detach_tab("b")
        tabs.detached_window("b").setGeometry(QRect(260, 200, 400, 300))
        tabs.setCurrentWidget(tabs.page("c"))
        _settle(qapp)
        placed = tabs.detached_window("b").geometry()
        state = json.loads(json.dumps(tabs.save_state()))

        tabs.attach_all()
        tabs.setCurrentWidget(tabs.page("a"))
        tabs.restore_state(state)
        _settle(qapp)

        assert tabs.detached_keys() == ["b"]
        assert tabs.detached_window("b").geometry() == placed
        assert tabs.current_key() == "c"
        assert _tab_texts(tabs) == ["A", "C"]

    def test_restore_moves_an_open_window(self, tabs, qapp):
        tabs.detach_tab("b")
        tabs.detached_window("b").setGeometry(QRect(300, 240, 380, 280))
        _settle(qapp)
        state = tabs.save_state(include_remembered=False)
        placed = tabs.detached_window("b").geometry()
        tabs.detached_window("b").setGeometry(QRect(120, 100, 500, 350))

        tabs.restore_state(state)
        _settle(qapp)

        assert tabs.detached_window("b").geometry() == placed

    def test_an_empty_state_docks_every_tab(self, tabs):
        tabs.detach_tab("a")
        tabs.detach_tab("c")

        tabs.restore_state({})

        assert tabs.detached_keys() == []
        assert _tab_texts(tabs) == ["A", "B", "C"]

    def test_unknown_keys_and_bad_data_are_ignored(self, tabs):
        tabs.restore_state(
            {
                "current": ["not", "a", "key"],
                "detached": {"zzz": "abc", "b": 12},
                "remembered": "nonsense",
            }
        )

        # "b" had no usable geometry: detached at the default place.
        assert tabs.detached_keys() == ["b"]

    def test_a_state_that_detaches_everything_keeps_one_tab_docked(self, tabs):
        tabs.restore_state({"detached": {"a": "", "b": "", "c": ""}})

        assert tabs.count() == 1
        assert tabs.detached_keys() == ["a", "b"]

    def test_the_saved_state_remembers_closed_windows(self, tabs, qapp):
        tabs.detach_tab("a")
        tabs.detached_window("a").setGeometry(QRect(240, 210, 400, 300))
        _settle(qapp)
        tabs.detached_window("a").close()
        _settle(qapp)

        session = tabs.save_state()
        layout = tabs.save_state(include_remembered=False)

        assert session["detached"] == {}
        assert set(session["remembered"]) == {"a"}
        assert "remembered" not in layout

    def test_geometry_codec_round_trip(self):
        data = QByteArray(b"\x01\x02geometry\xff")
        assert decode_geometry(encode_geometry(data)) == data
        assert decode_geometry("") is None
        assert decode_geometry(None) is None


class TestPendingWindows:
    def test_windows_wait_for_a_hidden_owner(self, qapp):
        window = QMainWindow()
        tabs = DetachableTabWidget()
        tabs.add_page(QLabel("a"), "A", "a")
        tabs.add_page(QLabel("b"), "B", "b")
        window.setCentralWidget(tabs)

        tabs.restore_state({"detached": {"b": ""}})

        detached = tabs.detached_window("b")
        assert detached is not None
        assert not detached.isVisible()  # no owner on screen to stay above

        window.show()
        _settle(qapp, 150)

        assert detached.isVisible()
        tabs.attach_all()
        window.close()
        window.deleteLater()


class TestPageActivation:
    def test_switching_tabs_activates_the_page(self, tabs):
        activated = []
        tabs.pageActivated.connect(activated.append)

        tabs.setCurrentWidget(tabs.page("b"))

        assert activated == [tabs.page("b")]

    def test_activating_a_detached_window_activates_its_page(self, tabs, qapp):
        tabs.detach_tab("c")
        activated = []
        tabs.pageActivated.connect(activated.append)

        tabs.detached_window("c").activated.emit("c")

        assert activated == [tabs.page("c")]
