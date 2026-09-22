"""The services package must not import Qt unless a Qt-bound service is used.

Regression test for the lazy ``optiland_gui.services.__init__``: the Optomal
sidecar imports ``SurfaceService`` / ``SystemService`` in an environment
without PySide6. Runs in a subprocess so the parent's Qt import state does
not matter.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap

import pytest

_BLOCK_QT = """
import sys
sys.modules["PySide6"] = None  # any `import PySide6...` now raises ImportError
"""


def _run(code: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(_BLOCK_QT) + textwrap.dedent(code)],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


@pytest.mark.parametrize(
    "module",
    [
        "optiland_gui.services.surface_service",
        "optiland_gui.services.system_service",
        "optiland_gui.registry",
    ],
)
def test_qt_free_modules_import_without_pyside6(module: str) -> None:
    result = _run(f"import {module}\nprint('ok')")
    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout


def test_package_attributes_resolve_lazily() -> None:
    code = """
    import optiland_gui.services as services
    assert "SurfaceService" not in vars(services)  # not imported eagerly
    from optiland_gui.services import SurfaceService, SystemService
    assert SurfaceService.__name__ == "SurfaceService"
    assert "SurfaceService" in vars(services)  # cached after first access
    assert "SurfaceService" in dir(services)
    try:
        services.NoSuchService
    except AttributeError:
        print("attribute-error-ok")
    """
    result = _run(code)
    assert result.returncode == 0, result.stderr
    assert "attribute-error-ok" in result.stdout


def test_qt_bound_service_still_needs_pyside6() -> None:
    result = _run("from optiland_gui.services import OptimizationService")
    assert result.returncode != 0
    assert "PySide6" in result.stderr
