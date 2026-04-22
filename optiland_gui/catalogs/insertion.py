"""Helpers for turning catalog records into insertable surface sequences."""

from __future__ import annotations

import math
import re

from .schema import CatalogLensRecord


def record_to_insert_specs(record: CatalogLensRecord) -> tuple[list[dict], int | None]:
    """Convert a catalog record into generic surface-sequence dicts."""
    sequence: list[dict] = []
    for surface in record.surfaces:
        formatted_comment = _format_catalog_surface_comment(record.part_number, surface.comment)
        spec = {
            "surface_type": surface.surface_type,
            "thickness": surface.thickness,
            "material": surface.material,
            "semi_diameter": surface.semi_diameter,
            "comment": formatted_comment,
        }
        material_reference = str(
            surface.extra_data.get("material_catalog", "")
        ).strip()
        if material_reference:
            spec["material_reference"] = material_reference
        if surface.surface_type == "paraxial":
            pass
        elif surface.surface_type == "toroidal":
            spec["radius_y"] = _normalize_value(surface.radius)
            spec["conic"] = surface.conic
        elif surface.surface_type == "biconic":
            spec["radius_y"] = _normalize_value(surface.radius)
            spec["conic_y"] = surface.conic
        else:
            spec["radius"] = _normalize_value(surface.radius)
            spec["conic"] = surface.conic
        for key, value in surface.extra_data.items():
            spec[key] = _normalize_value(value)
        sequence.append(spec)
    return sequence, record.stop_surface_offset


def _format_catalog_surface_comment(part_number: str, comment: str | None) -> str:
    """Build a compact Lens Editor comment for inserted catalog surfaces."""
    part = str(part_number or "").strip()
    label = str(comment or "").strip()
    if not label:
        return part
    short_label = label
    match = re.search(r"\bSurf(?:ace)?\s*(\d+)\b", label, re.IGNORECASE)
    if match:
        short_label = f"S{match.group(1)}"
    return f"{part} ({short_label})" if part else short_label


def _normalize_value(value):  # noqa: ANN001
    """Convert serialized ``inf`` strings back to floats recursively."""
    if isinstance(value, str) and value.strip().lower() == "inf":
        return math.inf
    if isinstance(value, list):
        return [_normalize_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _normalize_value(item) for key, item in value.items()}
    return value
