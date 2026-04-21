"""Persistence helpers for locally cached catalog records."""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QStandardPaths

from .schema import CatalogLensRecord


class CatalogStorage:
    """Read and write local per-manufacturer catalog caches."""

    def __init__(self) -> None:
        data_dir = QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)
        self._root = Path(data_dir) / "catalogs"
        self._root.mkdir(parents=True, exist_ok=True)

    @property
    def root(self) -> Path:
        return self._root

    @property
    def downloads_root(self) -> Path:
        """Return the directory used for downloaded vendor catalog archives."""
        path = self._root / "downloads"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def load_all_records(self) -> list[CatalogLensRecord]:
        """Load all cached manufacturer files."""
        records: list[CatalogLensRecord] = []
        for path in sorted(self._root.glob("*.json")):
            records.extend(self.load_records_for_path(path))
        return records

    def load_records_for_path(self, path: str | Path) -> list[CatalogLensRecord]:
        """Load records from a single cache file."""
        file_path = Path(path)
        if not file_path.exists():
            return []
        payload = json.loads(file_path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            raw_records = payload.get("records", [])
        elif isinstance(payload, list):
            raw_records = payload
        else:
            raw_records = []
        return [
            CatalogLensRecord.from_dict(item)
            for item in raw_records
            if isinstance(item, dict)
        ]

    def save_records(self, manufacturer: str, records: list[CatalogLensRecord]) -> Path:
        """Persist records for a single manufacturer cache."""
        filename = f"{manufacturer.strip().lower().replace(' ', '_')}.json"
        path = self._root / filename
        payload = {
            "manufacturer": manufacturer,
            "records": [record.to_dict() for record in records],
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return path
