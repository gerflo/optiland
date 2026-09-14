"""Regression tests: disabling the aperture stop surface is refused.

Found via a real user file: the pinhole mirror ("Lochspiegel") was the
aperture stop. Disabling it spliced the stop out of the traced optic,
Optiland raised "No stop surface found", the viewer turned that into a
one-off toast and drew the layout without rays, and nothing was logged.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest

from optiland_gui.optiland_connector import OptilandConnector

CONNECTOR_LOGGER = "optiland_gui.optiland_connector"


@pytest.fixture()
def connector(qapp, monkeypatch):
    monkeypatch.setattr(
        "optiland_gui.optiland_connector.CatalogService",
        lambda connector: MagicMock(),
    )
    monkeypatch.setattr(
        "optiland_gui.optiland_connector.MaterialCatalogService",
        lambda connector: MagicMock(),
    )
    connector = OptilandConnector()
    connector.add_surface()  # rows: 0 object, 1 stop, 2 plain surface, 3 image
    connector.mark_current_state_clean()
    return connector


def test_default_system_has_its_stop_on_row_one(connector):
    assert connector.get_stop_surface_index() == 1


def test_disabling_the_stop_surface_is_refused_with_a_warning_toast(connector):
    connector.toast_manager = MagicMock()

    assert connector.set_surface_disabled(1, True) is False

    assert connector.get_disabled_surface_indices() == set()
    assert connector.has_unsaved_changes() is False
    connector.toast_manager.notify.assert_called_once()
    message, severity = connector.toast_manager.notify.call_args[0][:2]
    assert severity == "warning"
    assert message == (
        "Surface 1 is the aperture stop. Move the stop to another surface "
        "before disabling it."
    )


def test_refusal_is_logged_when_no_toast_manager_is_attached(connector, caplog):
    with caplog.at_level(logging.WARNING, logger=CONNECTOR_LOGGER):
        assert connector.set_surface_disabled(1, True) is False

    messages = [r.getMessage() for r in caplog.records if r.name == CONNECTOR_LOGGER]
    assert messages == [
        "Surface 1 is the aperture stop. Move the stop to another surface "
        "before disabling it."
    ]


def test_disabling_an_element_that_contains_the_stop_is_refused(connector):
    connector.toast_manager = MagicMock()

    assert connector.set_surfaces_disabled([1, 2], True) is False

    assert connector.get_disabled_surface_indices() == set()
    message = connector.toast_manager.notify.call_args[0][0]
    assert message == (
        "Element not disabled: surface 1 is the aperture stop. Move the stop "
        "to another surface first."
    )


def test_refusal_adds_no_undo_step(connector):
    connector.toast_manager = MagicMock()
    assert connector.set_surface_disabled(2, True) is True
    assert connector.set_surface_disabled(1, True) is False

    connector.undo()

    assert connector.get_disabled_surface_indices() == set()


def test_other_surfaces_can_still_be_disabled_and_the_trace_keeps_its_stop(
    connector,
):
    assert connector.set_surface_disabled(2, True) is True

    assert connector.get_disabled_surface_indices() == {2}
    assert connector.get_effective_optic().surfaces.stop_index == 1


def test_enabling_is_never_refused(connector):
    connector.toast_manager = MagicMock()
    connector.set_surface_disabled(2, True)
    connector.set_stop_surface(2)  # the disabled row becomes the stop

    assert connector.set_surface_disabled(2, False) is True

    assert connector.get_disabled_surface_indices() == set()
    connector.toast_manager.notify.assert_not_called()


def test_stop_can_be_moved_and_the_old_stop_disabled(connector):
    """The workflow the warning asks for: move the stop, then disable."""
    connector.toast_manager = MagicMock()
    connector.set_stop_surface(2)

    assert connector.set_surface_disabled(1, True) is True

    assert connector.get_disabled_surface_indices() == {1}
    assert connector.get_effective_optic().surfaces.stop_index == 1
    connector.toast_manager.notify.assert_not_called()
