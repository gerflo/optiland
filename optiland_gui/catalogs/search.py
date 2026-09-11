"""Search helpers for the stock-lens catalog browser."""

from __future__ import annotations

from dataclasses import dataclass
import re

from .schema import CatalogLensRecord

WILDCARD_CHARACTERS = "*?"


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


class TextFilter:
    """Case-insensitive text filter with optional ``*`` and ``?`` wildcards.

    Without wildcards the filter is a plain substring test.  When the pattern
    contains ``*`` (any string, including the empty one) or ``?`` (exactly one
    character) it has to match the whole value: ``AC254-0*A`` matches
    ``AC254-050-A`` but not ``AC254-050-A-ML``.  Wrap a pattern in ``*`` to get
    substring behaviour together with wildcards.
    """

    __slots__ = ("pattern", "_regex")

    def __init__(self, pattern: str) -> None:
        self.pattern = pattern.casefold().strip()
        self._regex = _compile_wildcard_pattern(self.pattern)

    def __bool__(self) -> bool:
        return bool(self.pattern)

    @property
    def has_wildcards(self) -> bool:
        return self._regex is not None

    def matches(self, value: str) -> bool:
        """Return True when *value* satisfies the filter; empty filters match."""
        if not self.pattern:
            return True
        value = value.casefold()
        if self._regex is None:
            return self.pattern in value
        return self._regex.fullmatch(value) is not None


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
        part_number = TextFilter(query.part_number)
        part_number_variants = [
            TextFilter(_normalize_compact_pattern(variant))
            for variant in _part_number_search_variants(part_number.pattern)
        ]
        product_name = TextFilter(query.product_name)
        category = TextFilter(query.category)
        material_text = TextFilter(query.material_text)
        coating_text = TextFilter(query.coating_text)
        availability_text = TextFilter(query.availability_text)
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
            if not _matches_part_number(record.part_number, part_number, part_number_variants):
                continue
            if not product_name.matches(record.product_name):
                continue
            if not category.matches(record.category):
                continue
            if not material_text.matches(record.material_summary or ""):
                continue
            if not coating_text.matches(record.coating or ""):
                continue
            if not availability_text.matches(record.availability_status or ""):
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


def _compile_wildcard_pattern(pattern: str) -> re.Pattern[str] | None:
    """Translate ``*``/``?`` wildcards into a regex; None when there are none."""
    if not any(char in pattern for char in WILDCARD_CHARACTERS):
        return None
    parts: list[str] = []
    for char in pattern:
        if char == "*":
            parts.append(".*")
        elif char == "?":
            parts.append(".")
        else:
            parts.append(re.escape(char))
    return re.compile("".join(parts), re.DOTALL)


def _matches_part_number(
    value: str,
    part_number: TextFilter,
    compact_variants: list[TextFilter],
) -> bool:
    """Match a part number literally first, then separator-insensitively."""
    if not part_number:
        return True
    if part_number.matches(value):
        return True
    compact_value = _normalize_compact_token(value)
    return any(variant and variant.matches(compact_value) for variant in compact_variants)


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


def _normalize_compact_pattern(value: str) -> str:
    """Like :func:`_normalize_compact_token` but keeps ``*``/``?`` wildcards."""
    return re.sub(r"[^0-9a-z*?]+", "", value.casefold())


def _part_number_search_variants(value: str) -> set[str]:
    """Return normalized query variants for common vendor part-number prefixes."""
    variants = {value}
    compact = _normalize_compact_pattern(value)
    if re.fullmatch(r"g[0-9*?]{5,}", compact):
        variants.add(compact[1:])
    elif re.fullmatch(r"[0-9*?]{5,}", compact):
        variants.add(f"g{compact}")
    return {variant for variant in variants if variant}
