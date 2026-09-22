"""The 2D visualization stack must import and draw without VTK installed.

VTK is only needed for the 3D viewer. Keeping ``import vtk`` at function
level lets Matplotlib-only consumers (the Optomal sidecar, headless CI
images) use ``OpticViewer`` and the ``OpticalSystem`` components without
the VTK wheel. The check runs in a subprocess with ``vtk`` blocked in
``sys.modules`` so an accidental module-level import fails loudly.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap

MODULES = [
    "optiland.visualization.system.utils",
    "optiland.visualization.system.surface",
    "optiland.visualization.system.rays",
    "optiland.visualization.system.lens",
    "optiland.visualization.system.mirror",
    "optiland.visualization.system.system",
    "optiland.visualization.system.optic_viewer",
    "optiland.visualization.system.optic_viewer_3d",
]

SCRIPT = textwrap.dedent(
    """
    import importlib
    import sys

    sys.modules["vtk"] = None  # any `import vtk` now raises ImportError
    for name in {modules!r}:
        importlib.import_module(name)

    import matplotlib
    matplotlib.use("Agg")
    from optiland.samples.objectives import CookeTriplet
    from optiland.visualization.system.optic_viewer import OpticViewer

    fig, ax, _ = OpticViewer(CookeTriplet()).view(show=False)
    assert len(ax.lines) > 0 and len(ax.patches) > 0
    print("OK")
    """
).format(modules=MODULES)


def test_2d_visualization_imports_and_draws_without_vtk() -> None:
    result = subprocess.run(
        [sys.executable, "-c", SCRIPT],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout


def test_3d_viewer_still_needs_vtk_only_when_used() -> None:
    script = textwrap.dedent(
        """
        import sys
        sys.modules["vtk"] = None
        from optiland.samples.objectives import CookeTriplet
        from optiland.visualization.system.optic_viewer_3d import OpticViewer3D
        try:
            OpticViewer3D(CookeTriplet())
        except ImportError:
            print("IMPORT_ERROR")
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "IMPORT_ERROR" in result.stdout
