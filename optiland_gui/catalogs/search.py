"""Search helpers for the stock-lens catalog browser."""

from __future__ import annotations

from dataclasses import dataclass

from .schema import CatalogLensRecord


@dataclass(slots=True)
class CatalogSearchQuery:
    """Normalized query object for in-memory catalog searching."""

    text: str = ""
    manufacturer: str = ""
    category: str = ""
    efl_min: float | None = None
    efl_max: float | None = None
    diameter_min: float | None = None
    diameter_max: float | None = None
    material_text: str = ""
    coating_text: str = ""


class CatalogSearchService:
    """Perform simple in-memory filtering over cached catalog records."""

    def search(
        self,
        records: list[CatalogLensRecord],
        query: CatalogSearchQuery,
    ) -> list[CatalogLensRecord]:
        """Return matching records sorted by manufacturer and part number."""
        text = query.text.casefold().strip()
        manufacturer = query.manufacturer.casefold().strip()
        category = query.category.casefold().strip()
        material_text = query.material_text.casefold().strip()
        coating_text = query.coating_text.casefold().strip()
        matches: list[CatalogLensRecord] = []

        for record in records:
            if text and text not in record.search_blob:
                continue
            if manufacturer and record.manufacturer.casefold() != manufacturer:
                continue
            if category and category not in record.category.casefold():
                continue
            if material_text and material_text not in (record.material_summary or "").casefold():
                continue
            if coating_text and coating_text not in (record.coating or "").casefold():
                continue
            if not _matches_range(record.efl_mm, query.efl_min, query.efl_max):
                continue
            if not _matches_range(
                record.diameter_mm, query.diameter_min, query.diameter_max
            ):
                continue
            matches.append(record)

        return sorted(
            matches,
            key=lambda item: (
                item.manufacturer.casefold(),
                item.part_number.casefold(),
                item.product_name.casefold(),
            ),
        )


def _matches_range(
    value: float | None,
    min_value: float | None,
    max_value: float | None,
) -> bool:
    if min_value is None and max_value is None:
        return True
    if value is None:
        return False
    if min_value is not None and value < min_value:
        return False
    if max_value is not None and value > max_value:
        return False
    return True
