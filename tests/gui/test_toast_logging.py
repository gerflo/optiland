"""Every toast is also written to the Python log, without echoing back.

A user disabled the aperture stop surface; the viewer showed a one-off toast
and nothing else, so the reason for the missing rays was gone once the toast
had faded. Toasts now leave a log record. The GUI log handler, which turns
WARNING+ records into toasts, must ignore those records or every warning
toast would re-enter the log and loop forever.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest

TOAST_LOGGER = "optiland_gui.widgets.toast"


@pytest.fixture()
def toast_manager(qapp):
    from PySide6.QtWidgets import QMainWindow

    from optiland_gui.widgets.toast import ToastManager

    window = QMainWindow()
    window.resize(800, 600)
    manager = ToastManager(window)
    yield manager
    window.deleteLater()


@pytest.mark.parametrize(
    ("severity", "level"),
    [
        ("success", logging.INFO),
        ("info", logging.INFO),
        ("warning", logging.WARNING),
        ("error", logging.ERROR),
    ],
)
def test_toast_is_logged_at_matching_level(toast_manager, caplog, severity, level):
    with caplog.at_level(logging.INFO, logger=TOAST_LOGGER):
        toast_manager.notify("Hello", severity, sub_message="detail")

    records = [r for r in caplog.records if r.name == TOAST_LOGGER]
    assert len(records) == 1
    assert records[0].levelno == level
    assert records[0].getMessage() == "Hello (detail)"
    assert records[0].toast_origin is True


def test_toast_without_sub_message_logs_plain_text(toast_manager, caplog):
    with caplog.at_level(logging.INFO, logger=TOAST_LOGGER):
        toast_manager.notify("Saved", "success")

    records = [r for r in caplog.records if r.name == TOAST_LOGGER]
    assert [r.getMessage() for r in records] == ["Saved"]


def test_toast_born_from_a_log_record_is_not_logged_again(toast_manager, caplog):
    with caplog.at_level(logging.INFO, logger=TOAST_LOGGER):
        toast_manager.notify("From the log", "warning", log=False)

    assert not [r for r in caplog.records if r.name == TOAST_LOGGER]


def test_gui_log_handler_toasts_records_without_re_logging(qapp):
    from optiland_gui.utils.logging_handler import GuiLoggingHandler, _bridge

    manager = MagicMock()
    handler = GuiLoggingHandler(manager)
    logger = logging.getLogger("tests.toast_logging.plain")
    logger.propagate = False
    logger.setLevel(logging.WARNING)
    logger.addHandler(handler)
    try:
        logger.warning("plain warning")
    finally:
        logger.removeHandler(handler)
        _bridge.record_received.disconnect(handler._on_record)

    manager.notify.assert_called_once()
    args, kwargs = manager.notify.call_args
    assert args[0] == "plain warning"
    assert args[1] == "warning"
    assert kwargs["log"] is False


def test_gui_log_handler_ignores_toast_origin_records(qapp):
    """The loop guard: a record written by a toast must not become a toast."""
    from optiland_gui.utils.logging_handler import GuiLoggingHandler, _bridge

    manager = MagicMock()
    handler = GuiLoggingHandler(manager)
    logger = logging.getLogger("tests.toast_logging.echo")
    logger.propagate = False
    logger.setLevel(logging.WARNING)
    logger.addHandler(handler)
    try:
        logger.warning("echo", extra={"toast_origin": True})
    finally:
        logger.removeHandler(handler)
        _bridge.record_received.disconnect(handler._on_record)

    manager.notify.assert_not_called()


def test_toast_manager_and_log_handler_do_not_loop(qapp, caplog):
    """End to end: a warning toast with the GUI handler installed shows once."""
    from PySide6.QtWidgets import QMainWindow

    from optiland_gui.utils.logging_handler import GuiLoggingHandler, _bridge
    from optiland_gui.widgets.toast import ToastManager

    window = QMainWindow()
    window.resize(800, 600)
    manager = ToastManager(window)
    handler = GuiLoggingHandler(manager)
    toast_logger = logging.getLogger(TOAST_LOGGER)
    toast_logger.addHandler(handler)
    try:
        with caplog.at_level(logging.INFO, logger=TOAST_LOGGER):
            manager.notify("once", "warning")
    finally:
        toast_logger.removeHandler(handler)
        _bridge.record_received.disconnect(handler._on_record)
        window.deleteLater()

    assert [r.getMessage() for r in caplog.records if r.name == TOAST_LOGGER] == [
        "once"
    ]
    assert len(manager._stack) == 1


def test_configure_logging_writes_toasts_to_the_log_file(tmp_path, toast_manager):
    from optiland_gui.utils import logging_handler

    logging_handler.reset_logging()
    try:
        log_file = logging_handler.configure_logging(tmp_path)
        toast_manager.notify("On disk", "warning", sub_message="why")
        for handler in logging_handler._installed_handlers:
            handler.flush()
        text = log_file.read_text(encoding="utf-8")
    finally:
        logging_handler.reset_logging()

    assert log_file == tmp_path / "optiland_gui.log"
    assert "Log file:" in text
    assert "WARNING  optiland_gui.widgets.toast: On disk (why)" in text


def test_configure_logging_is_idempotent(tmp_path):
    from optiland_gui.utils import logging_handler

    logging_handler.reset_logging()
    try:
        first = logging_handler.configure_logging(tmp_path)
        second = logging_handler.configure_logging(tmp_path / "other")
        installed = list(logging_handler._installed_handlers)
    finally:
        logging_handler.reset_logging()

    assert first == second == tmp_path / "optiland_gui.log"
    assert len(installed) == 2  # one stream handler, one file handler
    assert logging_handler._installed_handlers == []
