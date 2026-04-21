"""Import validated WinLens ``glassplus`` records into Optiland locally."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import yaml

from optiland.materials.material import Material
from optiland.materials.material_file import MaterialFile
from optiland.materials.winlens_glassplus import iter_glassplus_records

_FORMULA_WAVELENGTH_RANGES = {
    ("schott", "formula 2"): "0.35 2.5",
    ("ohara", "formula 2"): "0.34 2.4",
    ("hoya", "formula 3"): "0.36501 1.01398",
    ("hikari", "formula 3"): "0.4 0.7",
    # Validated against existing Sumita glasses. We use the conservative
    # shared window until the exact WinLens wavelength-range fields are decoded.
    ("sumita", "formula 3"): "0.4 1.55",
    # Corning/Pilkington formula-3 blocks are internally validated via their
    # nd/Vd-like part codes; use the same conservative optical-glass window.
    ("corning", "formula 3"): "0.4 1.55",
    ("pilkington", "formula 3"): "0.4 1.55",
    ("chengdu", "formula 3"): "0.4 1.55",
}


@dataclass(slots=True)
class WinLensMaterialImportResult:
    imported_count: int
    skipped_existing: int
    skipped_unsupported: int
    catalog_csv: str


def import_validated_winlens_materials(root_path: str | Path) -> WinLensMaterialImportResult:
    """Import locally decodable WinLens materials into Optiland's local catalog."""
    root = Path(root_path)
    source_files = [
        root / "WinLens3DBasic" / "stglassplus.dat",
        root / "WinLens3DBasic" / "spglassplus.dat",
    ]
    database_root = Path(Material._filename).parent
    data_root = database_root / "data-nk" / "glass" / "winlens"
    csv_path = database_root / "catalog_nk_winlens.csv"

    existing_rows = _load_existing_rows(csv_path)
    original_existing_count = len(existing_rows)
    existing_rows = _prune_rows_shadowed_by_base_catalog(existing_rows, data_root)
    existing_keys = {
        (
            str(row.get("reference", "")).casefold(),
            str(row.get("filename_no_ext", "")).casefold(),
        )
        for row in existing_rows
    }

    imported_rows: list[dict[str, object]] = []
    imported_count = 0
    skipped_existing = 0
    skipped_unsupported = 0

    for source_file in source_files:
        if not source_file.is_file():
            continue
        for record in iter_glassplus_records(source_file):
            reference = str(record.reference or "").strip()
            key = (reference.casefold(), record.name.casefold())
            if not reference:
                skipped_unsupported += 1
                continue
            if Material._catalog_exact_targets(record.name, reference):
                skipped_existing += 1
                continue
            if Material._catalog_has_exact_manufacturer_material(record.name, reference):
                skipped_existing += 1
                continue
            if key in existing_keys:
                skipped_existing += 1
                continue

            output_path = _material_output_path(data_root, reference, record.name)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            payload = _build_yaml_payload(record)
            with output_path.open("w", encoding="utf-8") as handle:
                yaml.safe_dump(payload, handle, sort_keys=False, allow_unicode=False)

            specs = _compute_specs(output_path)
            row = {
                "group": "glass",
                "category_name": "WinLens",
                "category_name_full": f"WinLens imported {reference}",
                "reference": reference,
                "name": record.name,
                "filename": output_path.relative_to(database_root / "data-nk").as_posix(),
                "min_wavelength": specs["min_wavelength"],
                "max_wavelength": specs["max_wavelength"],
                "filename_no_ext": record.name,
            }
            imported_rows.append(row)
            existing_keys.add(key)
            imported_count += 1

    if imported_rows or len(existing_rows) != original_existing_count:
        all_rows = existing_rows + imported_rows
        pd.DataFrame(all_rows).to_csv(csv_path, index=False)
        Material._df = None

    return WinLensMaterialImportResult(
        imported_count=imported_count,
        skipped_existing=skipped_existing,
        skipped_unsupported=skipped_unsupported,
        catalog_csv=str(csv_path),
    )


def _load_existing_rows(csv_path: Path) -> list[dict[str, object]]:
    if not csv_path.is_file():
        return []
    return pd.read_csv(csv_path).to_dict(orient="records")


def _prune_rows_shadowed_by_base_catalog(
    rows: list[dict[str, object]],
    data_root: Path,
) -> list[dict[str, object]]:
    kept_rows: list[dict[str, object]] = []
    data_nk_root = data_root.parent.parent
    for row in rows:
        reference = str(row.get("reference", "")).strip()
        name = str(row.get("filename_no_ext") or row.get("name") or "").strip()
        if reference and name and Material._catalog_has_exact_manufacturer_material(name, reference):
            filename = str(row.get("filename", "")).strip()
            if filename:
                candidate = data_nk_root / Path(filename)
                try:
                    if candidate.is_file():
                        candidate.unlink()
                except OSError:
                    pass
            continue
        kept_rows.append(row)
    return kept_rows


def _material_output_path(data_root: Path, reference: str, name: str) -> Path:
    safe_reference = reference.strip().casefold().replace(" ", "_")
    safe_name = name.replace("/", "_")
    return data_root / safe_reference / f"{safe_name}.yml"


def _build_yaml_payload(record) -> dict[str, object]:  # noqa: ANN001
    reference_key = str(record.reference or "").casefold()
    wavelength_range = _FORMULA_WAVELENGTH_RANGES[(reference_key, record.formula_type)]
    return {
        "REFERENCES": (
            f"Imported from WinLens 2002 glassplus ({Path(record.source_path).name}) "
            f"for {record.name} ({record.reference})."
        ),
        "COMMENTS": "Locally imported from WinLens glassplus after coefficient validation.",
        "DATA": [
            {
                "type": record.formula_type,
                "wavelength_range": wavelength_range,
                "coefficients": record.coefficient_string(),
            }
        ],
    }


def _compute_specs(output_path: Path) -> dict[str, float]:
    material = MaterialFile(str(output_path))
    nd = material.n(0.5875618).item()
    vd = material.abbe().item()
    data = yaml.safe_load(output_path.read_text(encoding="utf-8"))
    data["SPECS"] = {
        "n_is_absolute": False,
        "wavelength_is_vacuum": False,
        "temperature": "20.0 °C",
        "nd": round(nd, 6),
        "Vd": round(vd, 6),
        "glass_status": "winlens-imported",
    }
    with output_path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(data, handle, sort_keys=False, allow_unicode=False)

    wave_min, wave_max = [
        float(value)
        for value in str(data["DATA"][0]["wavelength_range"]).split()
    ]
    return {"min_wavelength": wave_min, "max_wavelength": wave_max}
