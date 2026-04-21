"""Thorlabs catalog importer."""

from __future__ import annotations

from .base import CatalogImporter, load_normalized_json_records


class ThorlabsCatalogImporter(CatalogImporter):
    """Import Thorlabs catalog records from JSON or Zemax ``.zmx`` files."""

    manufacturer = "Thorlabs"
    catalog_url = "https://www.thorlabs.com/navigation.cfm?guide_id=1"

    def build_product_url(self, part_number: str) -> str | None:
        if not part_number:
            return self.catalog_url
        return f"https://www.thorlabs.com/thorproduct.cfm?partnumber={part_number}"
