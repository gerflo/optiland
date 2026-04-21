"""Base helpers for catalog importer implementations."""

from __future__ import annotations

import json
import math
import re
from abc import ABC
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from optiland.fileio import load_zemax_file
from optiland.materials import IdealMaterial

from ..schema import CatalogLensRecord, CatalogSource, LensSurfaceSpec

_READ_ENCODINGS = ("utf-16", "utf-8", "iso-8859-1")
_CATEGORY_KEYWORDS = (
    ("cylindrical", "cylindrical"),
    ("achromat", "achromat"),
    ("doublet", "doublet"),
    ("triplet", "triplet"),
    ("plano-convex", "plano-convex"),
    ("planoconvex", "plano-convex"),
    ("plano-concave", "plano-concave"),
    ("planoconcave", "plano-concave"),
    ("bi-convex", "bi-convex"),
    ("biconvex", "bi-convex"),
    ("bi-concave", "bi-concave"),
    ("biconcave", "bi-concave"),
    ("meniscus", "meniscus"),
    ("aspheric", "asphere"),
    ("asphere", "asphere"),
    ("tube lens", "tube lens"),
    ("scan lens", "scan lens"),
    ("f-theta", "f-theta"),
)
_THORLABS_PART_RE = re.compile(r"\b[A-Z]{1,6}\d{2,}[A-Z0-9-]*\b")
_EDMUND_PART_RE = re.compile(r"\b(?:\d{2}-\d{3}|\d{5})\b")
_FOCAL_MM_RE = re.compile(r"\bf\s*=\s*([0-9]+(?:\.[0-9]+)?)\s*mm\b", re.IGNORECASE)
_DIAMETER_MM_RE = re.compile(
    r"(?:[Øø]|diameter\s*=?|dia\.\s*=?|d\s*=)\s*([0-9]+(?:\.[0-9]+)?)\s*mm\b",
    re.IGNORECASE,
)
_ARC_RE = re.compile(r"\bARC:\s*([^,]+)", re.IGNORECASE)
_AR_COATED_RE = re.compile(r"\bAR(?:-|\s)?Coated:\s*([^,]+)", re.IGNORECASE)


class CatalogImporter(ABC):
    """Abstract base class for vendor-specific catalog importers."""

    manufacturer: str = ""
    catalog_url: str | None = None

    def import_file(self, path: str) -> list[CatalogLensRecord]:
        """Return normalized records from *path*."""
        file_path = Path(path)
        suffix = file_path.suffix.lower()
        if suffix == ".json":
            return load_normalized_json_records(path, self.manufacturer)
        if suffix == ".zmx":
            return [
                load_zemax_catalog_record(
                    path,
                    manufacturer=self.manufacturer,
                    fallback_catalog_url=self.catalog_url,
                    product_url=self.build_product_url,
                )
            ]
        raise ValueError(
            f"Unsupported catalog file: {file_path.name}. "
            "Supported formats are normalized JSON (*.json) and Zemax (*.zmx)."
        )

    def build_product_url(self, part_number: str) -> str | None:
        """Return a best-effort vendor URL for *part_number* if available."""
        return self.catalog_url


def load_normalized_json_records(path: str, manufacturer: str) -> list[CatalogLensRecord]:
    """Load Optiland-normalized catalog records from a JSON file."""
    file_path = Path(path)
    payload = json.loads(file_path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        raw_records = payload.get("records", [])
    elif isinstance(payload, list):
        raw_records = payload
    else:
        raw_records = []

    imported_at = datetime.now(timezone.utc).isoformat()
    records: list[CatalogLensRecord] = []
    for item in raw_records:
        if not isinstance(item, dict):
            continue
        item.setdefault("manufacturer", manufacturer)
        item.setdefault(
            "source",
            {
                "manufacturer": manufacturer,
                "source_type": "json",
                "source_path": str(file_path),
                "source_url": None,
                "imported_at": imported_at,
                "license_note": "Imported from a user-provided catalog file.",
                "version_hint": None,
            },
        )
        record = CatalogLensRecord.from_dict(item)
        if not record.catalog_id:
            record.catalog_id = f"{manufacturer.lower()}:{record.part_number.lower()}"
        records.append(record)
    return records


def load_zemax_catalog_record(
    path: str,
    manufacturer: str,
    fallback_catalog_url: str | None = None,
    product_url=None,  # noqa: ANN001
) -> CatalogLensRecord:
    """Load a single stock-lens record from a Zemax ``.zmx`` file."""
    file_path = Path(path)
    raw_text = _read_text_with_fallback(file_path)
    meta = _parse_zemax_text_metadata(raw_text)
    optic = load_zemax_file(str(file_path))

    part_number = _infer_part_number(manufacturer, meta, file_path)
    product_name = meta["name"] or part_number or file_path.stem
    surface_specs, stop_offset = _extract_surface_specs(
        optic, meta["surface_comments"], manufacturer, part_number
    )
    if not surface_specs:
        raise ValueError(
            f"No insertable optical surfaces found in {file_path.name}. "
            "The catalog importer expects a sequential component prescription."
        )

    diameter_mm = _infer_diameter_mm(product_name, surface_specs)
    bfl_mm = _safe_positive_float(surface_specs[-1].thickness)
    center_thickness_mm = _infer_center_thickness(surface_specs)
    material_summary = _build_material_summary(surface_specs)
    coating = _infer_coating(product_name, meta["surface_coatings"])
    wavelengths = [float(wavelength.value) for wavelength in optic.wavelengths.wavelengths]
    source_url = (
        product_url(part_number)
        if callable(product_url) and part_number
        else fallback_catalog_url
    )
    tags = _build_tags(product_name, material_summary, coating)

    return CatalogLensRecord(
        catalog_id=f"{manufacturer.lower()}:{part_number.lower()}",
        manufacturer=manufacturer,
        part_number=part_number,
        product_name=product_name,
        category=_infer_category(product_name),
        url=source_url,
        efl_mm=_extract_named_float(_FOCAL_MM_RE, product_name),
        bfl_mm=bfl_mm,
        diameter_mm=diameter_mm,
        center_thickness_mm=center_thickness_mm,
        material_summary=material_summary,
        coating=coating,
        wavelength_min_um=min(wavelengths) if wavelengths else None,
        wavelength_max_um=max(wavelengths) if wavelengths else None,
        surfaces=surface_specs,
        stop_surface_offset=stop_offset,
        tags=tags,
        source=CatalogSource(
            manufacturer=manufacturer,
            source_type="zemax",
            source_path=str(file_path),
            source_url=source_url,
            imported_at=datetime.now(timezone.utc).isoformat(),
            license_note=(
                "Imported from a user-provided Zemax stock-lens file. "
                "Review vendor license terms before redistribution."
            ),
            version_hint=file_path.name,
        ),
    )


def _read_text_with_fallback(path: Path) -> str:
    for encoding in _READ_ENCODINGS:
        try:
            return path.read_text(encoding=encoding)
        except UnicodeError:
            continue
    raise ValueError(f"Could not decode catalog file: {path}")


def _parse_zemax_text_metadata(text: str) -> dict[str, Any]:
    metadata = {
        "name": "",
        "surface_comments": {},
        "surface_coatings": {},
    }
    current_surface: int | None = None
    for line in text.splitlines():
        tokens = line.split()
        if not tokens:
            continue
        operand = tokens[0]
        if operand == "NAME":
            metadata["name"] = " ".join(tokens[1:]).strip()
        elif operand == "SURF" and len(tokens) > 1:
            try:
                current_surface = int(tokens[1])
            except ValueError:
                current_surface = None
        elif operand == "COMM" and current_surface is not None:
            metadata["surface_comments"][current_surface] = " ".join(tokens[1:]).strip()
        elif operand == "COAT" and current_surface is not None and len(tokens) > 1:
            metadata["surface_coatings"][current_surface] = tokens[1].strip()
    return metadata


def _infer_part_number(
    manufacturer: str,
    metadata: dict[str, Any],
    path: Path,
) -> str:
    name = str(metadata.get("name", "")).strip()
    comments = [
        str(comment).strip()
        for _idx, comment in sorted(metadata.get("surface_comments", {}).items())
        if comment
    ]
    for candidate in (name, *comments, path.stem):
        part_number = _match_part_number(manufacturer, candidate)
        if part_number:
            return part_number
    return path.stem.replace("_", "-").strip()


def _match_part_number(manufacturer: str, text: str) -> str:
    if not text:
        return ""
    clean = text.replace("#", " ").strip()
    if manufacturer.casefold() == "thorlabs":
        match = _THORLABS_PART_RE.search(clean)
        return match.group(0) if match else ""
    if manufacturer.casefold() == "edmund":
        match = _EDMUND_PART_RE.search(clean)
        return match.group(0) if match else ""
    return ""


def _extract_surface_specs(
    optic,
    surface_comments: dict[int, str],
    manufacturer: str,
    part_number: str,
) -> tuple[list[LensSurfaceSpec], int | None]:
    specs: list[LensSurfaceSpec] = []
    stop_offset: int | None = None
    for surface_index in range(1, max(optic.surfaces.num_surfaces - 1, 1)):
        surface = optic.surfaces[surface_index]
        surface_type = str(surface.surface_type or "standard")
        radius, conic, extra_data = _extract_geometry_data(surface)
        thickness = _extract_thickness(optic, surface_index)
        material = _material_name(surface)
        semi_diameter = _extract_semi_diameter(surface)
        comment = (
            surface_comments.get(surface_index)
            or surface.comment
            or f"{manufacturer} {part_number} S{len(specs) + 1}"
        )
        specs.append(
            LensSurfaceSpec(
                surface_type=surface_type,
                radius=radius,
                thickness=thickness,
                material=material,
                conic=conic,
                semi_diameter=semi_diameter,
                comment=comment,
                extra_data=extra_data,
            )
        )
        if getattr(surface, "is_stop", False):
            stop_offset = len(specs) - 1
    return specs, stop_offset


def _extract_geometry_data(surface) -> tuple[float | str, float, dict[str, Any]]:  # noqa: ANN001
    geometry = surface.geometry
    surface_type = str(surface.surface_type or "standard")
    extra_data: dict[str, Any] = {}

    if surface_type == "toroidal":
        radius = _normalize_scalar(getattr(geometry, "R_yz", math.inf))
        conic = float(getattr(geometry, "k_yz", 0.0))
        extra_data["radius_x"] = _normalize_scalar(getattr(geometry, "R_rot", math.inf))
        coeffs = list(getattr(geometry, "coeffs_poly_y", []))
        if coeffs:
            extra_data["toroidal_coeffs_poly_y"] = coeffs
        return radius, conic, extra_data

    if surface_type == "biconic":
        radius = _normalize_scalar(getattr(geometry, "Ry", math.inf))
        conic = float(getattr(geometry, "ky", 0.0))
        extra_data["radius_x"] = _normalize_scalar(getattr(geometry, "Rx", math.inf))
        extra_data["conic_x"] = float(getattr(geometry, "kx", 0.0))
        return radius, conic, extra_data

    radius = _normalize_scalar(getattr(geometry, "radius", math.inf))
    conic = float(getattr(geometry, "k", 0.0))
    coeffs = list(getattr(geometry, "coefficients", getattr(geometry, "c", [])))
    if coeffs:
        extra_data["coefficients"] = coeffs
    return radius, conic, extra_data


def _extract_thickness(optic, surface_index: int) -> float:
    thickness = optic.surfaces.get_thickness(surface_index)
    try:
        value = float(thickness[0])
    except (TypeError, IndexError, ValueError):
        value = float(thickness)
    if math.isinf(value) or math.isnan(value):
        return 0.0
    return value


def _material_name(surface) -> str:  # noqa: ANN001
    if surface.interaction_model.is_reflective:
        return "Mirror"
    material = surface.material_post
    if isinstance(material, IdealMaterial):
        try:
            index = float(material.n(0.55))
        except Exception:  # noqa: BLE001
            index = 1.0
        return "Air" if math.isclose(index, 1.0, rel_tol=1e-6, abs_tol=1e-6) else f"{index:.4f}"
    return str(getattr(material, "name", "Air"))


def _extract_semi_diameter(surface):  # noqa: ANN001
    aperture = getattr(surface, "aperture", None)
    if aperture is not None and hasattr(aperture, "r_max"):
        return float(aperture.r_max)
    semi_aperture = getattr(surface, "semi_aperture", None)
    if semi_aperture not in (None, ""):
        return float(semi_aperture)
    return None


def _infer_diameter_mm(product_name: str, surfaces: list[LensSurfaceSpec]) -> float | None:
    named = _extract_named_float(_DIAMETER_MM_RE, product_name)
    if named is not None:
        return named
    semi_diameters = [
        float(surface.semi_diameter)
        for surface in surfaces
        if surface.semi_diameter not in (None, "", "Auto")
    ]
    if semi_diameters:
        return max(semi_diameters) * 2.0
    return None


def _infer_center_thickness(surfaces: list[LensSurfaceSpec]) -> float | None:
    glass_thicknesses = [
        surface.thickness
        for surface in surfaces
        if surface.material.casefold() not in {"air", "mirror"}
    ]
    if glass_thicknesses:
        return float(sum(glass_thicknesses))
    return _safe_positive_float(surfaces[0].thickness if surfaces else None)


def _build_material_summary(surfaces: list[LensSurfaceSpec]) -> str | None:
    materials: list[str] = []
    for surface in surfaces:
        material = surface.material.strip()
        if not material or material.casefold() in {"air", "mirror"}:
            continue
        if material not in materials:
            materials.append(material)
    return ", ".join(materials) if materials else None


def _infer_coating(product_name: str, coatings: dict[int, str]) -> str | None:
    for pattern in (_ARC_RE, _AR_COATED_RE):
        match = pattern.search(product_name)
        if match:
            return match.group(1).strip()
    unique_codes = [
        code
        for _surface_index, code in sorted(coatings.items())
        if code and code.upper() not in {"", "NONE"}
    ]
    if unique_codes:
        return ", ".join(dict.fromkeys(unique_codes))
    return None


def _infer_category(product_name: str) -> str:
    lowered = product_name.casefold()
    for needle, category in _CATEGORY_KEYWORDS:
        if needle in lowered:
            return category
    return ""


def _build_tags(product_name: str, material_summary: str | None, coating: str | None) -> list[str]:
    tags = {_infer_category(product_name)}
    if material_summary:
        tags.update(
            part.strip().casefold()
            for part in material_summary.split(",")
            if part.strip()
        )
    if coating:
        tags.add(coating.casefold())
    tags.discard("")
    return sorted(tags)


def _extract_named_float(pattern: re.Pattern[str], text: str) -> float | None:
    match = pattern.search(text)
    if not match:
        return None
    try:
        return float(match.group(1))
    except (TypeError, ValueError):
        return None


def _safe_positive_float(value) -> float | None:  # noqa: ANN001
    if value in (None, ""):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(numeric) or math.isinf(numeric) or numeric < 0:
        return None
    return numeric


def _normalize_scalar(value):  # noqa: ANN001
    if isinstance(value, str):
        try:
            value = float(value)
        except ValueError:
            return value
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return value
    return "inf" if math.isinf(numeric) else numeric
