"""Tests for the PyInstaller build recipe ``optiland.spec``."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("PyInstaller")
pytest.importorskip("debugpy")

import PyInstaller.utils.hooks as pyi_hooks  # noqa: E402
from matplotlib.backend_bases import (  # noqa: E402
    FigureCanvasBase,
    get_registered_canvas_class,
)

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "optiland.spec"


def _spec_analysis_kwargs(monkeypatch: pytest.MonkeyPatch) -> dict:
    """Execute the spec with stubbed PyInstaller targets.

    The package-wide ``collect_*`` scans are stubbed out as well, so only the
    entries the spec lists itself end up in the recorded arguments.

    Returns:
        The keyword arguments the spec passes to ``Analysis``.
    """
    monkeypatch.setattr(pyi_hooks, "collect_submodules", lambda *a, **k: [])
    monkeypatch.setattr(pyi_hooks, "collect_data_files", lambda *a, **k: [])
    monkeypatch.delenv("OPTILAND_ONEFILE", raising=False)

    captured: dict = {}

    def analysis(scripts, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(pure=[], scripts=[], binaries=[], datas=[])

    def target(*args, **kwargs):
        return None

    namespace = {
        "__name__": "optiland_spec",
        "SPECPATH": str(ROOT),
        "Analysis": analysis,
        "PYZ": target,
        "EXE": target,
        "COLLECT": target,
    }
    code = compile(SPEC.read_text(encoding="utf-8"), str(SPEC), "exec")
    exec(code, namespace)
    return captured


def test_spec_bundles_every_savefig_backend(monkeypatch):
    """The frozen app can write every format the toolbar's save dialog offers.

    Regression: saving a plot as PDF from the packaged Optiland.exe failed with
    "No module named 'matplotlib.backends.backend_pdf'".
    """
    hiddenimports = set(_spec_analysis_kwargs(monkeypatch)["hiddenimports"])

    assert "matplotlib.backends.backend_pdf" in hiddenimports
    required = {
        get_registered_canvas_class(fmt).__module__
        for fmt in FigureCanvasBase.get_supported_filetypes()
    }
    assert required <= hiddenimports, sorted(required - hiddenimports)


def test_spec_leaves_torch_out_by_default(monkeypatch):
    """The GUI never uses the PyTorch backend, so the build does not carry it.

    torch was 310 MB and about 2000 files of the packaged app and took about
    2 s of every start (much more on a cold start); ``optiland.backend``
    falls back to NumPy when it is missing.
    """
    monkeypatch.delenv("OPTILAND_WITH_TORCH", raising=False)

    assert "torch" in _spec_analysis_kwargs(monkeypatch)["excludes"]


def test_spec_keeps_torch_on_request(monkeypatch):
    """``OPTILAND_WITH_TORCH=1`` (``make_windows_bin.cmd --with-torch``)."""
    monkeypatch.setenv("OPTILAND_WITH_TORCH", "1")

    assert "torch" not in _spec_analysis_kwargs(monkeypatch)["excludes"]
