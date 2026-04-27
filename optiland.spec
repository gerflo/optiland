# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build recipe for the Optiland GUI on Windows."""

from __future__ import annotations

import os
from pathlib import Path

import debugpy
from PyInstaller.utils.hooks import collect_data_files, collect_submodules


ROOT = Path(SPECPATH).resolve()
ONEFILE = os.environ.get("OPTILAND_ONEFILE", "").lower() in {
    "1",
    "true",
    "yes",
    "on",
}


datas = []
binaries = []
hiddenimports = []

DEBUGPY_ROOT = Path(debugpy.__file__).resolve().parent

datas += collect_data_files("optiland", include_py_files=False)
datas += collect_data_files("optiland_gui.resources", include_py_files=False)
datas += [
    (
        str(ROOT / "optiland" / "colorimetry" / "colorimetric_data_1nm.json"),
        "optiland/colorimetry",
    ),
]
datas += collect_data_files("debugpy", include_py_files=True)
datas += [(str(DEBUGPY_ROOT / "_vendored"), "debugpy/_vendored")]
hiddenimports += collect_submodules("vtkmodules")
hiddenimports += collect_submodules("optiland_gui")
hiddenimports += collect_submodules("optiland")
hiddenimports += collect_submodules("qtconsole")
hiddenimports += collect_submodules("ipykernel")
hiddenimports += collect_submodules("debugpy")

analysis = Analysis(
    [str(ROOT / "tools" / "optiland_gui_entry.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "dask",
        "matplotlib.tests",
        "PySide6.scripts",
        "scipy._lib.array_api_compat.dask",
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(analysis.pure)

exe_kwargs = {
    "name": "Optiland",
    "debug": False,
    "bootloader_ignore_signals": False,
    "strip": False,
    "upx": True,
    "console": False,
    "disable_windowed_traceback": False,
    "argv_emulation": False,
    "target_arch": None,
    "codesign_identity": None,
    "entitlements_file": None,
    "icon": str(ROOT / "optiland_gui" / "resources" / "icons" / "optiland_icon.png"),
}

if ONEFILE:
    exe = EXE(
        pyz,
        analysis.scripts,
        analysis.binaries,
        analysis.datas,
        [],
        **exe_kwargs,
    )
else:
    exe = EXE(
        pyz,
        analysis.scripts,
        [],
        exclude_binaries=True,
        **exe_kwargs,
    )
    coll = COLLECT(
        exe,
        analysis.binaries,
        analysis.datas,
        strip=False,
        upx=True,
        upx_exclude=[],
        name="Optiland",
    )
