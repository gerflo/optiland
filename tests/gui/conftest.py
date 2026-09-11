"""Shared fixtures for optiland_gui tests."""

from __future__ import annotations

import pytest

import optiland.backend as be


@pytest.fixture(scope="session")
def qapp():
    """Session-scoped QApplication required by PySide6 signal/thread machinery."""
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture()
def minimal_optic():
    """A 4-surface singlet (object, lens front, lens back/stop, image).

    EPD = 10 mm, single on-axis angle field (y=0°), wavelength 0.55 µm primary.
    """
    from optiland.optic import Optic

    optic = Optic()
    optic.surfaces.add(index=0, radius=be.inf, thickness=be.inf)
    optic.surfaces.add(
        index=1,
        radius=50.0,
        thickness=5.0,
        material="N-BK7",
        is_stop=False,
    )
    optic.surfaces.add(
        index=2,
        radius=-50.0,
        thickness=45.0,
        is_stop=True,
    )
    optic.surfaces.add(index=3, radius=be.inf, thickness=0.0)

    optic.set_aperture(aperture_type="EPD", value=10.0)
    optic.fields.set_type("angle")
    optic.fields.add(y=0.0)
    optic.wavelengths.add(value=0.55, is_primary=True)
    optic.updater.update()
    return optic


class _FakeClipboard:
    """In-process stand-in for QClipboard.

    The GUI code only uses ``text``/``setText``/``clear``. Going through the
    real OS clipboard makes copy/paste tests fail whenever anything else on
    the machine (a second test run, the running app, a clipboard manager)
    touches the clipboard in between.
    """

    def __init__(self) -> None:
        self._text = ""

    def text(self, *_args) -> str:
        return self._text

    def setText(self, text, *_args) -> None:  # noqa: N802, ANN001
        self._text = str(text)

    def clear(self, *_args) -> None:
        self._text = ""

    def ownsClipboard(self) -> bool:  # noqa: N802
        return True


@pytest.fixture(autouse=True)
def isolated_clipboard(monkeypatch):
    """Route ``QApplication.clipboard()`` to a per-test in-memory clipboard."""
    from PySide6.QtGui import QGuiApplication

    fake = _FakeClipboard()
    monkeypatch.setattr(QGuiApplication, "clipboard", staticmethod(lambda: fake))
    return fake
