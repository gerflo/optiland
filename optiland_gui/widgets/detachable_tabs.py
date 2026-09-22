"""A tab widget whose tabs can be shown in windows of their own.

Every tab gets a small button that moves its page into a separate
top-level window. Closing that window puts the page back into its old
place among the tabs. The last tab that is still docked has no button, so
the tab widget is never left empty.

The widget remembers where each window was, and :meth:`save_state` /
:meth:`restore_state` turn the whole arrangement (current tab, detached
tabs and their window geometry) into plain JSON-friendly data, so a
window layout can store it next to the dock state.

Author: Optiland contributors, 2026
"""

from __future__ import annotations

from collections.abc import Mapping

from PySide6.QtCore import (
    QByteArray,
    QEvent,
    QPoint,
    QPointF,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QAction,
    QColor,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QTabBar,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..theme_manager import get_theme

#: Object name of the per-tab detach buttons (for style sheets and tests).
DETACH_BUTTON_NAME = "DetachTabButton"
_DETACH_TOOLTIP = "Show in a separate window (close the window to dock it again)"
#: Size of a new window when the page has no usable size yet.
_DEFAULT_WINDOW_SIZE = QSize(900, 600)
#: A new window opens this far from the tab widget's top-left corner.
_WINDOW_OFFSET = QPoint(40, 40)


def encode_geometry(geometry: QByteArray) -> str:
    """``QWidget.saveGeometry`` data as a JSON-friendly base64 string."""
    return bytes(geometry.toBase64().data()).decode("ascii")


def decode_geometry(text: object) -> QByteArray | None:
    """The geometry that :func:`encode_geometry` wrote, or ``None``."""
    if not isinstance(text, str) or not text:
        return None
    try:
        data = QByteArray.fromBase64(text.encode("ascii"))
    except UnicodeEncodeError:
        return None
    return data if not data.isEmpty() else None


def popout_icon(color: QColor, size: int = 14) -> QIcon:
    """A window frame with an arrow leaving its top-right corner.

    Args:
        color: Stroke colour.
        size: Edge length in device-independent pixels.
    """
    scale = 2.0
    pixmap = QPixmap(round(size * scale), round(size * scale))
    pixmap.setDevicePixelRatio(scale)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(color, 1.4)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    s = size / 14.0
    frame = QPainterPath(QPointF(6.0 * s, 2.5 * s))
    for x, y in ((2.5, 2.5), (2.5, 11.5), (11.5, 11.5), (11.5, 8.0)):
        frame.lineTo(QPointF(x * s, y * s))
    painter.drawPath(frame)
    painter.drawLine(QPointF(6.5 * s, 7.5 * s), QPointF(12.0 * s, 2.0 * s))
    head = QPainterPath(QPointF(8.0 * s, 2.0 * s))
    head.lineTo(QPointF(12.0 * s, 2.0 * s))
    head.lineTo(QPointF(12.0 * s, 6.0 * s))
    painter.drawPath(head)
    painter.end()
    return QIcon(pixmap)


def _foreground_color(widget: QWidget) -> QColor:
    """Text colour of the active theme (the palette's before one is set)."""
    app = QApplication.instance()
    theme_id = app.property("activeThemeId") if app is not None else None
    if theme_id:
        return QColor(get_theme(str(theme_id)).palette["text"])
    return widget.palette().color(widget.palette().ColorRole.WindowText)


class DetachedTabWindow(QWidget):
    """A top-level window that shows one page of a :class:`DetachableTabWidget`.

    Args:
        key: The page's key in the tab widget.
        title: Window title.
        owner: Widget that owns the window (the main window): the window
            stays above it and closes with the application.
    """

    #: The user closed the window; the page should go back to the tabs.
    closed = Signal(str)
    #: The window became the active window.
    activated = Signal(str)
    #: The window was shown.
    shown = Signal(str)

    def __init__(self, key: str, title: str, owner: QWidget | None) -> None:
        super().__init__(owner, Qt.WindowType.Window)
        self.key = key
        self.setObjectName(f"DetachedTabWindow_{key}")
        self.setWindowTitle(title)
        if owner is not None:
            if not owner.windowIcon().isNull():
                self.setWindowIcon(owner.windowIcon())
            # The owner's keyboard shortcuts (save, undo, full screen, ...)
            # work in this window as they do in the owner. Only its own
            # actions: shortcuts of panels deeper down stay with them.
            self.addActions(
                [
                    action
                    for action in owner.findChildren(
                        QAction, options=Qt.FindChildOption.FindDirectChildrenOnly
                    )
                    if not action.shortcut().isEmpty()
                ]
            )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

    def set_page(self, page: QWidget) -> None:
        """Show *page* as the window's only content."""
        self.layout().addWidget(page)
        # The tab widget's stack hid the page when it was not current.
        page.show()

    def take_page(self) -> QWidget | None:
        """Remove the page from the window and return it."""
        item = self.layout().takeAt(0)
        return item.widget() if item is not None else None

    def closeEvent(self, event) -> None:  # noqa: ANN001, N802 -- Qt override
        """Let the tab widget take the page back."""
        event.accept()
        self.closed.emit(self.key)

    def showEvent(self, event) -> None:  # noqa: ANN001, N802 -- Qt override
        """Report that the page is on screen now."""
        super().showEvent(event)
        self.shown.emit(self.key)

    def changeEvent(self, event) -> None:  # noqa: ANN001, N802 -- Qt override
        """Report activation, so views can follow the window the user works in."""
        super().changeEvent(event)
        if event.type() == QEvent.Type.ActivationChange and self.isActiveWindow():
            self.activated.emit(self.key)


class DetachableTabWidget(QTabWidget):
    """Tab widget whose pages can move into separate windows and back.

    Pages are added with :meth:`add_page` under a stable key; the key, not
    the tab index, names a page in every other call and in the saved state.

    Args:
        window_title: Appended to a page's title for its window's title.
        parent: Optional parent widget.
    """

    #: A page moved into its own window (argument: its key).
    tabDetached = Signal(str)
    #: A page came back into the tabs (argument: its key).
    tabAttached = Signal(str)
    #: The window of a detached page was shown (argument: its key).
    detachedWindowShown = Signal(str)
    #: The user now works in this page: its tab became current, its window
    #: became active, or the tab widget's window became active.
    pageActivated = Signal(QWidget)

    def __init__(self, window_title: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._window_title = window_title
        self._order: list[str] = []
        self._pages: dict[str, QWidget] = {}
        self._titles: dict[str, str] = {}
        self._windows: dict[str, DetachedTabWindow] = {}
        self._remembered: dict[str, QByteArray] = {}
        self._pending: set[str] = set()
        self._watched_owner: QWidget | None = None
        self.currentChanged.connect(self._on_current_changed)

    # ------------------------------------------------------------------
    # Pages
    # ------------------------------------------------------------------

    def add_page(self, page: QWidget, title: str, key: str) -> int:
        """Append *page* as a tab that can be detached.

        Args:
            page: The page widget.
            title: Tab text (and the start of its window title).
            key: Stable name of the page, unique within this widget.

        Returns:
            The new tab's index.
        """
        if key in self._pages:
            raise ValueError(f"A page with key {key!r} exists already")
        self._order.append(key)
        self._pages[key] = page
        self._titles[key] = title
        return self.addTab(page, title)

    def keys(self) -> list[str]:
        """Keys of all pages, in tab order."""
        return list(self._order)

    def page(self, key: str) -> QWidget | None:
        """The page stored under *key*, docked or detached."""
        return self._pages.get(key)

    def page_key(self, page: QWidget | None) -> str | None:
        """The key of *page*, or ``None`` if it is not one of this widget's."""
        for key, candidate in self._pages.items():
            if candidate is page:
                return key
        return None

    def current_key(self) -> str | None:
        """Key of the current tab."""
        return self.page_key(self.currentWidget())

    def is_detached(self, key: str) -> bool:
        """Whether the page *key* is shown in a window of its own."""
        return key in self._windows

    def detached_keys(self) -> list[str]:
        """Keys of the detached pages, in tab order."""
        return [key for key in self._order if key in self._windows]

    def detached_window(self, key: str) -> DetachedTabWindow | None:
        """The window that shows the detached page *key*."""
        return self._windows.get(key)

    def can_detach(self, key: str) -> bool:
        """Whether *key* is a docked page that is not the last docked tab."""
        return key in self._pages and key not in self._windows and self.count() > 1

    def is_page_visible(self, page: QWidget | None) -> bool:
        """Whether *page* is on show: the current tab, or in a visible window."""
        key = self.page_key(page)
        if key is None:
            return False
        window = self._windows.get(key)
        if window is not None:
            return window.isVisible()
        return self.currentWidget() is page

    def show_page(self, key: str) -> None:
        """Bring the page *key* to the front: select its tab or raise its window."""
        window = self._windows.get(key)
        if window is not None:
            self._pending.discard(key)
            window.show()
            window.raise_()
            window.activateWindow()
            return
        page = self._pages.get(key)
        if page is not None:
            self.setCurrentWidget(page)

    # ------------------------------------------------------------------
    # Detaching and attaching
    # ------------------------------------------------------------------

    def detach_tab(
        self, key: str, geometry: QByteArray | None = None, activate: bool = True
    ) -> bool:
        """Move the page *key* into a window of its own.

        Args:
            key: The page to detach.
            geometry: ``saveGeometry`` data for the window. Without it the
                window opens where this page's window was last, or next
                to the tabs at the page's size.
            activate: Raise and focus the new window.

        Returns:
            ``False`` when the page cannot be detached (unknown, already
            detached, or the last docked tab).
        """
        if not self.can_detach(key):
            return False
        page = self._pages[key]
        size = page.size()
        origin = self.mapToGlobal(QPoint(0, 0))
        self.removeTab(self.indexOf(page))

        window = DetachedTabWindow(key, self._window_caption(key), self._window_owner())
        window.closed.connect(self._on_window_closed)
        window.activated.connect(self._on_window_activated)
        window.shown.connect(self.detachedWindowShown)
        window.set_page(page)
        self._windows[key] = window

        geometry = geometry if geometry is not None else self._remembered.get(key)
        if geometry is None or not window.restoreGeometry(geometry):
            usable = size.width() >= 200 and size.height() >= 150
            window.resize(size if usable else _DEFAULT_WINDOW_SIZE)
            window.move(origin + _WINDOW_OFFSET)

        owner = self._window_owner()
        if owner is self or owner.isVisible():
            window.show()
            if activate:
                window.raise_()
                window.activateWindow()
        else:
            # A window shown before its owner has no owner on screen to
            # stay above; it appears when the owner does.
            self._pending.add(key)
            self._watch_owner(owner)
        self.tabDetached.emit(key)
        return True

    def attach_tab(self, key: str, select: bool = False) -> bool:
        """Put the detached page *key* back at its place among the tabs.

        Args:
            key: The page to dock again.
            select: Make it the current tab.

        Returns:
            ``False`` when the page was not detached.
        """
        window = self._windows.pop(key, None)
        if window is None:
            return False
        self._pending.discard(key)
        self._remembered[key] = window.saveGeometry()
        page = window.take_page()
        window.hide()
        window.deleteLater()
        if page is None:
            return False
        self.insertTab(self._attach_index(key), page, self._titles[key])
        if select:
            self.setCurrentWidget(page)
        self.tabAttached.emit(key)
        return True

    def attach_all(self) -> None:
        """Dock every detached page again."""
        for key in self.detached_keys():
            self.attach_tab(key)

    def hide_windows(self) -> None:
        """Hide the detached windows without docking their pages (at exit)."""
        for window in self._windows.values():
            window.hide()

    def show_pending_windows(self) -> None:
        """Show the windows that waited for their owner to appear."""
        for key in [k for k in self._order if k in self._pending]:
            self._pending.discard(key)
            window = self._windows.get(key)
            if window is not None:
                window.show()

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------

    def save_state(self, include_remembered: bool = True) -> dict:
        """The arrangement as JSON-friendly data.

        Args:
            include_remembered: Also store where the windows of the docked
                pages were last (the session state wants it, a saved
                window layout does not).

        Returns:
            ``{"current": key, "detached": {key: geometry}}`` plus
            ``"remembered": {key: geometry}`` when asked for.
        """
        state: dict = {
            "current": self.current_key(),
            "detached": {
                key: encode_geometry(self._windows[key].saveGeometry())
                for key in self.detached_keys()
            },
        }
        if include_remembered:
            state["remembered"] = {
                key: encode_geometry(geometry)
                for key, geometry in self._remembered.items()
                if key not in self._windows
            }
        return state

    def restore_state(self, state: Mapping | None) -> None:
        """Arrange the pages as :meth:`save_state` described them.

        Pages missing from ``state["detached"]`` are docked again, so an
        empty state (a layout saved before tabs could be detached) docks
        everything. Unknown keys are ignored.

        Args:
            state: Data from :meth:`save_state`, or ``None``.
        """
        state = state if isinstance(state, Mapping) else {}
        remembered = state.get("remembered")
        if isinstance(remembered, Mapping):
            for key, text in remembered.items():
                geometry = decode_geometry(text)
                if geometry is not None and key in self._pages:
                    self._remembered[key] = geometry
        detached = state.get("detached")
        wanted: dict[str, QByteArray | None] = {}
        if isinstance(detached, Mapping):
            wanted = {
                key: decode_geometry(text)
                for key, text in detached.items()
                if key in self._pages
            }
        for key in self.detached_keys():
            if key not in wanted:
                self.attach_tab(key)
        for key in self._order:
            if key not in wanted:
                continue
            geometry = wanted[key]
            window = self._windows.get(key)
            if window is None:
                self.detach_tab(key, geometry, activate=False)
            elif geometry is not None:
                window.restoreGeometry(geometry)
        current = state.get("current")
        if (
            isinstance(current, str)
            and current in self._pages
            and current not in self._windows
        ):
            self.setCurrentWidget(self._pages[current])

    # ------------------------------------------------------------------
    # Theme
    # ------------------------------------------------------------------

    def update_theme(self) -> None:
        """Redraw the detach buttons in the active theme's text colour."""
        icon = popout_icon(_foreground_color(self))
        bar = self.tabBar()
        for index in range(self.count()):
            button = bar.tabButton(index, QTabBar.ButtonPosition.RightSide)
            if isinstance(button, QToolButton):
                button.setIcon(icon)

    # ------------------------------------------------------------------
    # Qt overrides and internals
    # ------------------------------------------------------------------

    def tabInserted(self, index: int) -> None:  # noqa: N802 -- Qt override
        """Give the new tab its detach button (if more than one tab is docked)."""
        super().tabInserted(index)
        self._update_detach_buttons()

    def tabRemoved(self, index: int) -> None:  # noqa: N802 -- Qt override
        """Take the button from the last docked tab."""
        super().tabRemoved(index)
        self._update_detach_buttons()

    def changeEvent(self, event) -> None:  # noqa: ANN001, N802 -- Qt override
        """The tab widget's window became active: the current page is in use."""
        super().changeEvent(event)
        if event.type() == QEvent.Type.ActivationChange and self.isActiveWindow():
            page = self.currentWidget()
            if page is not None:
                self.pageActivated.emit(page)

    def eventFilter(self, watched, event) -> bool:  # noqa: ANN001, N802
        """Show the waiting windows once their owner is on screen."""
        if watched is self._watched_owner and event.type() == QEvent.Type.Show:
            QTimer.singleShot(0, self.show_pending_windows)
        return super().eventFilter(watched, event)

    def _update_detach_buttons(self) -> None:
        """One button per docked tab; none while a single tab is left."""
        bar = self.tabBar()
        allowed = self.count() > 1
        side = QTabBar.ButtonPosition.RightSide
        for index in range(self.count()):
            key = self.page_key(self.widget(index))
            button = bar.tabButton(index, side)
            wanted = allowed and key is not None
            if wanted and button is None:
                bar.setTabButton(index, side, self._make_detach_button(key))
            elif not wanted and button is not None:
                bar.setTabButton(index, side, None)
                button.deleteLater()

    def _make_detach_button(self, key: str) -> QToolButton:
        button = QToolButton(self.tabBar())
        button.setObjectName(DETACH_BUTTON_NAME)
        button.setProperty("tabKey", key)
        button.setAutoRaise(True)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setToolTip(_DETACH_TOOLTIP)
        button.setIcon(popout_icon(_foreground_color(self)))
        button.setIconSize(QSize(12, 12))
        button.setFixedSize(18, 18)
        button.clicked.connect(lambda _checked=False, k=key: self.detach_tab(k))
        return button

    def _attach_index(self, key: str) -> int:
        """Tab index that restores the page's original order."""
        position = self._order.index(key)
        return sum(
            1
            for other in self._order[:position]
            if other not in self._windows and self.indexOf(self._pages[other]) >= 0
        )

    def _window_caption(self, key: str) -> str:
        title = self._titles[key]
        return f"{title} — {self._window_title}" if self._window_title else title

    def _window_owner(self) -> QWidget:
        """The outermost ancestor (the main window, even from a floating dock)."""
        owner: QWidget = self
        while owner.parentWidget() is not None:
            owner = owner.parentWidget()
        return owner

    def _watch_owner(self, owner: QWidget) -> None:
        if self._watched_owner is owner:
            return
        if self._watched_owner is not None:
            self._watched_owner.removeEventFilter(self)
        self._watched_owner = owner
        owner.installEventFilter(self)

    def _on_current_changed(self, index: int) -> None:
        page = self.widget(index)
        if page is not None:
            self.pageActivated.emit(page)

    def _on_window_closed(self, key: str) -> None:
        self.attach_tab(key, select=True)

    def _on_window_activated(self, key: str) -> None:
        page = self._pages.get(key)
        if page is not None:
            self.pageActivated.emit(page)
