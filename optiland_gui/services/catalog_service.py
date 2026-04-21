"""Catalog service for stock-lens import, search, cache, and insertion lookup."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from optiland_gui.catalogs.importers import (
    EdmundCatalogImporter,
    ThorlabsCatalogImporter,
)
from optiland_gui.catalogs.search import CatalogSearchQuery, CatalogSearchService
from optiland_gui.catalogs.storage import CatalogStorage
from optiland_gui.catalogs.schema import CatalogLensRecord


class CatalogService:
    """Manage locally cached stock-lens records and vendor importers."""

    def __init__(self, connector: object) -> None:
        self._connector = connector
        self._storage = CatalogStorage()
        self._search_service = CatalogSearchService()
        self._records: list[CatalogLensRecord] = self._storage.load_all_records()
        self._importers = {
            "edmund": EdmundCatalogImporter(),
            "thorlabs": ThorlabsCatalogImporter(),
        }

    def import_catalog_file(self, manufacturer: str, filepath: str | list[str]) -> int:
        """Import one or more manufacturer catalog files and persist them locally."""
        key = manufacturer.strip().lower()
        importer = self._importers.get(key)
        if importer is None:
            raise ValueError(f"Unsupported manufacturer: {manufacturer}")
        input_paths = [filepath] if isinstance(filepath, str) else filepath
        expanded_paths = self._expand_import_paths(input_paths)
        if not expanded_paths:
            raise ValueError(
                "No supported catalog files were selected. "
                "Choose .zmx or normalized .json files."
            )

        imported_records: list[CatalogLensRecord] = []
        for path in expanded_paths:
            imported_records.extend(importer.import_file(str(path)))

        merged_records = {
            record.catalog_id: record
            for record in self._records
            if record.manufacturer.casefold() == importer.manufacturer.casefold()
        }
        for record in imported_records:
            merged_records[record.catalog_id] = record

        self._storage.save_records(
            importer.manufacturer,
            sorted(
                merged_records.values(),
                key=lambda item: (
                    item.part_number.casefold(),
                    item.product_name.casefold(),
                ),
            ),
        )
        self._reload_all()
        return len(imported_records)

    def get_manufacturers(self) -> list[str]:
        """Return manufacturer names currently available in the local cache."""
        return sorted({record.manufacturer for record in self._records if record.manufacturer})

    def search(self, query_dict: dict | None = None) -> list[dict]:
        """Return GUI summary dicts matching *query_dict*."""
        query_dict = query_dict or {}
        query = CatalogSearchQuery(
            text=str(query_dict.get("text", "")),
            manufacturer=str(query_dict.get("manufacturer", "")),
            category=str(query_dict.get("category", "")),
            efl_min=_float_or_none(query_dict.get("efl_min")),
            efl_max=_float_or_none(query_dict.get("efl_max")),
            diameter_min=_float_or_none(query_dict.get("diameter_min")),
            diameter_max=_float_or_none(query_dict.get("diameter_max")),
            material_text=str(query_dict.get("material_text", "")),
            coating_text=str(query_dict.get("coating_text", "")),
        )
        return [record.to_summary_dict() for record in self._search_service.search(self._records, query)]

    def get_record(self, catalog_id: str) -> CatalogLensRecord | None:
        """Return a full record by id."""
        for record in self._records:
            if record.catalog_id == catalog_id:
                return record
        return None

    def get_record_details(self, catalog_id: str) -> dict | None:
        """Return a full record payload for GUI detail display."""
        record = self.get_record(catalog_id)
        return None if record is None else record.to_dict()

    def _reload_all(self) -> None:
        self._records = self._storage.load_all_records()

    def _expand_import_paths(self, raw_paths: Iterable[str]) -> list[Path]:
        """Return supported files from *raw_paths*, expanding directories recursively."""
        seen: set[Path] = set()
        expanded: list[Path] = []
        for raw_path in raw_paths:
            path = Path(raw_path)
            if path.is_dir():
                candidates = sorted(
                    list(path.rglob("*.zmx")) + list(path.rglob("*.json"))
                )
            elif path.is_file():
                candidates = [path]
            else:
                continue

            for candidate in candidates:
                suffix = candidate.suffix.lower()
                if suffix not in {".json", ".zmx"}:
                    continue
                resolved = candidate.resolve()
                if resolved in seen:
                    continue
                seen.add(resolved)
                expanded.append(candidate)
        return expanded


def _float_or_none(value) -> float | None:  # noqa: ANN001
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
