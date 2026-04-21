from __future__ import annotations

import shutil
from pathlib import Path

from optiland.materials import Material, import_validated_winlens_materials


def _workspace_tmp_dir() -> Path:
    path = Path(".tmp_testdata") / "winlens_material_import"
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)
    path.mkdir(parents=True, exist_ok=True)
    return path


def test_import_validated_winlens_materials_adds_new_schott_glass() -> None:
    tmp_path = _workspace_tmp_dir()
    database_root = Path(Material._filename).parent
    local_csv = database_root / "catalog_nk_winlens.csv"
    local_glass_root = database_root / "data-nk" / "glass" / "winlens"

    backup_csv = None
    if local_csv.exists():
        backup_csv = local_csv.read_bytes()
    backup_glass_root = None
    if local_glass_root.exists():
        backup_glass_root = tmp_path / "glass_winlens_backup"
        shutil.copytree(local_glass_root, backup_glass_root)

    Material._df = None
    try:
        if local_csv.exists():
            local_csv.unlink()
        if local_glass_root.exists():
            shutil.rmtree(local_glass_root)

        root = Path.cwd().parent / "WinLens Library 2002"
        result = import_validated_winlens_materials(root)

        assert result.imported_count > 0

        imported = Material("BAF50", reference="Schott", warn_on_inexact=False)
        assert imported.material_data["reference"] == "Schott"
        assert imported.material_data["filename"].startswith("glass/winlens/schott/")
    finally:
        Material._df = None
        if local_csv.exists():
            local_csv.unlink()
        if local_glass_root.exists():
            shutil.rmtree(local_glass_root)
        if backup_csv is not None:
            local_csv.write_bytes(backup_csv)
        if backup_glass_root is not None and backup_glass_root.exists():
            shutil.copytree(backup_glass_root, local_glass_root)
        shutil.rmtree(tmp_path, ignore_errors=True)


def test_import_validated_winlens_materials_ignores_empty_existing_csv() -> None:
    tmp_path = _workspace_tmp_dir()
    database_root = Path(Material._filename).parent
    local_csv = database_root / "catalog_nk_winlens.csv"
    local_glass_root = database_root / "data-nk" / "glass" / "winlens"

    backup_csv = None
    if local_csv.exists():
        backup_csv = local_csv.read_bytes()
    backup_glass_root = None
    if local_glass_root.exists():
        backup_glass_root = tmp_path / "glass_winlens_backup"
        shutil.copytree(local_glass_root, backup_glass_root)

    Material._df = None
    try:
        local_csv.write_text("\n", encoding="utf-8")
        if local_glass_root.exists():
            shutil.rmtree(local_glass_root)

        root = Path.cwd().parent / "WinLens Library 2002"
        result = import_validated_winlens_materials(root)

        assert result.imported_count >= 0
        imported = Material("BAF50", reference="Schott", warn_on_inexact=False)
        assert imported.material_data["reference"] == "Schott"
    finally:
        Material._df = None
        if local_csv.exists():
            local_csv.unlink()
        if local_glass_root.exists():
            shutil.rmtree(local_glass_root)
        if backup_csv is not None:
            local_csv.write_bytes(backup_csv)
        if backup_glass_root is not None and backup_glass_root.exists():
            shutil.copytree(backup_glass_root, local_glass_root)
        shutil.rmtree(tmp_path, ignore_errors=True)
