"""Excelitas / LINOS shop catalog importer."""

from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

from ..schema import CatalogLensRecord, CatalogSource
from .base import CatalogImporter

EXCELITAS_SHOP_ROOT_URL = "https://linosoptics.excelitas.com/"
EXCELITAS_DISCOVERY_PAGE_URLS = [
    "https://linosoptics.excelitas.com/en/Precision-Optics/",
    "https://linosoptics.excelitas.com/en/Precision-Optics/Singlets/",
    "https://linosoptics.excelitas.com/en/Precision-Optics/Singlets/Plano-Convex-Lenses/",
    "https://linosoptics.excelitas.com/en/Precision-Optics/Singlets/Plano-Concave-Lenses/",
    "https://linosoptics.excelitas.com/en/Precision-Optics/Singlets/Aspheric-Condenser-Lenses/",
    "https://linosoptics.excelitas.com/en/Precision-Optics/LINOS-Achromats-Lens-Systems/",
    "https://linosoptics.excelitas.com/en/Precision-Optics/LINOS-Achromats-Lens-Systems/Achromats-positive/",
    "https://linosoptics.excelitas.com/en/Precision-Optics/LINOS-Achromats-Lens-Systems/Achromats-negative/",
    "https://linosoptics.excelitas.com/en/Precision-Optics/LINOS-Laseroptics-Lenses/",
    (
        "https://linosoptics.excelitas.com/en/Precision-Optics/LINOS-Laseroptics-Lenses/"
        "LINOS-F-Theta-Ronar-Lenses/Product-range-LINOS-F-Theta-Ronar/"
    ),
]
EXCELITAS_DEFAULT_FAMILY_URLS = [
    (
        "https://linosoptics.excelitas.com/en/Precision-Optics/Singlets/"
        "Plano-Convex-Lenses/Plano-convex-lenses-mounted.html"
    ),
    (
        "https://linosoptics.excelitas.com/en/Precision-Optics/Singlets/"
        "Plano-Convex-Lenses/Plano-convex-lenses-mounted-fused-silica.html"
    ),
    (
        "https://linosoptics.excelitas.com/en/Precision-Optics/Singlets/"
        "Plano-Concave-Lenses/Plano-concave-lenses-unmounted-N-BK7.html"
    ),
    (
        "https://linosoptics.excelitas.com/en/Precision-Optics/Singlets/"
        "Plano-Concave-Lenses/Plano-concave-Lenses-unmounted-fused-silica.html"
    ),
    (
        "https://linosoptics.excelitas.com/en/Precision-Optics/Singlets/"
        "Plano-Concave-Lenses/Plano-concave-lenses-mounted-N-BK7.html"
    ),
    (
        "https://linosoptics.excelitas.com/en/Precision-Optics/LINOS-Achromats-Lens-Systems/"
        "Achromats-positive/Achromats-VIS-Positive-dia-3-mm-to-31-5-mm-unmounted.html"
    ),
    (
        "https://linosoptics.excelitas.com/en/Precision-Optics/LINOS-Achromats-Lens-Systems/"
        "Achromats-positive/Achromats-VIS-Positive-dia-3-mm-to-31-5-mm-mounted.html"
    ),
    (
        "https://linosoptics.excelitas.com/en/Precision-Optics/Singlets/"
        "Aspheric-Condenser-Lenses/Aspheric-Condenser-Lenses-unmounted-crown-glass.html"
    ),
    (
        "https://linosoptics.excelitas.com/en/Precision-Optics/Singlets/"
        "Aspheric-Condenser-Lenses/Aspheric-Condenser-Lenses-mounted-crown-glass.html"
    ),
]

_PART_LINK_RE = re.compile(
    r'href="([^"]+)"[^>]*>\s*([A-Z]\d{6,12})\s*</a>\s*([^<\r\n]+)',
    re.IGNORECASE,
)
_VARIANT_ROW_RE = re.compile(
    r'<td[^>]*class="bestnr"[^>]*>\s*<a[^>]*>([A-Z]\d{6,12})</a>\s*</td>\s*'
    r'<td[^>]*>\s*(.*?)\s*</td>\s*'
    r'<td[^>]*>\s*(.*?)\s*</td>',
    re.IGNORECASE | re.DOTALL,
)
_OPTION_RE = re.compile(
    r'<option[^>]*value="([A-Z]\d{6,12})"[^>]*>(.*?)</option>',
    re.IGNORECASE | re.DOTALL,
)
_PAGE_TITLE_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.IGNORECASE | re.DOTALL)
_DOCS_TAB_RE = re.compile(r'<div id="tab_docs">(.*?)</div>', re.IGNORECASE | re.DOTALL)
_ZEMAX_LINK_RE = re.compile(
    r'href="([^"]+)"[^>]*>\s*ZEMAX-Files\s*<',
    re.IGNORECASE,
)
_ANCHOR_RE = re.compile(
    r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
_TABLE_RE = re.compile(r"<table[^>]*>(.*?)</table>", re.IGNORECASE | re.DOTALL)
_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.IGNORECASE | re.DOTALL)
_CELL_RE = re.compile(r"<t([hd])[^>]*>(.*?)</t[hd]>", re.IGNORECASE | re.DOTALL)
_SPACE_RE = re.compile(r"\s+")
_FOCAL_RE = re.compile(r"\bF(?:L|ocal Length)?\s*=?\s*(-?[0-9]+(?:\.[0-9]+)?)\b", re.IGNORECASE)
_DIAMETER_RE = re.compile(r"\bD(?:ia(?:meter)?)?\s*=?\s*([0-9]+(?:\.[0-9]+)?)\b", re.IGNORECASE)
_CATEGORY_KEYWORDS = (
    ("aspheric", "asphere"),
    ("asphere", "asphere"),
    ("achr.", "achromat"),
    ("achromat", "achromat"),
    ("plano-convex", "plano-convex"),
    ("plano-conc", "plano-concave"),
    ("plano-concave", "plano-concave"),
    ("symm.-convex", "bi-convex"),
    ("symmetric-convex", "bi-convex"),
    ("biconvex", "bi-convex"),
    ("biconcave", "bi-concave"),
    ("meniscus", "meniscus"),
    ("f-theta", "f-theta"),
)
_MATERIAL_KEYWORDS = (
    "N-BK 7",
    "N-BK7",
    "Crown glass",
    "UVFS",
    "Fused silica",
    "Fused Silica",
    "CaF2",
    "Calcium Fluoride",
    "ZnSe",
    "Germanium",
    "Silicon",
    "Sapphire",
    "N-LASF 9",
)
_COATING_KEYWORDS = (
    "Uncoated",
    "ARB2-VIS",
    "ARB2-NIR",
    "ARHS-YAG",
    "RAL (AL)",
    "RAGV",
)
_DISCOVERY_KEYWORDS = (
    "lens",
    "lenses",
    "achromat",
    "singlet",
    "aspheric",
    "condenser",
    "meniscus",
    "f-theta",
)
_DISCOVERY_EXCLUDED_PATH_PARTS = (
    "/files/",
    "/publications/",
    "/optics-software/",
    "/machine-vision/",
    "/contact",
)


class ExcelitasCatalogImporter(CatalogImporter):
    """Import Excelitas / LINOS catalog records from shop pages and Zemax files."""

    manufacturer = "Excelitas LINOS"
    catalog_url = EXCELITAS_SHOP_ROOT_URL

    def import_html_page(self, html_text: str, page_url: str) -> list[CatalogLensRecord]:
        """Parse a LINOS family page into metadata-only catalog records."""
        page_title = _extract_page_title(html_text)
        imported_at = datetime.now(timezone.utc).isoformat()
        records: list[CatalogLensRecord] = []
        seen_parts: set[str] = set()
        table_metadata = _extract_table_metadata(html_text)

        for base_part_number, description_html, pricing_html in _VARIANT_ROW_RE.findall(html_text):
            description = _clean_text(_html_strip(description_html))
            if not description:
                description = page_title or base_part_number.strip().upper()
            option_matches = _OPTION_RE.findall(pricing_html)
            if not option_matches:
                option_matches = [(base_part_number, "")]
            for option_part_number, option_text in option_matches:
                normalized_part = option_part_number.strip().upper()
                if not normalized_part or normalized_part in seen_parts:
                    continue
                seen_parts.add(normalized_part)
                coating = _infer_variant_coating(option_text) or _infer_coating(description)
                record = CatalogLensRecord(
                    catalog_id=f"{self.manufacturer.lower()}:{normalized_part.casefold()}",
                    manufacturer=self.manufacturer,
                    part_number=normalized_part,
                    product_name=description,
                    category=_infer_category(description, page_title),
                    url=f"{page_url}#popup_{normalized_part}",
                    efl_mm=_infer_efl(description),
                    diameter_mm=_infer_diameter(description),
                    material_summary=_infer_material_from_context(description, page_title, page_url),
                    coating=coating,
                    surfaces=[],
                    tags=_build_tags(description, page_title, coating_override=coating),
                    source=CatalogSource(
                        manufacturer=self.manufacturer,
                        source_type="excelitas_shop_html",
                        source_path=None,
                        source_url=page_url,
                        imported_at=imported_at,
                        license_note=(
                            "Imported from official Excelitas / LINOS shop metadata. "
                            "Review vendor license terms before redistribution."
                        ),
                        version_hint=page_title or page_url,
                    ),
                )
                record.search_blob = record.build_search_blob()
                records.append(record)

        for href, part_number, description in _PART_LINK_RE.findall(html_text):
            normalized_part = part_number.strip().upper()
            if not normalized_part or normalized_part in seen_parts:
                continue
            seen_parts.add(normalized_part)
            description = _clean_text(description)
            if not description:
                description = page_title or normalized_part
            record = CatalogLensRecord(
                catalog_id=f"{self.manufacturer.lower()}:{normalized_part.casefold()}",
                manufacturer=self.manufacturer,
                part_number=normalized_part,
                product_name=description,
                category=_infer_category(description, page_title),
                url=urljoin(page_url, href),
                efl_mm=_infer_efl(description),
                diameter_mm=_infer_diameter(description),
                material_summary=_infer_material_from_context(description, page_title, page_url),
                coating=_infer_coating(description),
                surfaces=[],
                tags=_build_tags(description, page_title),
                source=CatalogSource(
                    manufacturer=self.manufacturer,
                    source_type="excelitas_shop_html",
                    source_path=None,
                    source_url=page_url,
                    imported_at=imported_at,
                    license_note=(
                        "Imported from official Excelitas / LINOS shop metadata. "
                        "Review vendor license terms before redistribution."
                    ),
                    version_hint=page_title or page_url,
                ),
            )
            record.search_blob = record.build_search_blob()
            records.append(record)

        for record in records:
            _apply_table_metadata(record, table_metadata.get(record.part_number))
        return records

    def build_product_url(self, part_number: str) -> str | None:
        return self.catalog_url


def extract_excelitas_zemax_urls(html_text: str, page_url: str) -> list[str]:
    """Return absolute ZEMAX download URLs from a LINOS family/product page."""
    urls: list[str] = []
    seen: set[str] = set()
    for href in _ZEMAX_LINK_RE.findall(html_text):
        absolute = urljoin(page_url, html.unescape(href))
        if absolute in seen:
            continue
        seen.add(absolute)
        urls.append(absolute)
    return urls


def extract_excelitas_document_urls(html_text: str, page_url: str) -> list[str]:
    """Return absolute document/download URLs from the Docs + Drawings tab."""
    match = _DOCS_TAB_RE.search(html_text)
    if not match:
        return []
    block = match.group(1)
    urls: list[str] = []
    seen: set[str] = set()
    for href, _label_html in _ANCHOR_RE.findall(block):
        absolute = urljoin(page_url, html.unescape(href))
        if absolute in seen:
            continue
        seen.add(absolute)
        urls.append(absolute)
    return urls


def extract_excelitas_family_urls(html_text: str, page_url: str) -> list[str]:
    """Return likely family-page URLs from official Excelitas / LINOS landing pages."""
    urls: list[str] = []
    seen: set[str] = set()
    base_host = urlparse(EXCELITAS_SHOP_ROOT_URL).netloc.casefold()
    current_path = urlparse(page_url).path.rstrip("/").casefold()

    for href, label_html in _ANCHOR_RE.findall(html_text):
        absolute = urljoin(page_url, html.unescape(href))
        parsed = urlparse(absolute)
        path = parsed.path.rstrip("/")
        lowered_path = path.casefold()
        label = _clean_text(_html_strip(label_html))
        discovery_text = f"{lowered_path} {label.casefold()}"

        if parsed.netloc.casefold() != base_host:
            continue
        if "/precision-optics/" not in lowered_path:
            continue
        if not lowered_path.endswith(".html"):
            continue
        if lowered_path == current_path:
            continue
        if any(part in lowered_path for part in _DISCOVERY_EXCLUDED_PATH_PARTS):
            continue
        if not any(keyword in discovery_text for keyword in _DISCOVERY_KEYWORDS):
            continue
        if absolute in seen:
            continue
        seen.add(absolute)
        urls.append(absolute)

    return urls


def looks_like_excelitas_family_page(html_text: str) -> bool:
    """Return whether HTML looks like a LINOS family page with usable catalog content."""
    return bool(_PART_LINK_RE.search(html_text) or _ZEMAX_LINK_RE.search(html_text))


def _extract_page_title(html_text: str) -> str:
    match = _PAGE_TITLE_RE.search(html_text)
    if not match:
        return ""
    return _clean_text(match.group(1))


def _clean_text(value: str) -> str:
    value = html.unescape(value)
    value = value.replace("\ufeff", " ")
    value = _SPACE_RE.sub(" ", value)
    return value.strip(" ,;:-")


def _html_strip(value: str) -> str:
    return re.sub(r"<[^>]+>", " ", value)


def _infer_category(description: str, page_title: str) -> str:
    lowered = f"{description} {page_title}".casefold()
    for needle, category in _CATEGORY_KEYWORDS:
        if needle in lowered:
            return category
    return ""


def _infer_efl(description: str) -> float | None:
    match = _FOCAL_RE.search(description)
    if not match:
        return None
    return float(match.group(1))


def _infer_diameter(description: str) -> float | None:
    match = _DIAMETER_RE.search(description)
    if not match:
        return None
    return float(match.group(1))


def _infer_material(description: str) -> str | None:
    lowered = description.casefold()
    for material in _MATERIAL_KEYWORDS:
        if material.casefold() in lowered:
            return material.replace("N-BK 7", "N-BK7")
    return None


def _infer_material_from_context(*texts: str) -> str | None:
    """Infer material from trusted text fragments on the family page."""
    for text in texts:
        material = _infer_material(text)
        if material:
            return material
    return None


def _infer_coating(description: str) -> str | None:
    lowered = description.casefold()
    for coating in _COATING_KEYWORDS:
        if coating.casefold() in lowered:
            return coating
    return None


def _infer_variant_coating(option_text: str) -> str | None:
    cleaned = _clean_text(_html_strip(option_text))
    if not cleaned:
        return None
    coating = re.split(r"\s+[–-]\s+|\s+€", cleaned, maxsplit=1)[0].strip()
    if not coating:
        return None
    if "€" in coating:
        return None
    return coating


def _extract_table_metadata(html_text: str) -> dict[str, dict[str, object]]:
    """Return per-part metadata extracted from structured product tables."""
    metadata_by_part: dict[str, dict[str, object]] = {}

    for table_html in _TABLE_RE.findall(html_text):
        row_htmls = _ROW_RE.findall(table_html)
        if len(row_htmls) < 2:
            continue
        header = _extract_row_cells(row_htmls[0])
        if not header:
            continue
        part_index = _find_header_index(header, ("part no.", "part no", "part number"))
        if part_index is None:
            continue
        diameter_index = _find_header_index(
            header,
            ("optic size (mm)", "diameter (mm)", "dia. (mm)", "dia (mm)"),
        )
        focal_index = _find_header_index(
            header,
            ("focal length (mm)", "f'546 nm (mm)", "focal length"),
        )
        coating_index = _find_header_index(
            header,
            ("coating", "coating specification"),
        )
        material_index = _find_header_index(
            header,
            (
                "material",
                "material type",
                "optic material",
                "glass",
                "glass type",
                "substrate",
                "material / substrate",
            ),
        )

        for row_html in row_htmls[1:]:
            cells = _extract_row_cells(row_html)
            if part_index >= len(cells):
                continue
            part_number = _match_part_number(cells[part_index])
            if not part_number:
                continue
            metadata: dict[str, object] = {}
            if diameter_index is not None and diameter_index < len(cells):
                diameter = _parse_float_cell(cells[diameter_index])
                if diameter is not None:
                    metadata["diameter_mm"] = diameter
            if focal_index is not None and focal_index < len(cells):
                efl = _parse_float_cell(cells[focal_index])
                if efl is not None:
                    metadata["efl_mm"] = efl
            if coating_index is not None and coating_index < len(cells):
                coating = _infer_coating(cells[coating_index]) or _clean_text(cells[coating_index])
                if coating:
                    metadata["coating"] = coating
            if material_index is not None and material_index < len(cells):
                material = _infer_material(cells[material_index]) or _clean_text(cells[material_index])
                if material:
                    metadata["material_summary"] = material
            if metadata:
                metadata_by_part[part_number] = metadata

    return metadata_by_part


def _extract_row_cells(row_html: str) -> list[str]:
    """Return cleaned cell text from a single HTML table row."""
    cells: list[str] = []
    for _tag, cell_html in _CELL_RE.findall(row_html):
        cells.append(_clean_text(_html_strip(cell_html)))
    return cells


def _find_header_index(headers: list[str], candidates: tuple[str, ...]) -> int | None:
    """Return the first header index matching any candidate label."""
    normalized_headers = [_normalize_header(header) for header in headers]
    normalized_candidates = {_normalize_header(candidate) for candidate in candidates}
    for index, header in enumerate(normalized_headers):
        if header in normalized_candidates:
            return index
    return None


def _normalize_header(value: str) -> str:
    """Normalize table headers for loose matching."""
    return re.sub(r"\s+", " ", value.casefold()).strip(" :;,.")


def _match_part_number(value: str) -> str | None:
    """Return the Excelitas part number contained in *value* if present."""
    match = re.search(r"\b([A-Z]\d{6,12})\b", value, re.IGNORECASE)
    if not match:
        return None
    return match.group(1).upper()


def _parse_float_cell(value: str) -> float | None:
    """Parse the leading numeric value from a table cell."""
    match = re.search(r"-?\d+(?:[.,]\d+)?", value)
    if not match:
        return None
    try:
        return float(match.group(0).replace(",", "."))
    except ValueError:
        return None


def _apply_table_metadata(
    record: CatalogLensRecord,
    metadata: dict[str, object] | None,
) -> None:
    """Fill missing record fields from structured HTML table metadata."""
    if not metadata:
        return
    if record.efl_mm is None and isinstance(metadata.get("efl_mm"), float):
        record.efl_mm = metadata["efl_mm"]
    if record.diameter_mm is None and isinstance(metadata.get("diameter_mm"), float):
        record.diameter_mm = metadata["diameter_mm"]
    if not record.material_summary and isinstance(metadata.get("material_summary"), str):
        record.material_summary = metadata["material_summary"]
    if not record.coating and isinstance(metadata.get("coating"), str):
        record.coating = metadata["coating"]
    record.search_blob = record.build_search_blob()


def _build_tags(description: str, page_title: str, coating_override: str | None = None) -> list[str]:
    tags = [_infer_category(description, page_title)]
    material = _infer_material_from_context(description, page_title)
    coating = coating_override or _infer_coating(description)
    if material:
        tags.append(material)
    if coating:
        tags.append(coating)
    return [tag for tag in tags if tag]
