"""Plausibility and consistency validation for Optiland design files.

Runs on the raw JSON dict before an :class:`~optiland.optic.Optic` is built,
so structural defects in externally generated files (hand-written, exported,
or AI-drafted) are surfaced — with offered corrections — instead of producing
silently wrong optics or rendering artifacts.

The checks are derived from defects found in real user files:

- ``aperture_exceeds_sag_domain``: a radial aperture wider than the spherical
  cap can be (``r_max > |R| / sqrt(1+k)``) — draws NaN regions and spams
  sqrt warnings.
- ``thickness_position_mismatch``: stored surface positions disagree with the
  stored thickness fields. Positions win on load, so an edited thickness
  silently has no effect.
- ``glass_gap_in_foreign_element``: an unrelated glass surface sits inside a
  grouped element's glass run (e.g. a pinhole mirror stored with a glass
  material inside a cemented doublet), merging elements optically and
  graphically.
- ``stock_part_missing_aperture``: catalog parts without physical apertures
  draw at arbitrary sizes derived from geometry limits.
"""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass, field

_POSITION_TOL = 1e-6


@dataclass
class ValidationFinding:
    """One validation finding, optionally carrying an applicable fix."""

    code: str
    severity: str  # "error" | "warning" | "info"
    surface_index: int | None
    message: str
    fix_description: str | None = None
    apply_by_default: bool = False
    fix_data: dict = field(default_factory=dict)

    @property
    def fixable(self) -> bool:
        return self.fix_description is not None


def _surfaces(data: dict) -> list[dict]:
    group = data.get("surface_group")
    if not isinstance(group, dict):
        return []
    surfaces = group.get("surfaces")
    return surfaces if isinstance(surfaces, list) else []


def _surface_z(surface: dict) -> float | None:
    try:
        z = surface["geometry"]["cs"]["z"]
    except (KeyError, TypeError):
        return None
    try:
        z = float(z)
    except (TypeError, ValueError):
        return None
    return z if math.isfinite(z) else None


def _surface_label(surface: dict, index: int) -> str:
    comment = str(surface.get("comment") or "").strip()
    return f"surface {index}" + (f" ({comment})" if comment else "")


def _is_glass_material(surface: dict) -> bool:
    """Whether the medium after *surface* is glass-like (not air, not mirror)."""
    model = surface.get("interaction_model")
    if isinstance(model, dict) and model.get("is_reflective"):
        return False
    material = surface.get("material_post")
    if not isinstance(material, dict):
        return False
    if material.get("type") == "IdealMaterial":
        try:
            return float(material.get("index", 1.0)) > 1.0001
        except (TypeError, ValueError):
            return False
    # Named catalog materials (type "Material" etc.) count as glass.
    return bool(material.get("name"))


def _air_material() -> dict:
    return {
        "type": "IdealMaterial",
        "propagation_model": {"class": "HomogeneousPropagation"},
        "index": 1.0,
        "absorp": 0.0,
    }


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


def _check_aperture_sag_domain(surfaces: list[dict]) -> list[ValidationFinding]:
    findings = []
    for i, surface in enumerate(surfaces):
        geometry = surface.get("geometry")
        aperture = surface.get("aperture")
        if not isinstance(geometry, dict) or not isinstance(aperture, dict):
            continue
        if geometry.get("type") not in ("StandardGeometry", "EvenAsphere"):
            continue
        try:
            radius = float(geometry.get("radius", float("inf")))
            conic = float(geometry.get("conic", 0.0))
            r_max = float(aperture.get("r_max"))
        except (TypeError, ValueError):
            continue
        if not math.isfinite(radius) or (1.0 + conic) <= 0 or not math.isfinite(r_max):
            continue
        domain = abs(radius) / math.sqrt(1.0 + conic)
        if r_max <= domain:
            continue
        fixed_r = math.floor(domain * 0.99 * 1e4) / 1e4
        findings.append(
            ValidationFinding(
                code="aperture_exceeds_sag_domain",
                severity="error",
                surface_index=i,
                message=(
                    f"{_surface_label(surface, i)}: aperture r_max={r_max:g} mm "
                    f"exceeds the surface's geometric limit of {domain:.4f} mm "
                    f"(|R|={abs(radius):g}, k={conic:g}) — the cap cannot be "
                    "that wide; drawing produces undefined (NaN) regions."
                ),
                fix_description=f"Clamp aperture r_max to {fixed_r:g} mm.",
                apply_by_default=True,
                fix_data={"r_max": fixed_r},
            )
        )
    return findings


def _check_thickness_positions(surfaces: list[dict]) -> list[ValidationFinding]:
    findings = []
    for i in range(len(surfaces) - 1):
        z_here, z_next = _surface_z(surfaces[i]), _surface_z(surfaces[i + 1])
        if z_here is None or z_next is None:
            continue
        try:
            thickness = float(surfaces[i].get("thickness"))
        except (TypeError, ValueError):
            continue
        if not math.isfinite(thickness):
            continue
        gap = z_next - z_here
        if abs(gap - thickness) <= _POSITION_TOL:
            continue
        findings.append(
            ValidationFinding(
                code="thickness_position_mismatch",
                severity="error",
                surface_index=i,
                message=(
                    f"{_surface_label(surfaces[i], i)}: stored thickness "
                    f"{thickness:g} mm does not match the stored surface "
                    f"positions (gap {gap:g} mm). Positions win on load, so "
                    "the thickness value silently has no effect."
                ),
                fix_description=(
                    "Recompute all surface positions from the thickness values."
                ),
                apply_by_default=True,
            )
        )
    return findings


def _check_glass_gap_in_foreign_element(
    surfaces: list[dict],
) -> list[ValidationFinding]:
    findings = []
    for i in range(1, len(surfaces) - 1):
        surface = surfaces[i]
        if not _is_glass_material(surface):
            continue
        prev_group = surfaces[i - 1].get("group_id")
        next_group = surfaces[i + 1].get("group_id")
        own_group = surface.get("group_id")
        if not prev_group or prev_group != next_group or own_group == prev_group:
            continue
        group_name = surfaces[i - 1].get("group_name") or prev_group
        material = surface.get("material_post", {})
        material_name = material.get("name") or f"n={material.get('index')}"
        findings.append(
            ValidationFinding(
                code="glass_gap_in_foreign_element",
                severity="warning",
                surface_index=i,
                message=(
                    f"{_surface_label(surface, i)}: sits inside the element "
                    f"'{group_name}' with glass material ({material_name}). "
                    "This merges the element into one solid glass block — "
                    "likely the material should be Air."
                ),
                fix_description="Set this surface's material to Air.",
                apply_by_default=False,
            )
        )
    return findings


def _check_stock_part_apertures(surfaces: list[dict]) -> list[ValidationFinding]:
    findings = []
    reported_groups: set[str] = set()
    for i, surface in enumerate(surfaces):
        if surface.get("group_role") != "stock_part":
            continue
        if isinstance(surface.get("aperture"), dict):
            continue
        group = str(surface.get("group_id") or f"__surface_{i}")
        if group in reported_groups:
            continue
        reported_groups.add(group)
        name = surface.get("group_name") or _surface_label(surface, i)
        findings.append(
            ValidationFinding(
                code="stock_part_missing_aperture",
                severity="info",
                surface_index=i,
                message=(
                    f"Stock part '{name}' has no physical aperture — the 2D "
                    "layout will draw it at an arbitrary size derived from "
                    "its geometry limits, not its real diameter."
                ),
            )
        )
    return findings


def validate_design(data: dict) -> list[ValidationFinding]:
    """Validate a raw design dict and return all findings (may be empty)."""
    surfaces = _surfaces(data)
    if not surfaces:
        return []
    findings: list[ValidationFinding] = []
    findings.extend(_check_aperture_sag_domain(surfaces))
    findings.extend(_check_thickness_positions(surfaces))
    findings.extend(_check_glass_gap_in_foreign_element(surfaces))
    findings.extend(_check_stock_part_apertures(surfaces))
    return findings


# ---------------------------------------------------------------------------
# Fixes
# ---------------------------------------------------------------------------


def apply_design_fixes(data: dict, findings: list[ValidationFinding]) -> dict:
    """Return a copy of *data* with the selected findings' fixes applied."""
    fixed = copy.deepcopy(data)
    surfaces = _surfaces(fixed)
    recompute_positions = False
    for finding in findings:
        if not finding.fixable:
            continue
        if finding.code == "aperture_exceeds_sag_domain":
            surface = surfaces[finding.surface_index]
            surface["aperture"]["r_max"] = finding.fix_data["r_max"]
        elif finding.code == "thickness_position_mismatch":
            recompute_positions = True
        elif finding.code == "glass_gap_in_foreign_element":
            surfaces[finding.surface_index]["material_post"] = _air_material()
    if recompute_positions:
        _recompute_positions_from_thickness(surfaces)
    return fixed


def _recompute_positions_from_thickness(surfaces: list[dict]) -> None:
    """Rewrite every finite surface z from the thickness chain.

    The first surface with a finite position anchors the chain; the object
    surface (typically at -inf) is left untouched.
    """
    anchor = None
    for i, surface in enumerate(surfaces):
        if _surface_z(surface) is not None:
            anchor = i
            break
    if anchor is None:
        return
    z = _surface_z(surfaces[anchor])
    for i in range(anchor, len(surfaces) - 1):
        try:
            thickness = float(surfaces[i].get("thickness"))
        except (TypeError, ValueError):
            thickness = None
        z_next = _surface_z(surfaces[i + 1])
        if thickness is None or not math.isfinite(thickness):
            # keep the existing gap when no usable thickness is stored
            if z_next is None:
                return
            z = z_next
            continue
        z = z + thickness
        if z_next is not None:
            surfaces[i + 1]["geometry"]["cs"]["z"] = z
