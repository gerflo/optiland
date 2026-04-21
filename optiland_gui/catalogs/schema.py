"""Schema objects for locally cached stock-lens catalogs."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class CatalogSource:
    """Metadata about where a catalog record came from."""

    manufacturer: str
    source_type: str
    source_path: str | None = None
    source_url: str | None = None
    imported_at: str = ""
    license_note: str | None = None
    version_hint: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CatalogSource":
        return cls(
            manufacturer=str(data.get("manufacturer", "")),
            source_type=str(data.get("source_type", "unknown")),
            source_path=data.get("source_path"),
            source_url=data.get("source_url"),
            imported_at=str(data.get("imported_at", "")),
            license_note=data.get("license_note"),
            version_hint=data.get("version_hint"),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class LensSurfaceSpec:
    """A single surface description derived from a stock-lens entry."""

    surface_type: str = "standard"
    radius: float | str = "inf"
    thickness: float = 0.0
    material: str = "Air"
    conic: float = 0.0
    semi_diameter: float | str | None = None
    comment: str | None = None
    extra_data: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LensSurfaceSpec":
        return cls(
            surface_type=str(data.get("surface_type", "standard")),
            radius=data.get("radius", "inf"),
            thickness=float(data.get("thickness", 0.0)),
            material=str(data.get("material", "Air")),
            conic=float(data.get("conic", 0.0)),
            semi_diameter=data.get("semi_diameter"),
            comment=data.get("comment"),
            extra_data=(
                dict(data.get("extra_data", {}))
                if isinstance(data.get("extra_data"), dict)
                else {}
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CatalogLensRecord:
    """Normalized stock-lens record used by the GUI catalog browser."""

    catalog_id: str
    manufacturer: str
    part_number: str
    product_name: str
    category: str = ""
    url: str | None = None
    efl_mm: float | None = None
    bfl_mm: float | None = None
    diameter_mm: float | None = None
    center_thickness_mm: float | None = None
    edge_thickness_mm: float | None = None
    material_summary: str | None = None
    coating: str | None = None
    availability_status: str | None = None
    wavelength_min_um: float | None = None
    wavelength_max_um: float | None = None
    surfaces: list[LensSurfaceSpec] = field(default_factory=list)
    stop_surface_offset: int | None = None
    tags: list[str] = field(default_factory=list)
    search_blob: str = ""
    source: CatalogSource = field(
        default_factory=lambda: CatalogSource(
            manufacturer="",
            source_type="unknown",
        )
    )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CatalogLensRecord":
        source_data = data.get("source", {}) if isinstance(data.get("source"), dict) else {}
        surfaces_data = data.get("surfaces", [])
        manufacturer = str(data.get("manufacturer", "")).strip()
        part_number = str(data.get("part_number", "")).strip()
        catalog_id = str(data.get("catalog_id") or f"{manufacturer.lower()}:{part_number.lower()}")
        record = cls(
            catalog_id=catalog_id,
            manufacturer=manufacturer,
            part_number=part_number,
            product_name=str(data.get("product_name", part_number)),
            category=str(data.get("category", "")),
            url=data.get("url"),
            efl_mm=_float_or_none(data.get("efl_mm")),
            bfl_mm=_float_or_none(data.get("bfl_mm")),
            diameter_mm=_float_or_none(data.get("diameter_mm")),
            center_thickness_mm=_float_or_none(data.get("center_thickness_mm")),
            edge_thickness_mm=_float_or_none(data.get("edge_thickness_mm")),
            material_summary=data.get("material_summary"),
            coating=data.get("coating"),
            availability_status=data.get("availability_status"),
            wavelength_min_um=_float_or_none(data.get("wavelength_min_um")),
            wavelength_max_um=_float_or_none(data.get("wavelength_max_um")),
            surfaces=[
                LensSurfaceSpec.from_dict(item)
                for item in surfaces_data
                if isinstance(item, dict)
            ],
            stop_surface_offset=_int_or_none(data.get("stop_surface_offset")),
            tags=[str(tag) for tag in data.get("tags", [])],
            search_blob=str(data.get("search_blob", "")),
            source=CatalogSource.from_dict(source_data),
        )
        if not record.search_blob:
            record.search_blob = record.build_search_blob()
        return record

    def build_search_blob(self) -> str:
        """Build a normalized full-text blob for simple in-memory searching."""
        tokens = [
            self.manufacturer,
            self.part_number,
            self.product_name,
            self.category,
            self.material_summary or "",
            self.coating or "",
            self.availability_status or "",
            " ".join(self.tags),
        ]
        return " ".join(token for token in tokens if token).casefold()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["source"] = self.source.to_dict()
        payload["surfaces"] = [surface.to_dict() for surface in self.surfaces]
        return payload

    def to_summary_dict(self) -> dict[str, Any]:
        """Return a GUI-friendly summary payload for search results."""
        return {
            "catalog_id": self.catalog_id,
            "manufacturer": self.manufacturer,
            "part_number": self.part_number,
            "product_name": self.product_name,
            "category": self.category,
            "efl_mm": self.efl_mm,
            "diameter_mm": self.diameter_mm,
            "material_summary": self.material_summary,
            "coating": self.coating,
            "availability_status": self.availability_status,
            "surface_count": len(self.surfaces),
        }


def _float_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
