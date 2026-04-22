"""WinLens SPD catalog importer and WinLens alias extraction helpers."""

from __future__ import annotations

import csv
import re
import struct
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ..schema import CatalogLensRecord, CatalogSource, LensSurfaceSpec
from .base import CatalogImporter

_READ_ENCODINGS = ("utf-8", "utf-16", "iso-8859-1")
_VERSION_RE = re.compile(r"Version\s+([0-9.]+)", re.IGNORECASE)
_EFL_RE = re.compile(r'"efl",\s*([-+]?\d+(?:\.\d+)?)', re.IGNORECASE)
_STOP_RAD_RE = re.compile(r'"Stop Rad",\s*([-+]?\d+(?:\.\d+)?)', re.IGNORECASE)
_WAVEBAND_RE = re.compile(
    r'"Waveband",\s*([-+]?\d+(?:\.\d+)?),\s*([-+]?\d+(?:\.\d+)?),\s*([-+]?\d+(?:\.\d+)?)',
    re.IGNORECASE,
)
_PART_DIGITS_RE = re.compile(r"\d{5,}")
_PRINTABLE_RUN_RE = re.compile(rb"[ -~]{12,}")
_ALIAS_LINE_RE = re.compile(r"^[\d\s]{9,}.+?[A-Za-z].*$")
_FOCAL_DIAMETER_PAIR_RE = re.compile(r"\b([0-9]+(?:\.[0-9]+)?)\s*/\s*([0-9]+(?:\.[0-9]+)?)\b")
_CATEGORY_KEYWORDS = (
    ("double gauss", "double gauss"),
    ("eyepiece", "eyepiece"),
    ("microscopic", "microscope objective"),
    ("microscope objective", "microscope objective"),
    ("microprojection", "microprojection lenses"),
    ("micro projection", "microprojection lenses"),
    ("petzval", "petzval"),
    ("laser focus", "laser focus"),
    ("beam expander", "beam expander"),
    ("condenser", "condenser"),
    ("asphere", "asphere"),
    ("aspheric", "asphere"),
    ("plano-convex", "plano-convex"),
    ("planoconvex", "plano-convex"),
    ("plano-concave", "plano-concave"),
    ("planoconcave", "plano-concave"),
    ("bi-convex", "bi-convex"),
    ("biconvex", "bi-convex"),
    ("bi-concave", "bi-concave"),
    ("biconcave", "bi-concave"),
    ("meniscus", "meniscus"),
    ("ball lens", "ball lens"),
    ("halo", "halo"),
    ("achromat", "achromat"),
)
_IGNORED_WINLENS_CATEGORIES = {
    "beam expander",
    "eyepiece",
    "hyperchromatic doublet",
    "microprojection lenses",
    "microscope objective",
}


@dataclass(slots=True)
class WinLensAliasGroup:
    """Alias relationship extracted from auxiliary WinLens catalog files."""

    part_numbers: list[str]
    family_numbers: list[str]
    title: str
    materials: list[str]
    source_path: str


class WinLensCatalogImporter(CatalogImporter):
    """Import WinLens 2002 ``.SPD`` library files."""

    manufacturer = "WinLens Library 2002"
    supported_suffixes = {".spd", ".txt", ".dat"}

    def import_file(self, path: str) -> list[CatalogLensRecord]:
        file_path = Path(path)
        if file_path.suffix.lower() == ".spd":
            record = load_winlens_catalog_record(path, self.manufacturer)
            if record is None:
                return []
            return [record]
        if file_path.suffix.lower() == ".txt":
            return load_winlens_table_records(path, self.manufacturer)
        if file_path.suffix.lower() == ".dat":
            return load_winlens_dat_records(path, self.manufacturer)
        raise ValueError(f"Unsupported WinLens catalog file: {file_path.name}")


def is_winlens_catalog_path(path: str | Path) -> bool:
    """Return whether *path* belongs to importable WinLens catalog content."""
    file_path = Path(path)
    suffix = file_path.suffix.casefold()
    parts = {part.casefold() for part in file_path.parts}
    parts_joined = " / ".join(part.casefold() for part in file_path.parts)

    if suffix == ".spd":
        if "examples" in parts or "manual examples" in parts_joined:
            return False
        # Generic WinLens "LIBRARY" families (zoom lenses, telescopes, tessars, etc.)
        # are design examples/templates rather than concrete stock-lens products.
        # Only the LINOS standard systems subtree maps to actual stock-lens-like items.
        return "linos_standard_systems" in parts

    if suffix == ".txt":
        return file_path.name.casefold() in {"prisms.txt", "gratings.txt"}

    if suffix == ".dat":
        return file_path.name.casefold() in {
            "sh_l1.dat",
            "sh_l2.dat",
            "sh_l2a.dat",
            "sh_c1.dat",
            "sh_grin.dat",
        }

    return False


def load_winlens_catalog_record(path: str, manufacturer: str) -> CatalogLensRecord | None:
    """Load a WinLens ``.SPD`` design file as a catalog-like record."""
    file_path = Path(path)
    raw_text = _read_text_with_fallback(file_path)
    lines = [line for line in raw_text.splitlines() if line.strip()]
    version = _extract_version(lines[0] if lines else "")
    title = _extract_title(lines[1] if len(lines) > 1 else "", file_path.stem)
    surfaces = _parse_v4_surfaces(lines) if version.startswith("4") else []
    materials = _collect_materials(surfaces)
    diameter_mm = _extract_stop_diameter(raw_text, surfaces)
    category = _infer_category(title, file_path)
    tags = _build_tags(file_path, version, category)
    wavelengths = _extract_waveband(raw_text)
    imported_at = datetime.now(timezone.utc).isoformat()

    record = CatalogLensRecord(
        catalog_id=f"{manufacturer.lower()}:{file_path.stem.lower()}",
        manufacturer=manufacturer,
        part_number=file_path.stem.upper(),
        product_name=title,
        category=category,
        efl_mm=_extract_efl(raw_text, title),
        diameter_mm=diameter_mm,
        material_summary=", ".join(materials) if materials else None,
        wavelength_min_um=min(wavelengths) / 1000.0 if wavelengths else None,
        wavelength_max_um=max(wavelengths) / 1000.0 if wavelengths else None,
        surfaces=surfaces,
        tags=tags,
        source=CatalogSource(
            manufacturer=manufacturer,
            source_type="winlens_spd",
            source_path=str(file_path),
            source_url=None,
            imported_at=imported_at,
            license_note=(
                "Imported from a local WinLens 2002 SPD library file. "
                "Review vendor license terms before redistribution."
            ),
            version_hint=f"WinLens SPD v{version}" if version else file_path.name,
        ),
    )
    if _should_ignore_winlens_record(record):
        return None
    record.search_blob = record.build_search_blob()
    return record


def load_winlens_alias_groups(root_path: str | Path) -> list[WinLensAliasGroup]:
    """Extract part-number alias groups from auxiliary WinLens catalog files."""
    root = Path(root_path)
    groups: list[WinLensAliasGroup] = []
    for path in sorted(root.rglob("sh_l*.dat")):
        entries = _extract_printable_strings(path)
        for index, entry in enumerate(entries):
            normalized = _normalize_alias_line(entry)
            if not normalized or not _ALIAS_LINE_RE.match(normalized):
                continue
            part_numbers = _extract_alias_part_numbers(normalized)
            if len(part_numbers) < 2:
                continue
            title = _extract_alias_title(normalized)
            materials = _extract_alias_materials(entries[index + 1] if index + 1 < len(entries) else "")
            candidate = WinLensAliasGroup(
                part_numbers=part_numbers,
                family_numbers=_family_aliases(part_numbers),
                title=title,
                materials=materials,
                source_path=str(path),
            )
            if groups and _should_merge_alias_group(groups[-1], candidate):
                groups[-1] = _merge_alias_group(groups[-1], candidate)
            else:
                groups.append(candidate)
    return _deduplicate_alias_groups(groups)


def load_winlens_table_records(path: str, manufacturer: str) -> list[CatalogLensRecord]:
    """Load structured WinLens table exports such as prisms and gratings."""
    file_path = Path(path)
    name = file_path.name.casefold()
    if name == "prisms.txt":
        return _load_winlens_prism_records(file_path, manufacturer)
    if name == "gratings.txt":
        return _load_winlens_grating_records(file_path, manufacturer)
    return []


def load_winlens_dat_records(path: str, manufacturer: str) -> list[CatalogLensRecord]:
    """Load selected structured WinLens DAT catalog files."""
    file_path = Path(path)
    name = file_path.name.casefold()
    if name in {"sh_l1.dat", "sh_l2.dat", "sh_l2a.dat"}:
        return _load_winlens_lens_family_dat_records(file_path, manufacturer)
    if name == "sh_c1.dat":
        return _load_winlens_cylinder_dat_records(file_path, manufacturer)
    if name == "sh_grin.dat":
        return _load_winlens_grin_dat_records(file_path, manufacturer)
    return []


def _read_text_with_fallback(path: Path) -> str:
    data = path.read_bytes()
    for encoding in _READ_ENCODINGS:
        try:
            return data.decode(encoding)
        except UnicodeError:
            continue
    return data.decode("latin1", "ignore")


def _extract_printable_strings(path: Path) -> list[str]:
    data = path.read_bytes()
    return [match.decode("latin1", "ignore") for match in _PRINTABLE_RUN_RE.findall(data)]


def _iter_dat_text_lines(path: Path) -> list[str]:
    return [line for line in _read_text_with_fallback(path).splitlines() if line.strip()]


def _extract_version(first_line: str) -> str:
    match = _VERSION_RE.search(first_line)
    return match.group(1) if match else ""


def _extract_title(line: str, fallback: str) -> str:
    values = _parse_csv_line(line)
    title = values[0].strip() if values else ""
    return title or fallback


def _normalize_alias_line(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\x00", " ")).strip()


def _extract_alias_part_numbers(text: str) -> list[str]:
    numbers: list[str] = []
    seen: set[str] = set()
    for run in re.findall(r"\d{9,}", text):
        usable = len(run) - (len(run) % 9)
        if usable < 9:
            continue
        for offset in range(0, usable, 9):
            token = run[offset : offset + 9]
            if token in seen:
                continue
            seen.add(token)
            numbers.append(token)
    return numbers


def _family_aliases(part_numbers: list[str]) -> list[str]:
    families: list[str] = []
    seen: set[str] = set()
    for token in part_numbers:
        family = token[:6]
        if len(family) != 6 or family in seen:
            continue
        seen.add(family)
        families.append(family)
    return families


def _extract_alias_title(text: str) -> str:
    title = re.sub(r"^[^A-Za-z]+", "", text).strip()
    return re.sub(r"\s+", " ", title)


def _extract_alias_materials(text: str) -> list[str]:
    materials: list[str] = []
    seen: set[str] = set()
    for candidate in re.findall(r"[A-Z][A-Z0-9-]{2,}", text):
        if candidate in {"ACHROMAT", "ECO", "VERS"}:
            continue
        if candidate in seen:
            continue
        seen.add(candidate)
        materials.append(candidate)
    return materials


def _extract_material_sequence(text: str) -> list[str]:
    candidates = _extract_alias_materials(text)
    if not candidates:
        return []
    filtered = [candidate for candidate in candidates if _looks_like_glass_code(candidate)]
    if not filtered or len(filtered) > 4:
        return []
    return filtered


def _looks_like_glass_code(candidate: str) -> bool:
    upper = candidate.strip().upper()
    if upper in {"AIR", "GRIN"}:
        return True
    if len(upper) > 12:
        return False
    if upper.startswith(("WL", "W8", "33K", "FFF")):
        return False
    if not re.fullmatch(r"(?:[A-Z]{1,3}-)?[A-Z]{1,6}\d{1,3}[A-Z]?", upper):
        return False
    return True


def _should_merge_alias_group(first: WinLensAliasGroup, second: WinLensAliasGroup) -> bool:
    if first.source_path != second.source_path:
        return False
    if set(first.family_numbers) & set(second.family_numbers):
        return True
    return False


def _merge_alias_group(first: WinLensAliasGroup, second: WinLensAliasGroup) -> WinLensAliasGroup:
    return WinLensAliasGroup(
        part_numbers=_merge_unique_strings(first.part_numbers, second.part_numbers),
        family_numbers=_merge_unique_strings(first.family_numbers, second.family_numbers),
        title=first.title if len(first.title) >= len(second.title) else second.title,
        materials=_merge_unique_strings(first.materials, second.materials),
        source_path=first.source_path,
    )


def _deduplicate_alias_groups(groups: list[WinLensAliasGroup]) -> list[WinLensAliasGroup]:
    deduplicated: list[WinLensAliasGroup] = []
    seen: set[tuple[tuple[str, ...], str]] = set()
    for group in groups:
        key = (tuple(group.part_numbers), group.title.casefold())
        if key in seen:
            continue
        seen.add(key)
        deduplicated.append(group)
    return deduplicated


def _merge_unique_strings(first: list[str], second: list[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for value in [*first, *second]:
        if value in seen:
            continue
        seen.add(value)
        merged.append(value)
    return merged


def _parse_csv_line(line: str) -> list[str]:
    try:
        return next(csv.reader([line], skipinitialspace=False))
    except csv.Error:
        return [line.strip()]


def _load_winlens_prism_records(path: Path, manufacturer: str) -> list[CatalogLensRecord]:
    rows = list(csv.DictReader(path.read_text(encoding="utf-8").splitlines()))
    imported_at = datetime.now(timezone.utc).isoformat()
    current_section = "prism"
    records: list[CatalogLensRecord] = []
    for row in rows:
        section_note = (row.get("note") or "").strip()
        if section_note:
            current_section = section_note
        part_specs = [
            ((row.get("Part#") or "").strip(), "prism"),
            ((row.get("Part# mount") or "").strip(), "mounted prism"),
        ]
        line_dims = _float_values(
            row.get("Depth"),
            row.get("LinDim1"),
            row.get("LinDim2"),
            row.get("LinDim3"),
        )
        angle_dims = _float_values(row.get("AngDim1"), row.get("AngDim2"))
        material = _join_values((row.get("Glass1") or "").strip(), (row.get("Glass2") or "").strip())
        for part_number, variant in part_specs:
            if not part_number:
                continue
            product_name = _build_prism_name(current_section, variant, line_dims)
            record = CatalogLensRecord(
                catalog_id=f"{manufacturer.lower()}:{part_number.lower()}",
                manufacturer=manufacturer,
                part_number=part_number,
                product_name=product_name,
                category="prism",
                diameter_mm=max(line_dims) if line_dims else None,
                center_thickness_mm=line_dims[0] if line_dims else None,
                material_summary=material or None,
                coating=_infer_table_coating(current_section),
                tags=_build_table_tags("prism", current_section, row.get("PrismType"), material),
                source=CatalogSource(
                    manufacturer=manufacturer,
                    source_type="winlens_table",
                    source_path=str(path),
                    source_url=None,
                    imported_at=imported_at,
                    license_note=(
                        "Imported from a local WinLens 2002 table file. "
                        "Review vendor license terms before redistribution."
                    ),
                    version_hint=path.name,
                ),
            )
            record.search_blob = record.build_search_blob() + _extra_search_blob(angle_dims)
            records.append(record)
    return records


def _load_winlens_grating_records(path: Path, manufacturer: str) -> list[CatalogLensRecord]:
    rows = list(csv.reader(path.read_text(encoding="utf-8").splitlines()))
    if not rows:
        return []
    header = [value.strip() for value in rows[0]]
    imported_at = datetime.now(timezone.utc).isoformat()
    records: list[CatalogLensRecord] = []
    for values in rows[1:]:
        if not any(cell.strip() for cell in values):
            continue
        row = {
            header[index]: values[index].strip() if index < len(values) else ""
            for index in range(len(header))
        }
        part_number = row.get("Part No.", "")
        if not part_number:
            continue
        size_text = row.get("Edge Length (mm�)", "") or row.get("Edge Length (mm)", "")
        size_values = _float_values(*re.split(r"[xX]", size_text))
        trailing = values[len(header):] if len(values) > len(header) else []
        description = row.get("", "")
        if not description and trailing:
            description = trailing[0].strip()
        material = trailing[3].strip() if len(trailing) > 3 else ""
        record = CatalogLensRecord(
            catalog_id=f"{manufacturer.lower()}:{part_number.lower()}",
            manufacturer=manufacturer,
            part_number=part_number,
            product_name=description or f"Grating {part_number}",
            category="grating",
            diameter_mm=max(size_values) if size_values else None,
            center_thickness_mm=_safe_float(row.get("Thickness (mm)")),
            material_summary=material or None,
            tags=_build_table_tags(
                "grating",
                row.get("Grooves (1 / mm)"),
                row.get("Blaze Wavelength (nm)"),
                material,
            ),
            source=CatalogSource(
                manufacturer=manufacturer,
                source_type="winlens_table",
                source_path=str(path),
                source_url=None,
                imported_at=imported_at,
                license_note=(
                    "Imported from a local WinLens 2002 table file. "
                    "Review vendor license terms before redistribution."
                ),
                version_hint=path.name,
            ),
        )
        record.search_blob = (
            record.build_search_blob()
            + _extra_search_blob(size_values)
            + _extra_search_blob([row.get("Grooves (1 / mm)", ""), row.get("Blaze Wavelength (nm)", "")])
        )
        records.append(record)
    return records


def _load_winlens_cylinder_dat_records(path: Path, manufacturer: str) -> list[CatalogLensRecord]:
    imported_at = datetime.now(timezone.utc).isoformat()
    records: list[CatalogLensRecord] = []
    pending_record_indexes: list[int] = []
    for entry in _iter_dat_text_lines(path):
        normalized = _normalize_alias_line(entry)
        if not normalized:
            continue
        if "cylinder" in normalized.casefold() and re.search(r"\d{9}", normalized):
            part_numbers = _extract_alias_part_numbers(normalized)
            if not part_numbers:
                continue
            title = _extract_alias_title(normalized)
            line_dims = _extract_dimension_values(title)
            efl_mm = _extract_first_named_float(r"f\s*=\s*([-+]?\d+(?:\.\d+)?)", title)
            inline_materials = _extract_alias_materials(normalized)
            current_indexes: list[int] = []
            for part_number in part_numbers:
                record = CatalogLensRecord(
                    catalog_id=f"{manufacturer.lower()}:{part_number.lower()}",
                    manufacturer=manufacturer,
                    part_number=part_number,
                    product_name=title,
                    category="cylindrical",
                    efl_mm=efl_mm,
                    diameter_mm=max(line_dims) if line_dims else None,
                    material_summary=", ".join(inline_materials) if inline_materials else None,
                    tags=_build_table_tags("cylinder", title, *inline_materials),
                    source=CatalogSource(
                        manufacturer=manufacturer,
                        source_type="winlens_dat",
                        source_path=str(path),
                        source_url=None,
                        imported_at=imported_at,
                        license_note=(
                            "Imported from a local WinLens 2002 DAT catalog file. "
                            "Review vendor license terms before redistribution."
                        ),
                        version_hint=path.name,
                    ),
                )
                if _should_ignore_winlens_record(record):
                    continue
                record.search_blob = record.build_search_blob() + _extra_search_blob(line_dims)
                current_indexes.append(len(records))
                records.append(record)
            pending_record_indexes = [] if inline_materials else current_indexes
            continue
        material_candidates = _extract_alias_materials(normalized)
        if material_candidates and pending_record_indexes:
            material_summary = ", ".join(material_candidates)
            for index in pending_record_indexes:
                records[index].material_summary = material_summary
                records[index].tags = _build_table_tags("cylinder", records[index].product_name, *material_candidates)
                records[index].search_blob = records[index].build_search_blob() + _extra_search_blob(
                    _extract_dimension_values(records[index].product_name)
                )
            pending_record_indexes = []
    return records


def _load_winlens_grin_dat_records(path: Path, manufacturer: str) -> list[CatalogLensRecord]:
    imported_at = datetime.now(timezone.utc).isoformat()
    records: list[CatalogLensRecord] = []
    pending_family = ""
    for entry in _iter_dat_text_lines(path):
        normalized = _normalize_alias_line(entry)
        if not normalized:
            continue
        if "grin" in normalized.casefold():
            pending_family = normalized
        if re.match(r"^\d{9}\b", normalized):
            part_number = normalized.split()[0]
            title = normalized
            body = re.sub(r"^\d{9}\s*", "", title).strip()
            category = "grin lens"
            if body.casefold().startswith("cyl"):
                category = "grin cylindrical"
            elif pending_family and "slab" in pending_family.casefold():
                category = "grin slab"
            record = CatalogLensRecord(
                catalog_id=f"{manufacturer.lower()}:{part_number.lower()}",
                manufacturer=manufacturer,
                part_number=part_number,
                product_name=_build_grin_name(title, pending_family),
                category=category,
                efl_mm=_extract_first_named_float(r"f\s*=\s*([-+]?\d+(?:\.\d+)?)", title),
                material_summary="GRIN",
                tags=_build_table_tags("grin", pending_family, title),
                source=CatalogSource(
                    manufacturer=manufacturer,
                    source_type="winlens_dat",
                    source_path=str(path),
                    source_url=None,
                    imported_at=imported_at,
                    license_note=(
                        "Imported from a local WinLens 2002 DAT catalog file. "
                        "Review vendor license terms before redistribution."
                    ),
                    version_hint=path.name,
                ),
            )
            if _should_ignore_winlens_record(record):
                continue
            record.search_blob = record.build_search_blob() + _extra_search_blob(
                _extract_named_metrics(title, ("pitch", "na", "wd"))
            )
            records.append(record)
    return records


def _load_winlens_lens_family_dat_records(path: Path, manufacturer: str) -> list[CatalogLensRecord]:
    imported_at = datetime.now(timezone.utc).isoformat()
    raw_data = path.read_bytes()
    records: list[CatalogLensRecord] = []
    pending_record_indexes: list[int] = []
    search_cursor = 0
    printable_entries = _extract_printable_strings(path)
    repeated_anchor_tokens = _find_repeated_family_anchor_tokens(printable_entries)
    for entry in printable_entries:
        normalized = _normalize_alias_line(entry)
        if not normalized:
            continue
        if _is_winlens_family_product_line(normalized):
            part_numbers = _extract_alias_part_numbers(normalized)
            if not part_numbers:
                continue
            part_numbers = _normalize_family_product_part_numbers(
                part_numbers,
                repeated_anchor_tokens,
            )
            recipe = _extract_winlens_lens_family_recipe(raw_data, part_numbers, search_cursor)
            title = _extract_alias_title(normalized)
            efl_mm = _extract_efl_from_title(title)
            diameter_mm = _extract_family_diameter(title)
            category = _infer_family_category(title)
            if recipe is None or "surfaces" not in recipe:
                singlet_recipe = _extract_winlens_singlet_recipe_after_text(
                    raw_data,
                    part_numbers,
                    title,
                    search_cursor,
                )
                if singlet_recipe is not None:
                    recipe = singlet_recipe
            inline_materials: list[str] = []
            surfaces: list[LensSurfaceSpec] = []
            if recipe is not None and "surfaces" in recipe:
                surfaces = recipe["surfaces"]
                inline_materials = recipe["materials"]
                diameter_mm = diameter_mm or recipe["diameter_mm"]
            current_indexes: list[int] = []
            for part_number in part_numbers:
                record = CatalogLensRecord(
                    catalog_id=f"{manufacturer.lower()}:{part_number.lower()}",
                    manufacturer=manufacturer,
                    part_number=part_number,
                    product_name=title,
                    category=category,
                    efl_mm=efl_mm,
                    diameter_mm=diameter_mm,
                    material_summary=", ".join(inline_materials) if inline_materials else None,
                    surfaces=[
                        LensSurfaceSpec(
                            surface_type=surface.surface_type,
                            radius=surface.radius,
                            thickness=surface.thickness,
                            material=surface.material,
                            conic=surface.conic,
                            semi_diameter=surface.semi_diameter,
                            comment=surface.comment,
                            extra_data=dict(surface.extra_data),
                        )
                        for surface in surfaces
                    ],
                    tags=_build_table_tags("winlens", category, title, *inline_materials),
                    source=CatalogSource(
                        manufacturer=manufacturer,
                        source_type="winlens_dat",
                        source_path=str(path),
                        source_url=None,
                        imported_at=imported_at,
                        license_note=(
                            "Imported from a local WinLens 2002 DAT catalog file. "
                            "Review vendor license terms before redistribution."
                        ),
                        version_hint=path.name,
                    ),
                )
                if _should_ignore_winlens_record(record):
                    continue
                record.search_blob = record.build_search_blob()
                current_indexes.append(len(records))
                records.append(record)
            if recipe is not None:
                search_cursor = recipe["next_cursor"]
            pending_record_indexes = current_indexes
            continue
        material_candidates = _extract_material_sequence(normalized)
        if material_candidates and pending_record_indexes:
            material_summary = ", ".join(material_candidates)
            for index in pending_record_indexes:
                records[index].material_summary = material_summary
                records[index].tags = _build_table_tags(
                    "winlens",
                    records[index].category,
                    records[index].product_name,
                    *material_candidates,
                )
                records[index].search_blob = records[index].build_search_blob()
            pending_record_indexes = []
    return records


def _find_repeated_family_anchor_tokens(entries: list[str]) -> set[str]:
    counts: dict[str, set[str]] = {}
    for entry in entries:
        normalized = _normalize_alias_line(entry)
        if not normalized or not _is_winlens_family_product_line(normalized):
            continue
        part_numbers = _extract_alias_part_numbers(normalized)
        if not part_numbers:
            continue
        counts.setdefault(part_numbers[0], set()).add(_extract_alias_title(normalized))
    return {
        token
        for token, titles in counts.items()
        if len(titles) >= 2
    }


def _normalize_family_product_part_numbers(
    part_numbers: list[str],
    repeated_anchor_tokens: set[str],
) -> list[str]:
    if len(part_numbers) <= 1:
        return part_numbers
    anchor = part_numbers[0]
    if anchor not in repeated_anchor_tokens:
        return part_numbers
    if len(part_numbers) == 2 and part_numbers[1].startswith("052"):
        return part_numbers
    return part_numbers[1:]


def _extract_winlens_lens_family_recipe(
    data: bytes,
    part_numbers: list[str],
    start_pos: int,
) -> dict[str, object] | None:
    part_run = "".join(part_numbers).encode("ascii", "ignore")
    match_start = data.find(part_run, start_pos)
    if match_start == -1:
        return None

    candidate = _find_winlens_recipe_block(data, match_start)
    if candidate is None:
        return {"next_cursor": match_start + len(part_run)}

    radii = candidate["radii"]
    semi_diameters = candidate["semi_diameters"]
    thicknesses = candidate["thicknesses"]
    materials = candidate["materials"]
    surfaces = [
        LensSurfaceSpec(
            surface_type="standard",
            radius=_normalize_recipe_radius(radii[0]),
            thickness=thicknesses[0],
            material=materials[0],
            semi_diameter=semi_diameters[0],
            comment="Surf  1",
        ),
        LensSurfaceSpec(
            surface_type="standard",
            radius=_normalize_recipe_radius(radii[1]),
            thickness=thicknesses[1],
            material=materials[1],
            semi_diameter=semi_diameters[1],
            comment="Surf  2",
        ),
        LensSurfaceSpec(
            surface_type="standard",
            radius=_normalize_recipe_radius(radii[2]),
            thickness=0.0,
            material="Air",
            semi_diameter=semi_diameters[2],
            comment="Surf  3",
        ),
    ]
    return {
        "surfaces": surfaces,
        "materials": materials,
        "diameter_mm": max(semi_diameters) * 2.0 if semi_diameters else None,
        "next_cursor": match_start + len(part_run),
    }


def _find_winlens_recipe_block(data: bytes, match_start: int) -> dict[str, object] | None:
    for offset in range(match_start - 80, match_start - 60):
        if offset < 0 or offset + 68 > len(data):
            continue
        radii = [_unpack_le_float(data, offset + index * 4) for index in range(3)]
        semi_diameters = [_unpack_le_float(data, offset + 12 + index * 4) for index in range(3)]
        thicknesses = [_unpack_le_float(data, offset + 24 + index * 4) for index in range(2)]
        if not _looks_like_recipe_numbers(radii, semi_diameters, thicknesses):
            continue
        materials = _decode_recipe_materials(data[offset + 32 : offset + 52])
        if materials is None:
            continue
        optical_constants = [
            _unpack_le_float(data, offset + 52 + index * 4) for index in range(4)
        ]
        if not _looks_like_recipe_optical_constants(optical_constants):
            continue
        return {
            "radii": radii,
            "semi_diameters": semi_diameters,
            "thicknesses": thicknesses,
            "materials": materials,
        }
    return None


def _extract_winlens_singlet_recipe_after_text(
    data: bytes,
    part_numbers: list[str],
    title: str,
    start_pos: int,
) -> dict[str, object] | None:
    lowered = title.casefold()
    if "plano-convex" not in lowered and "plano-concave" not in lowered:
        return None
    part_run = "".join(part_numbers).encode("ascii", "ignore")
    match_start = data.find(part_run, start_pos)
    if match_start == -1:
        return None
    candidate = _find_winlens_singlet_recipe_block_after_text(data, match_start)
    if candidate is None:
        return None

    radius = candidate["radius"]
    semi_diameter = candidate["semi_diameter"]
    thickness = candidate["thickness"]
    material = candidate["material"]
    surfaces = [
        LensSurfaceSpec(
            surface_type="standard",
            radius=_normalize_recipe_radius(radius),
            thickness=thickness,
            material=material,
            semi_diameter=semi_diameter,
            comment="Surf  1",
        ),
        LensSurfaceSpec(
            surface_type="standard",
            radius="inf",
            thickness=0.0,
            material="Air",
            semi_diameter=semi_diameter,
            comment="Surf  2",
        ),
    ]
    return {
        "surfaces": surfaces,
        "materials": [material],
        "diameter_mm": semi_diameter * 2.0,
        "next_cursor": match_start + len(part_run),
    }


def _find_winlens_singlet_recipe_block_after_text(
    data: bytes,
    match_start: int,
) -> dict[str, object] | None:
    window = data[match_start : match_start + 180]
    for material_offset in range(96, min(len(window) - 18, 145)):
        material = window[material_offset : material_offset + 10].decode("latin1", "ignore").strip()
        if not _looks_like_glass_code(material):
            continue
        if material_offset < 20:
            continue
        radius = _unpack_le_float(window, material_offset - 20)
        semi_diameter_1 = _unpack_le_float(window, material_offset - 12)
        semi_diameter_2 = _unpack_le_float(window, material_offset - 8)
        thickness = _unpack_le_float(window, material_offset - 4)
        nd = _unpack_le_float(window, material_offset + 10)
        vd = _unpack_le_float(window, material_offset + 14)
        if not (0.1 <= abs(radius) <= 5000.0):
            continue
        if not (0.1 <= semi_diameter_1 <= 250.0):
            continue
        if abs(semi_diameter_1 - semi_diameter_2) > 1e-3:
            continue
        if not (0.0 <= thickness <= 100.0):
            continue
        if not (1.0 <= nd <= 2.5 and 10.0 <= vd <= 100.0):
            continue
        return {
            "radius": radius,
            "semi_diameter": semi_diameter_1,
            "thickness": thickness,
            "material": material,
        }
    return None


def _unpack_le_float(data: bytes, offset: int) -> float:
    return struct.unpack("<f", data[offset : offset + 4])[0]


def _looks_like_recipe_numbers(
    radii: list[float],
    semi_diameters: list[float],
    thicknesses: list[float],
) -> bool:
    return (
        len(radii) == 3
        and len(semi_diameters) == 3
        and len(thicknesses) == 2
        and all(0.1 <= abs(radius) <= 5000.0 for radius in radii)
        and all(0.1 <= semi_diameter <= 250.0 for semi_diameter in semi_diameters)
        and all(0.0 <= thickness <= 100.0 for thickness in thicknesses)
    )


def _decode_recipe_materials(payload: bytes) -> list[str] | None:
    tokens = [payload[:10].decode("latin1", "ignore").strip(), payload[10:20].decode("latin1", "ignore").strip()]
    if len(tokens) != 2 or not all(_looks_like_glass_code(token) for token in tokens):
        return None
    return tokens


def _looks_like_recipe_optical_constants(values: list[float]) -> bool:
    if len(values) != 4:
        return False
    n1, n2, vd1, vd2 = values
    return (
        1.0 <= n1 <= 2.5
        and 1.0 <= n2 <= 2.5
        and 10.0 <= vd1 <= 100.0
        and 10.0 <= vd2 <= 100.0
    )


def _normalize_recipe_radius(value: float) -> float | str:
    if abs(value) < 1e-9:
        return "inf"
    return value


def _parse_v4_surfaces(lines: list[str]) -> list[LensSurfaceSpec]:
    """Parse the explicit surface/space blocks used by WinLens 4.x SPD files."""
    surfaces: list[LensSurfaceSpec] = []
    pending: dict[str, object] | None = None
    for raw_line in lines:
        values = _parse_csv_line(raw_line)
        if not values:
            continue
        raw_label = values[0]
        label = raw_label.strip()
        lowered = label.casefold()
        if lowered.startswith("surf"):
            radius = _safe_float(values[3] if len(values) > 3 else "")
            semi_diameter = _safe_float(values[9] if len(values) > 9 else "")
            pending = {
                "radius": "inf" if radius in (None, 0.0) else radius,
                "semi_diameter": semi_diameter,
                "comment": label.strip(),
            }
            continue
        if lowered.startswith("space") and pending is not None:
            material = (values[3] if len(values) > 3 else "").strip() or "Air"
            material = "Air" if material.casefold() == "air" else material
            extra_data: dict[str, object] = {}
            material_catalog = (values[4] if len(values) > 4 else "").strip()
            if material_catalog:
                extra_data["material_catalog"] = material_catalog
            surfaces.append(
                LensSurfaceSpec(
                    surface_type="standard",
                    radius=pending["radius"],
                    thickness=_safe_float(values[1] if len(values) > 1 else "") or 0.0,
                    material=material,
                    semi_diameter=pending["semi_diameter"],
                    comment=str(pending["comment"]),
                    extra_data=extra_data,
                )
            )
            pending = None
    return surfaces


def _collect_materials(surfaces: list[LensSurfaceSpec]) -> list[str]:
    seen: set[str] = set()
    materials: list[str] = []
    for surface in surfaces:
        material = surface.material.strip()
        if not material or material.casefold() == "air":
            continue
        normalized = material.upper()
        if normalized in seen:
            continue
        seen.add(normalized)
        materials.append(material)
    return materials


def _extract_stop_diameter(raw_text: str, surfaces: list[LensSurfaceSpec]) -> float | None:
    match = _STOP_RAD_RE.search(raw_text)
    if match:
        return float(match.group(1)) * 2.0
    radii = [
        float(surface.semi_diameter)
        for surface in surfaces
        if isinstance(surface.semi_diameter, (int, float))
    ]
    return max(radii) * 2.0 if radii else None


def _extract_efl(raw_text: str, title: str) -> float | None:
    match = _EFL_RE.search(raw_text)
    if match:
        return float(match.group(1))
    title_match = re.search(r"f[' ]*=\s*([-+]?\d+(?:\.\d+)?)", title, re.IGNORECASE)
    if title_match:
        return float(title_match.group(1))
    return None


def _extract_waveband(raw_text: str) -> list[float]:
    match = _WAVEBAND_RE.search(raw_text)
    if not match:
        return []
    return [float(match.group(index)) for index in range(1, 4)]


def _infer_category(title: str, path: Path) -> str:
    haystack = f"{title} {' '.join(path.parts)}".casefold()
    for needle, category in _CATEGORY_KEYWORDS:
        if needle in haystack:
            return category
    return path.parent.name.replace("_", " ").casefold()


def _should_ignore_winlens_record(record: CatalogLensRecord) -> bool:
    return str(record.category or "").casefold() in _IGNORED_WINLENS_CATEGORIES


def _build_tags(path: Path, version: str, category: str) -> list[str]:
    tags = [
        "winlens",
        f"spd-v{version}" if version else "spd",
        path.parent.name.replace("_", " "),
        category,
    ]
    digit_groups = _PART_DIGITS_RE.findall(path.stem)
    tags.extend(digit_groups)
    return [tag for tag in tags if tag]


def _build_prism_name(section_label: str, variant: str, line_dims: list[float]) -> str:
    dims = " x ".join(_format_decimal(value) for value in line_dims)
    suffix = f"; {dims} mm" if dims else ""
    return f"{section_label} {variant}{suffix}".strip()


def _build_table_tags(*values: object) -> list[str]:
    tags: list[str] = []
    seen: set[str] = set()
    for value in values:
        for token in re.split(r"[^0-9a-zA-Z.+-]+", str(value or "").casefold()):
            cleaned = token.strip()
            if len(cleaned) < 2 or cleaned in seen:
                continue
            seen.add(cleaned)
            tags.append(cleaned)
    return tags


def _infer_table_coating(text: str) -> str | None:
    lowered = text.casefold()
    if "uncoated" in lowered:
        return "Uncoated"
    if "coated" in lowered:
        return "Coated"
    return None


def _float_values(*values: object) -> list[float]:
    numbers: list[float] = []
    for value in values:
        numeric = _safe_float(value)
        if numeric is None:
            continue
        numbers.append(numeric)
    return numbers


def _join_values(*values: str) -> str:
    parts: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = value.strip(" ,")
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        parts.append(cleaned)
    return ", ".join(parts)


def _format_decimal(value: float) -> str:
    return f"{value:.4f}".rstrip("0").rstrip(".")


def _extra_search_blob(values: list[object]) -> str:
    extras = " ".join(str(value) for value in values if str(value).strip())
    return f" {extras.casefold()}" if extras else ""


def _extract_dimension_values(text: str) -> list[float]:
    numbers: list[float] = []
    match = re.search(r"/\s*([0-9.]+(?:x[0-9.]+)*)\s*mm", text, re.IGNORECASE)
    if not match:
        return numbers
    for token in match.group(1).split("x"):
        numeric = _safe_float(token)
        if numeric is None:
            continue
        numbers.append(numeric)
    return numbers


def _extract_first_named_float(pattern: str, text: str) -> float | None:
    match = re.search(pattern, text, re.IGNORECASE)
    if not match:
        return None
    return _safe_float(match.group(1))


def _extract_named_metrics(text: str, names: tuple[str, ...]) -> list[str]:
    metrics: list[str] = []
    for name in names:
        match = re.search(rf"{re.escape(name)}\s*([-+]?\d+(?:\.\d+)?)", text, re.IGNORECASE)
        if match:
            metrics.append(f"{name} {match.group(1)}")
    return metrics


def _build_grin_name(title: str, family_hint: str) -> str:
    if family_hint and family_hint.casefold() not in title.casefold():
        return f"{family_hint} {title}"
    return title


def _is_winlens_family_product_line(text: str) -> bool:
    if not re.search(r"\d{9}", text):
        return False
    lowered = text.casefold()
    return any(keyword in lowered for keyword, _category in _CATEGORY_KEYWORDS) or "doublet" in lowered


def _infer_family_category(title: str) -> str:
    lowered = title.casefold()
    for needle, category in _CATEGORY_KEYWORDS:
        if needle in lowered:
            return category
    if "hyperchromatic doublet" in lowered:
        return "hyperchromatic doublet"
    if "laser-monochromat" in lowered:
        return "laser monochromat"
    return "lens"


def _extract_efl_from_title(title: str) -> float | None:
    explicit = _extract_first_named_float(r"f\s*=\s*([-+]?\d+(?:\.\d+)?)", title)
    if explicit is not None:
        return explicit
    match = _FOCAL_DIAMETER_PAIR_RE.search(title)
    if match:
        return _safe_float(match.group(1))
    return None


def _extract_family_diameter(title: str) -> float | None:
    match = re.search(
        r"f\s*=\s*[-+]?\d+(?:\.\d+)?\s*/\s*([-+]?\d+(?:\.\d+)?)",
        title,
        re.IGNORECASE,
    )
    if match:
        return _safe_float(match.group(1))
    pair_match = _FOCAL_DIAMETER_PAIR_RE.search(title)
    if pair_match:
        return _safe_float(pair_match.group(2))
    return None


def _safe_float(value: object) -> float | None:
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None
