"""Helpers for turning catalog records into insertable surface sequences."""

from __future__ import annotations

import math

from .schema import CatalogLensRecord


def record_to_insert_specs(record: CatalogLensRecord) -> tuple[list[dict], int | None]:
    """Convert a catalog record into generic surface-sequence dicts."""
    sequence: list[dict] = []
    for surface in record.surfaces:
        spec = {
            "surface_type": surface.surface_type,
            "thickness": surface.thickness,
            "material": surface.material,
            "semi_diameter": surface.semi_diameter,
            "comment": surface.comment or f"{record.manufacturer} {record.part_number}",
        }
        if surface.surface_type == "toroidal":
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


def _normalize_value(value):  # noqa: ANN001
    """Convert serialized ``inf`` strings back to floats recursively."""
    if isinstance(value, str) and value.strip().lower() == "inf":
        return math.inf
    if isinstance(value, list):
        return [_normalize_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _normalize_value(item) for key, item in value.items()}
    return value
