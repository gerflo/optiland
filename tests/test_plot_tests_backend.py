"""Test modules that open plots select a non-interactive backend (O17).

``OpticViewer.view()``, ``Optic.draw()`` and the analysis ``view()`` methods
call ``plt.show()`` by default. Under an interactive default backend (QtAgg
on a Windows desktop) that blocks until the window is closed, so the modules
below hung when run on their own. Each selects Agg on import, as the other
plotting test modules do.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import matplotlib
import pytest

TESTS_DIR = Path(__file__).parent

PLOTTING_MODULES = [
    "analysis/test_jones_pupil.py",
    "nonsequential/test_nsq_visualization.py",
    "test_extended_sources.py",
    "test_folded_paraxial_hardening.py",
    "test_mtf_vs_field.py",
    "test_through_focus_mtf.py",
    "visualization/system/test_optic_viewer_projection.py",
    "visualization/system/test_surface2d_offset_aperture.py",
    "visualization/test_interaction.py",
    "visualization/test_themes.py",
]


@pytest.mark.parametrize("relative_path", PLOTTING_MODULES)
def test_module_selects_agg_on_import(relative_path):
    """Importing the module switches matplotlib to Agg (O17)."""
    path = TESTS_DIR / relative_path
    package = ".".join(("tests", *path.relative_to(TESTS_DIR).parent.parts))
    spec = importlib.util.spec_from_file_location(
        f"{package}._o17_probe_{path.stem}", path
    )
    module = importlib.util.module_from_spec(spec)

    previous = matplotlib.get_backend()
    # A fresh copy of the module runs its import-time code again; the
    # "template" backend is a non-interactive sentinel it must replace.
    matplotlib.use("template")
    try:
        spec.loader.exec_module(module)
        assert matplotlib.get_backend().lower() == "agg"
    finally:
        matplotlib.use(previous)
