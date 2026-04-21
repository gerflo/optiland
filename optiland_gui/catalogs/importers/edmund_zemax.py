"""Edmund catalog importer."""

from __future__ import annotations

from .base import CatalogImporter, load_normalized_json_records


class EdmundCatalogImporter(CatalogImporter):
    """Import Edmund catalog records from JSON or Zemax ``.zmx`` files."""

    manufacturer = "Edmund"
    catalog_url = "https://www.edmundoptics.com/products/services/zemax-catalog/"
