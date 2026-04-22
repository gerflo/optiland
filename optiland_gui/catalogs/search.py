"""Search helpers for the stock-lens catalog browser."""

from __future__ import annotations

from dataclasses import dataclass
import re

from .schema import CatalogLensRecord


@dataclass(slots=True)
class CatalogSearchQuery:
    """Normalized query object for in-memory catalog searching."""

    text: str = ""
    manufacturer: str = ""
    part_number: str = ""
    product_name: str = ""
    category: str = ""
    efl_min: float | None = None
    efl_max: float | None = None
    diameter_min: float | None = None
    diameter_max: float | None = None
    material_text: str = ""
    coating_text: str = ""
    availability_text: str = ""


class CatalogSearchService:
    """Perform simple in-memory filtering over cached catalog records."""

    def search(
        self,
        records: list[CatalogLensRecord],
        query: CatalogSearchQuery,
    ) -> list[CatalogLensRecord]:
        """Return matching records sorted by manufacturer and part number."""
        text = query.text.casefold().strip()
        text_variants = _part_number_search_variants(text)
        normalized_text_variants = {_normalize_compact_token(value) for value in text_variants}
        manufacturer = query.manufacturer.casefold().strip()
        part_number = query.part_number.casefold().strip()
        part_number_variants = _part_number_search_variants(part_number)
        normalized_part_number_variants = {
            _normalize_compact_token(value) for value in part_number_variants
        }
        product_name = query.product_name.casefold().strip()
        category = query.category.casefold().strip()
        material_text = query.material_text.casefold().strip()
        coating_text = query.coating_text.casefold().strip()
        availability_text = query.availability_text.casefold().strip()
        matches: list[CatalogLensRecord] = []

        for record in records:
            search_blob = record.search_blob or record.build_search_blob()
            if text and text not in search_blob:
                normalized_blob = _normalize_compact_token(search_blob)
                if not normalized_text_variants or not any(
                    variant and variant in normalized_blob
                    for variant in normalized_text_variants
                ):
                    continue
            if manufacturer and record.manufacturer.casefold() != manufacturer:
                continue
            record_part_number = record.part_number.casefold()
            if part_number and part_number not in record_part_number:
                normalized_record_part_number = _normalize_compact_token(record_part_number)
                if not normalized_part_number_variants or not any(
                    variant and variant in normalized_record_part_number
                    for variant in normalized_part_number_variants
                ):
                    continue
            if product_name and product_name not in record.product_name.casefold():
                continue
            if category and category not in record.category.casefold():
                continue
            if material_text and material_text not in (record.material_summary or "").casefold():
                continue
            if coating_text and coating_text not in (record.coating or "").casefold():
                continue
            if availability_text and availability_text not in (record.availability_status or "").casefold():
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


def _normalize_compact_token(value: str) -> str:
    """Return a case-insensitive token with separators removed."""
    return re.sub(r"[^0-9a-z]+", "", value.casefold())


def _part_number_search_variants(value: str) -> set[str]:
    """Return normalized query variants for common vendor part-number prefixes."""
    variants = {value}
    compact = _normalize_compact_token(value)
    if re.fullmatch(r"g\d{5,}", compact):
        variants.add(compact[1:])
    elif re.fullmatch(r"\d{5,}", compact):
        variants.add(f"g{compact}")
    return {variant for variant in variants if variant}
