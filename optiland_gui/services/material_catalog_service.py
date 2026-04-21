"""Material database browsing and import helpers for the GUI."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from optiland.materials import Material, import_validated_winlens_materials


@dataclass(slots=True)
class MaterialCatalogImportResult:
    imported_count: int
    skipped_existing: int
    skipped_unsupported: int
    catalog_csv: str
    message: str


class MaterialCatalogService:
    """Provide material database search and WinLens import helpers."""

    def __init__(self, connector: object) -> None:
        self._connector = connector

    def search(self, query: dict | None = None) -> list[dict]:
        query = query or {}
        df = Material._load_dataframe().copy()
        if df.empty:
            return []

        for column in (
            "group",
            "category_name",
            "category_name_full",
            "reference",
            "name",
            "filename",
            "filename_no_ext",
        ):
            if column not in df:
                df[column] = ""
            df[column] = df[column].fillna("")

        df["source"] = df["filename"].apply(self._classify_source)

        text = str(query.get("text", "")).strip().casefold()
        if text:
            text_mask = (
                df["reference"].str.casefold().str.contains(text, regex=False)
                | df["name"].str.casefold().str.contains(text, regex=False)
                | df["filename_no_ext"].str.casefold().str.contains(text, regex=False)
                | df["category_name"].str.casefold().str.contains(text, regex=False)
                | df["category_name_full"].str.casefold().str.contains(text, regex=False)
                | df["source"].str.casefold().str.contains(text, regex=False)
            )
            df = df[text_mask]

        for field, column in (
            ("reference", "reference"),
            ("name", "name"),
            ("category", "category_name"),
            ("source", "source"),
        ):
            value = str(query.get(field, "")).strip().casefold()
            if value:
                df = df[df[column].str.casefold().str.contains(value, regex=False)]

        min_wavelength = self._parse_float(query.get("min_wavelength"))
        max_wavelength = self._parse_float(query.get("max_wavelength"))
        if min_wavelength is not None:
            df = df[df["max_wavelength"] >= min_wavelength]
        if max_wavelength is not None:
            df = df[df["min_wavelength"] <= max_wavelength]

        df = df.sort_values(
            by=["reference", "filename_no_ext", "filename"],
            kind="stable",
        )
        results: list[dict] = []
        for row in df.to_dict(orient="records"):
            material_id = self._material_id(row)
            results.append(
                {
                    "material_id": material_id,
                    "reference": row.get("reference", ""),
                    "name": row.get("filename_no_ext") or row.get("name", ""),
                    "display_name": row.get("name", ""),
                    "group": row.get("group", ""),
                    "category": row.get("category_name", ""),
                    "category_full": row.get("category_name_full", ""),
                    "source": row.get("source", ""),
                    "filename": row.get("filename", ""),
                    "absolute_filename": self._resolve_material_path(row.get("filename", "")),
                    "min_wavelength": row.get("min_wavelength"),
                    "max_wavelength": row.get("max_wavelength"),
                    "is_local_import": row.get("source", "") == "WinLens Import",
                }
            )
        return results

    def get_references(self) -> list[str]:
        df = Material._load_dataframe().copy()
        if df.empty or "reference" not in df:
            return []
        references = [
            str(value).strip()
            for value in df["reference"].dropna().tolist()
            if str(value).strip()
        ]
        return sorted(set(references), key=str.casefold)

    def get_details(self, material_id: str) -> dict | None:
        for item in self.search():
            if item["material_id"] == material_id:
                return item
        return None

    def import_winlens_materials(self, root_path: str) -> MaterialCatalogImportResult:
        result = import_validated_winlens_materials(root_path)
        Material._df = None
        message = (
            f"Imported {result.imported_count} WinLens material(s), "
            f"skipped {result.skipped_existing} existing and "
            f"{result.skipped_unsupported} unsupported."
        )
        return MaterialCatalogImportResult(
            imported_count=result.imported_count,
            skipped_existing=result.skipped_existing,
            skipped_unsupported=result.skipped_unsupported,
            catalog_csv=result.catalog_csv,
            message=message,
        )

    def delete_materials(self, material_ids: list[str]) -> int:
        if not material_ids:
            return 0
        csv_path = Path(Material._filename).with_name("catalog_nk_winlens.csv")
        if not csv_path.is_file():
            return 0

        removable_ids = set(material_ids)
        rows = self.search()
        removable_rows = [
            row
            for row in rows
            if row["material_id"] in removable_ids and row.get("is_local_import")
        ]
        if not removable_rows:
            return 0

        kept_rows = []
        for row in self._load_extra_catalog_rows(csv_path):
            row_id = self._material_id(row)
            if row_id not in removable_ids:
                kept_rows.append(row)
                continue
            filename = self._resolve_material_path(row.get("filename", ""))
            try:
                if filename and Path(filename).is_file():
                    Path(filename).unlink()
            except OSError:
                pass

        if kept_rows:
            import pandas as pd

            pd.DataFrame(kept_rows).to_csv(csv_path, index=False)
        else:
            csv_path.write_text("", encoding="utf-8")

        Material._df = None
        return len(removable_rows)

    @staticmethod
    def _classify_source(filename: str) -> str:
        normalized = str(filename or "").replace("\\", "/").casefold()
        if "/winlens/" in normalized:
            return "WinLens Import"
        if normalized.startswith("glass/"):
            return "Built-in Glass"
        if normalized.startswith("main/"):
            return "RefractiveIndex.info"
        return "Catalog"

    @staticmethod
    def _resolve_material_path(filename: str) -> str:
        relative = str(filename or "").strip()
        if not relative:
            return ""
        return str(Path(Material._filename).parent / "data-nk" / Path(relative))

    @staticmethod
    def _parse_float(value) -> float | None:  # noqa: ANN001
        if value in (None, ""):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _material_id(row: dict) -> str:
        reference = str(row.get("reference", "")).strip()
        filename = str(row.get("filename", "")).strip()
        name = str(row.get("filename_no_ext") or row.get("name") or "").strip()
        return f"{reference}|{name}|{filename}"

    @staticmethod
    def _load_extra_catalog_rows(csv_path: Path) -> list[dict]:
        if not csv_path.is_file() or csv_path.stat().st_size == 0:
            return []
        import pandas as pd

        return pd.read_csv(csv_path).to_dict(orient="records")
