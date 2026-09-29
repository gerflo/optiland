"""Entry point for launching the Optiland GUI application.

This module initializes the :class:`~PySide6.QtWidgets.QApplication` and the
:class:`~optiland_gui.main_window.MainWindow`, starting the event loop to run
the graphical user interface for Optiland.

Authors:
    Manuel Fragata Mendes, 2025
"""

from __future__ import annotations

import contextlib
import ctypes
import os
import sys

from PySide6.QtCore import QLocale, QSize, Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QApplication, QSplashScreen

from .config import APPLICATION_NAME, OPTILAND_ICON_PATH, ORGANIZATION_NAME
from .resources import resources_rc  # noqa: F401
from .utils import logging_handler as _log_handler


def _patch_matplotlib_show_event() -> None:
    """Guard against a deleted QWindow in matplotlib's showEvent on PySide6 >= 6.6.

    windowHandle() can return a Python wrapper around an already-destroyed C++
    QWindow during app startup, causing installEventFilter to raise RuntimeError.
    Suppressing it is safe: the only consequence is that DPI changes via screen
    moves won't be detected until the next repaint.
    """
    try:
        from matplotlib.backends.backend_qt import FigureCanvasQT

        _orig = FigureCanvasQT.showEvent

        def _safe_show_event(self, event):
            with contextlib.suppress(RuntimeError):
                _orig(self, event)

        FigureCanvasQT.showEvent = _safe_show_event
    except Exception:
        pass


def _startup_file(argv: list[str]) -> str | None:
    """The file named on the command line, as an absolute path, or ``None``.

    Explorer's "Open with" (and a file association) start the application
    with the file as its only argument. Options such as Qt's ``-style`` are
    skipped; of the other arguments, the first that exists is the file, else
    the first at all, so that a wrong path is reported rather than ignored.
    """
    candidates = [arg for arg in argv[1:] if not arg.startswith("-")]
    for arg in candidates:
        if os.path.isfile(arg):
            return os.path.abspath(arg)
    return os.path.abspath(candidates[0]) if candidates else None


def main() -> None:
    """Application entry point."""
    _patch_matplotlib_show_event()

    if sys.platform == "win32":
        myappid = f"{ORGANIZATION_NAME}.{APPLICATION_NAME}.1.0"
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)

    # Force XCB (X11) on Linux to avoid BadWindow / X_ConfigureWindow crashes
    # caused by incompatibility between the VTK/OpenGL render pipeline and the
    # Qt Wayland backend.  This must be set before QApplication is created.
    if sys.platform.startswith("linux"):
        os.environ["QT_QPA_PLATFORM"] = "xcb"

    app = QApplication(sys.argv)
    # Log to stderr and to a rotating file in the app data folder. Toasts
    # write to the log as well, so what the user saw on screen is on record.
    _log_handler.configure_logging()
    # A crash inside Qt kills the process without a log record; this at
    # least leaves the Python stack of the moment behind.
    _log_handler.enable_crash_log()
    app.setWindowIcon(QIcon(OPTILAND_ICON_PATH))
    QLocale.setDefault(QLocale(QLocale.Language.English, QLocale.Country.UnitedStates))

    original_pixmap = QPixmap(":/images/logo.png")
    desired_size = QSize(700, 400)
    scaled_pixmap = original_pixmap.scaled(
        desired_size, Qt.KeepAspectRatio, Qt.SmoothTransformation
    )

    # Create and show splash screen
    splash = QSplashScreen(scaled_pixmap)
    splash.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint)
    splash.setEnabled(False)
    splash.showMessage(
        "<h3>Initializing application...</h3>",
        Qt.AlignBottom | Qt.AlignHCenter,
        Qt.white,
    )
    splash.show()
    app.processEvents()

    # The main window pulls in Optiland, VTK and the analysis stack, which
    # takes seconds (far longer on a cold start of the packaged app); it is
    # imported only now so that the splash screen is up in the meantime.
    from .main_window import MainWindow

    # Initialize the main window while splash is visible.  The time taken
    # here is the actual loading time the user experiences.
    window = MainWindow()
    window.show_at_start()

    # Close the splash screen once the main window is ready.
    splash.finish(window)

    # Explorer's "Open with" hands the file over on the command line.
    startup_file = _startup_file(sys.argv)
    if startup_file is not None:
        window.open_file_from_command_line(startup_file)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
