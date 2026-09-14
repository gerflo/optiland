"""GUI logging handler for the Optiland GUI.

Routes Python ``logging`` records at WARNING level and above to the
:class:`~optiland_gui.widgets.toast.ToastManager` so that backend warnings
are surfaced in the UI without coupling ``optiland/`` to GUI code.

Author: Manuel Fragata Mendes, 2025
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtCore import QObject, Signal

_LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
_LOG_FILE_NAME = "optiland_gui.log"

# Handlers installed by configure_logging(); kept so tests can remove them.
_installed_handlers: list[logging.Handler] = []
_log_file: Path | None = None
_previous_root_level: int | None = None


class _LogSignalBridge(QObject):
    """Thread-safe bridge: emits a Qt signal from any thread."""

    record_received = Signal(int, str, str)  # levelno, message, name


_bridge = _LogSignalBridge()


class GuiLoggingHandler(logging.Handler):
    """A :class:`logging.Handler` that forwards records to :class:`ToastManager`.

    Instantiate once and pass a reference to the active
    :class:`~optiland_gui.widgets.toast.ToastManager`; the handler will
    call ``ToastManager.notify`` for every WARNING/ERROR/CRITICAL record.

    Args:
        toast_manager: The application's :class:`ToastManager` instance.
    """

    _LEVEL_TO_SEVERITY: dict[int, str] = {
        logging.WARNING: "warning",
        logging.ERROR: "error",
        logging.CRITICAL: "error",
    }

    def __init__(self, toast_manager: object) -> None:
        super().__init__(level=logging.WARNING)
        self._toast_manager = toast_manager
        # Connect the bridge signal on the main thread so Qt updates are safe.
        _bridge.record_received.connect(self._on_record)

    def emit(self, record: logging.LogRecord) -> None:
        """Forward *record* to the toast manager via a Qt signal."""
        if getattr(record, "toast_origin", False):
            # Written by ToastManager.notify for a toast that is already on
            # screen; echoing it back would show it twice and loop forever.
            return
        try:
            msg = self.format(record)
            _bridge.record_received.emit(record.levelno, msg, record.name)
        except Exception:  # noqa: BLE001
            self.handleError(record)

    def _on_record(self, levelno: int, message: str, logger_name: str) -> None:
        severity = self._LEVEL_TO_SEVERITY.get(levelno, "warning")
        # Truncate very long messages
        display_msg = message if len(message) <= 120 else message[:117] + "…"
        # The record is already in the log; do not write it a second time.
        self._toast_manager.notify(
            display_msg, severity, sub_message=logger_name, log=False
        )


def install(toast_manager: object, root_logger_name: str = "") -> GuiLoggingHandler:
    """Install a :class:`GuiLoggingHandler` on the named logger.

    Args:
        toast_manager: The active :class:`~optiland_gui.widgets.toast.ToastManager`.
        root_logger_name: Logger name to attach to (default: root logger).

    Returns:
        The installed handler (keep a reference to avoid garbage collection).
    """
    handler = GuiLoggingHandler(toast_manager)
    logging.getLogger(root_logger_name).addHandler(handler)
    return handler


def default_log_dir() -> Path:
    """Return the log folder next to the catalog cache in the app data dir."""
    from PySide6.QtCore import QStandardPaths

    data_dir = QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)
    return Path(data_dir) / "logs"


def configure_logging(
    log_dir: Path | None = None, level: int = logging.INFO
) -> Path | None:
    """Write the application log to stderr and to a rotating file.

    The GUI shows WARNING+ records as toasts and every toast writes a log
    record, so this is where both end up on disk. A second call is a no-op.

    Args:
        log_dir: Folder for the log file. Defaults to ``logs`` in the
            application data directory.
        level: Root logger level; INFO also records success/info toasts.

    Returns:
        The log file path, or ``None`` if the file could not be opened.
    """
    global _log_file, _previous_root_level
    if _installed_handlers:
        return _log_file

    root = logging.getLogger()
    _previous_root_level = root.level
    if root.level == logging.NOTSET or root.level > level:
        root.setLevel(level)
    formatter = logging.Formatter(_LOG_FORMAT)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    root.addHandler(stream_handler)
    _installed_handlers.append(stream_handler)

    log_dir = default_log_dir() if log_dir is None else Path(log_dir)
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_dir / _LOG_FILE_NAME,
            maxBytes=1_000_000,
            backupCount=3,
            encoding="utf-8",
        )
    except OSError:
        logging.getLogger(__name__).warning(
            "Could not open the log file in %s; logging to stderr only.", log_dir
        )
        _log_file = None
    else:
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
        _installed_handlers.append(file_handler)
        _log_file = log_dir / _LOG_FILE_NAME
        logging.getLogger(__name__).info("Log file: %s", _log_file)
    return _log_file


def reset_logging() -> None:
    """Remove the handlers installed by :func:`configure_logging` (tests)."""
    global _log_file, _previous_root_level
    root = logging.getLogger()
    for handler in _installed_handlers:
        root.removeHandler(handler)
        handler.close()
    _installed_handlers.clear()
    if _previous_root_level is not None:
        root.setLevel(_previous_root_level)
        _previous_root_level = None
    _log_file = None
