"""Tests for the native/frameless window-chrome invariant.

These guard against the "double menu" regression: the custom title-bar toolbar
(which embeds a second menu bar) must be visible *if and only if* the window is in
frameless/fullscreen mode, and the native menu bar must be visible *if and only if*
the window is in normal mode. The invariant must hold even after ``restoreState``
re-shows the custom toolbar (e.g. stale QSettings from the original always-frameless
fork) — which is exactly what :meth:`MainWindow._sync_window_chrome` re-asserts.

The helpers are exercised on lightweight stubs (no full ``MainWindow`` or even a
``QApplication`` is required), matching the stub style in
``test_main_window_layouts.py``.
"""

from __future__ import annotations

from optiland_gui.main_window import MainWindow


class _MenuActionStub:
    def __init__(self) -> None:
        self.visible = True

    def setVisible(self, visible: bool) -> None:  # noqa: N802 (Qt API name)
        self.visible = bool(visible)


class _MenuBarStub:
    def __init__(self) -> None:
        self._action = _MenuActionStub()

    def menuAction(self):  # noqa: N802 (Qt API name)
        return self._action


class _ToolbarStub:
    def __init__(self, visible: bool = False) -> None:
        self.visible = visible

    def setVisible(self, visible: bool) -> None:  # noqa: N802 (Qt API name)
        self.visible = bool(visible)

    def isVisible(self) -> bool:  # noqa: N802 (Qt API name)
        return self.visible


def _make_chrome_stub(*, is_fullscreen: bool, toolbar_visible: bool):
    class _WindowStub:
        pass

    stub = _WindowStub()
    stub._fullscreen = is_fullscreen
    stub.isFullScreen = lambda: stub._fullscreen
    stub.title_bar_as_toolbar = _ToolbarStub(toolbar_visible)
    stub._native_menu_bar_instance = _MenuBarStub()
    stub._sync_window_chrome = MainWindow._sync_window_chrome.__get__(stub, _WindowStub)
    stub._normalize_chrome_for_save = MainWindow._normalize_chrome_for_save.__get__(
        stub, _WindowStub
    )
    return stub


def test_sync_chrome_normal_mode_hides_titlebar_shows_native_menu() -> None:
    # Simulate restoreState() having leaked the custom toolbar visible in normal mode.
    stub = _make_chrome_stub(is_fullscreen=False, toolbar_visible=True)

    stub._sync_window_chrome()

    assert stub.title_bar_as_toolbar.isVisible() is False
    assert stub._native_menu_bar_instance.menuAction().visible is True


def test_sync_chrome_fullscreen_shows_titlebar_hides_native_menu() -> None:
    stub = _make_chrome_stub(is_fullscreen=True, toolbar_visible=False)

    stub._sync_window_chrome()

    assert stub.title_bar_as_toolbar.isVisible() is True
    assert stub._native_menu_bar_instance.menuAction().visible is False


def test_sync_chrome_is_idempotent() -> None:
    stub = _make_chrome_stub(is_fullscreen=False, toolbar_visible=True)

    for _ in range(3):
        stub._sync_window_chrome()
        assert stub.title_bar_as_toolbar.isVisible() is False
        assert stub._native_menu_bar_instance.menuAction().visible is True


def test_normalize_chrome_for_save_hides_titlebar() -> None:
    # Saving while fullscreen must not persist the toolbar as visible.
    stub = _make_chrome_stub(is_fullscreen=True, toolbar_visible=True)

    stub._normalize_chrome_for_save()

    assert stub.title_bar_as_toolbar.isVisible() is False
