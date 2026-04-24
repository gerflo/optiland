"""Surface CRUD and geometry service for the Optiland GUI.

Handles all surface-related operations: reading/writing surface data for the
Lens Data Editor, adding/removing surfaces, changing surface types, and
extracting/applying extra geometry parameters from the surface properties box.
"""

from __future__ import annotations

import ast
import copy
import logging
import uuid
from contextlib import suppress

import optiland.backend as be
from optiland.geometries.biconic import BiconicGeometry
from optiland.materials import IdealMaterial
from optiland.materials import Material as OptilandMaterial
from optiland.physical_apertures import DifferenceAperture, RadialAperture
from optiland.physical_apertures.radial import configure_aperture
from optiland.surfaces.standard_surface import Surface
from optiland.surfaces.factories.geometry_factory import (
    GeometryFactory,
    config_registry,
)

logger = logging.getLogger(__name__)


class SurfaceService:
    """Manages surface CRUD, type conversions, and geometry parameter I/O.

    This service encapsulates every operation that reads or modifies individual
    surfaces in the active :class:`~optiland.optic.Optic` instance.

    Args:
        connector: The :class:`~optiland_gui.optiland_connector.OptilandConnector`
            instance that owns this service.
    """

    AVAILABLE_SURFACE_TYPES: list[str] = [
        "standard",
        "paraxial",
        "biconic",
        "chebyshev",
        "even_asphere",
        "odd_asphere",
        "polynomial",
        "toroidal",
        "zernike",
    ]

    # Map for EXTRA parameters that appear ONLY in the properties box.
    EXTRA_PARAM_MAP: dict[str, dict[str, str]] = {
        "BiconicGeometry": {
            "Radius X": "Rx",
            "Conic X": "kx",
        },
        "ChebyshevPolynomialGeometry": {
            "Coefficients": "c",
            "Norm X": "norm_x",
            "Norm Y": "norm_y",
        },
        "EvenAsphere": {"Coefficients": "coefficients"},
        "OddAsphere": {"Coefficients": "coefficients"},
        "PolynomialGeometry": {"Coefficients": "c"},
        "ToroidalGeometry": {
            "Radius of Rotation (XZ)": "R_rot",
            "Coefficients YZ": "coeffs_poly_y",
        },
        "ZernikePolynomialGeometry": {
            "Coefficients": "c",
            "Normalization Radius": "norm_radius",
        },
    }

    def __init__(self, connector: object) -> None:
        self._connector = connector

    # ------------------------------------------------------------------
    # Column header helpers
    # ------------------------------------------------------------------

    def get_column_headers(self, row: int = -1) -> list[str]:
        """Return column headers, dynamically adjusted for the selected row.

        Args:
            row: LDE row index. Pass ``-1`` (default) for the generic headers.

        Returns:
            A list of seven header strings corresponding to the LDE columns.
        """
        # Column index constants are accessed through the connector for
        # backward compatibility.
        c = self._connector
        headers = [
            "Type",
            "Comment",
            "Radius",
            "Thickness",
            "Material",
            "Conic",
            "Semi-Diameter",
        ]
        if not (0 <= row < self.get_surface_count()):
            return headers

        surface = self._connector._optic.surfaces.surfaces[row]
        if surface.surface_type == "paraxial":
            headers[c.COL_RADIUS] = "Focal Length"
            headers[c.COL_CONIC] = "N/A"
        elif surface.surface_type == "toroidal":
            headers[c.COL_RADIUS] = "Radius YZ"
            headers[c.COL_CONIC] = "Conic YZ"
        elif surface.surface_type == "biconic":
            headers[c.COL_RADIUS] = "Radius Y"
            headers[c.COL_CONIC] = "Conic Y"
        return headers

    # ------------------------------------------------------------------
    # Surface count / type queries
    # ------------------------------------------------------------------

    def get_surface_count(self) -> int:
        """Return the number of surfaces in the active optic.

        Returns:
            The surface count, or ``0`` if no optic is available.
        """
        optic = self._connector._optic
        return optic.surfaces.num_surfaces if optic and optic.surfaces else 0

    def get_geometry_types(self) -> list[str]:
        """Return all geometry type keys registered with :class:`GeometryFactory`.

        Queries ``config_registry`` from the geometry factory module so that
        newly-added geometry types are discovered automatically without
        updating any hard-coded list.

        Returns:
            A sorted list of geometry type identifier strings.
        """
        return sorted(config_registry.keys())

    def get_available_surface_types(self) -> list[str]:
        """Return the list of surface type strings the GUI supports.

        Delegates to :meth:`get_geometry_types` so the dropdown is always
        in sync with what :class:`GeometryFactory` can create.

        Returns:
            A list of surface type identifier strings.
        """
        return self.get_geometry_types()

    def get_surface_type_info(self, row: int) -> dict:
        """Return display metadata for a surface row.

        Args:
            row: LDE row index (0-based).

        Returns:
            A dict with keys ``display_text`` (str), ``is_changeable`` (bool),
            and optionally ``has_extra_params`` (bool).
        """
        if not (0 <= row < self.get_surface_count()):
            return {"display_text": "Error", "is_changeable": False}
        surface = self._connector._optic.surfaces.surfaces[row]
        if row == 0:
            return {"display_text": "Object", "is_changeable": False}
        if row == self.get_surface_count() - 1:
            return {"display_text": "Image", "is_changeable": False}
        base_type = surface.surface_type or "Standard"
        display_text = (
            f"Stop ({base_type.title()})" if surface.is_stop else base_type.title()
        )
        has_extra_params = bool(self.get_surface_geometry_params(row))
        return {
            "display_text": display_text,
            "is_changeable": True,
            "has_extra_params": has_extra_params,
        }

    # ------------------------------------------------------------------
    # Read helpers (private)
    # ------------------------------------------------------------------

    def _get_safe_primary_wavelength_value(self) -> float:
        """Return the primary wavelength in micrometres, adding one if absent.

        Returns:
            The primary wavelength value in micrometres.
        """
        optic = self._connector._optic
        default = self._connector.DEFAULT_WAVELENGTH_UM
        if optic.wavelengths.num_wavelengths > 0:
            primary_idx = optic.wavelengths.primary_index
            if primary_idx is not None:
                try:
                    return optic.wavelengths.wavelengths[primary_idx].value
                except IndexError:
                    pass
            optic.wavelengths.wavelengths[0].is_primary = True
            return optic.wavelengths.wavelengths[0].value
        optic.wavelengths.add(default, is_primary=True, unit="um")
        optic.updater.update()
        return default

    def _get_material_data(self, surface: object) -> str:
        """Return the material label for *surface*.

        Args:
            surface: A surface object from the surface group.

        Returns:
            A human-readable material string.
        """
        if surface.interaction_model.is_reflective:
            return "Mirror"
        mat = surface.material_post
        if isinstance(mat, IdealMaterial):
            n = mat.n(self._get_safe_primary_wavelength_value())
            return "Air" if be.isclose(n, 1.0) else f"Ideal n={n:.4f}"
        return mat.name if isinstance(mat, OptilandMaterial) else "Unknown"

    def _get_semi_diameter_data(self, surface: object) -> str:
        """Return the semi-diameter label for *surface*.

        Args:
            surface: A surface object from the surface group.

        Returns:
            A formatted semi-diameter string, or ``"Auto"``.
        """
        if isinstance(surface.aperture, RadialAperture):
            return f"{float(surface.aperture.r_max):.4f}"
        if surface.semi_aperture is not None:
            return f"{float(surface.semi_aperture):.4f}"
        return "Auto"

    def _get_dynamic_radius_data(self, surface: object) -> str:
        """Return the radius-column value for *surface*, respecting surface type.

        Args:
            surface: A surface object from the surface group.

        Returns:
            A formatted radius string, or ``"inf"``.
        """
        geo = surface.geometry
        val = float("inf")
        if surface.surface_type == "paraxial":
            val = surface.f
        elif surface.surface_type == "toroidal":
            val = getattr(geo, "R_yz", val)
        elif surface.surface_type == "biconic":
            val = getattr(geo, "Ry", val)
        else:
            val = geo.radius
        return "inf" if val == float("inf") else f"{val:.4f}"

    def _get_dynamic_conic_data(self, surface: object) -> str:
        """Return the conic-column value for *surface*, respecting surface type.

        Args:
            surface: A surface object from the surface group.

        Returns:
            A formatted conic string, or ``"N/A"`` for paraxial surfaces.
        """
        if surface.surface_type == "paraxial":
            return "N/A"
        geo = surface.geometry
        val = 0.0
        if surface.surface_type == "toroidal":
            val = getattr(geo, "k_yz", val)
        elif surface.surface_type == "biconic":
            val = getattr(geo, "ky", val)
        elif hasattr(geo, "k"):
            val = geo.k
        return f"{val:.4f}"

    def _get_thickness_data(self, surface: object) -> str:
        """Return the thickness for *surface*.

        Args:
            surface: A surface object from the surface group.

        Returns:
            A formatted thickness string, or ``"N/A"``.
        """
        optic = self._connector._optic
        row = optic.surfaces.surfaces.index(surface)
        if row < self.get_surface_count() - 1:
            t = optic.surfaces.get_thickness(row)
            return f"{float(t[0]):.4f}" if t is not None and len(t) > 0 else "N/A"
        return "N/A"

    # ------------------------------------------------------------------
    # Public read API
    # ------------------------------------------------------------------

    def get_surface_data(self, row: int, col_idx: int) -> object:
        """Return the display value for a given LDE cell.

        Args:
            row: LDE row index (0-based).
            col_idx: Column index constant (e.g. ``COL_RADIUS``).

        Returns:
            A string or ``None`` if the cell is out of range.
        """
        if not (0 <= row < self.get_surface_count()):
            return None
        c = self._connector
        surface = c._optic.surfaces.surfaces[row]
        column_handlers = {
            c.COL_TYPE: lambda s: self.get_surface_type_info(row)["display_text"],
            c.COL_COMMENT: lambda s: s.comment,
            c.COL_RADIUS: self._get_dynamic_radius_data,
            c.COL_THICKNESS: self._get_thickness_data,
            c.COL_MATERIAL: self._get_material_data,
            c.COL_CONIC: self._get_dynamic_conic_data,
            c.COL_SEMI_DIAMETER: self._get_semi_diameter_data,
        }
        handler = column_handlers.get(col_idx)
        return handler(surface) if handler else None

    # ------------------------------------------------------------------
    # Write helpers (private)
    # ------------------------------------------------------------------

    def _set_comment_data(self, surface: object, value: str) -> None:
        """Set the comment on *surface*.

        Args:
            surface: Target surface object.
            value: New comment string.
        """
        surface.comment = str(value)

    def _set_material_data(self, surface: object, value: str) -> None:
        """Set the material on *surface* from a user-entered string.

        Handles ``"mirror"``, ``"air"``, numeric ideal indices, and catalog
        glass names.

        Args:
            surface: Target surface object.
            value: Material name or value string.
        """
        new_material_name = str(value).strip().lower()
        if new_material_name == "mirror":
            surface.is_reflective = True
            surface.material_post = surface.material_pre or IdealMaterial(n=1.0)
        else:
            surface.is_reflective = False
            if new_material_name == "air":
                surface.material_post = IdealMaterial(n=1.0)
            else:
                try:
                    n_val = float(new_material_name)
                    surface.material_post = IdealMaterial(n=n_val)
                except ValueError:
                    surface.material_post = OptilandMaterial(name=str(value).strip())

        self._connector._optic.updater.update()

    def _set_thickness_data(self, surface: object, value: str) -> None:
        """Set the thickness behind *surface*.

        Args:
            surface: Target surface object.
            value: New thickness as a string-encoded float.
        """
        optic = self._connector._optic
        row = optic.surfaces.surfaces.index(surface)
        if row < self.get_surface_count() - 1:
            optic.updater.set_thickness(float(value), row)

    def _set_semi_diameter_data(self, surface: object, value: str) -> None:
        """Set the semi-diameter aperture on *surface*.

        Args:
            surface: Target surface object.
            value: Semi-diameter as a string-encoded float.
        """
        try:
            surface.aperture = configure_aperture(float(value) * 2.0)
        except (ValueError, TypeError):
            surface.aperture = None

    def get_surface_aperture_config(self, row: int) -> dict:
        """Return a GUI-friendly physical aperture config for *row*."""
        if not (0 <= row < self.get_surface_count()):
            return {"type": "none"}
        surface = self._connector._optic.surfaces.surfaces[row]
        aperture = getattr(surface, "aperture", None)
        if aperture is None:
            return {"type": "none"}
        if isinstance(aperture, RadialAperture):
            return {
                "type": "ring_aperture" if float(aperture.r_min) > 0 else "circular_aperture",
                "outer_radius": float(aperture.r_max),
                "inner_radius": float(aperture.r_min),
                "clear_radius": float(aperture.r_max),
            }
        if (
            isinstance(aperture, DifferenceAperture)
            and isinstance(aperture.a, RadialAperture)
            and isinstance(aperture.b, RadialAperture)
        ):
            return {
                "type": (
                    "ring_mask" if float(aperture.b.r_min) > 0 else "circular_mask"
                ),
                "outer_radius": float(aperture.b.r_max),
                "inner_radius": float(aperture.b.r_min),
                "clear_radius": float(aperture.a.r_max),
            }
        return {"type": aperture.__class__.__name__}

    def set_surface_aperture_config(self, row: int, config: dict) -> None:
        """Apply a physical aperture config to *row*."""
        if not (0 <= row < self.get_surface_count()):
            return
        surface = self._connector._optic.surfaces.surfaces[row]
        aperture_type = str(config.get("type", "none")).strip().lower()
        aperture_type = {
            "circular": "circular_aperture",
            "annular": "ring_aperture",
            "ring_aperture": "ring_aperture",
            "ring_mask": "ring_mask",
            "circular_mask": "circular_mask",
            "circular_aperture": "circular_aperture",
        }.get(aperture_type, aperture_type)
        if aperture_type == "none":
            surface.aperture = None
            self._connector._optic.updater.update()
            return

        outer_radius = float(config.get("outer_radius", 0.0) or 0.0)
        inner_radius = float(config.get("inner_radius", 0.0) or 0.0)
        clear_radius = float(config.get("clear_radius", outer_radius) or outer_radius or 0.0)

        if outer_radius <= 0:
            raise ValueError("Aperture outer radius must be greater than zero.")
        if inner_radius < 0:
            raise ValueError("Aperture inner radius cannot be negative.")
        if inner_radius >= outer_radius:
            raise ValueError("Aperture inner radius must be smaller than outer radius.")
        if clear_radius <= 0:
            raise ValueError("Aperture clear radius must be greater than zero.")
        if clear_radius < outer_radius:
            raise ValueError("Aperture clear radius must be greater than or equal to outer radius.")

        if aperture_type == "circular_aperture":
            surface.aperture = RadialAperture(r_max=outer_radius, r_min=0.0)
        elif aperture_type == "ring_aperture":
            surface.aperture = RadialAperture(r_max=outer_radius, r_min=inner_radius)
        elif aperture_type == "circular_mask":
            surface.aperture = DifferenceAperture(
                RadialAperture(r_max=clear_radius, r_min=0.0),
                RadialAperture(r_max=outer_radius, r_min=0.0),
            )
        elif aperture_type == "ring_mask":
            surface.aperture = DifferenceAperture(
                RadialAperture(r_max=clear_radius, r_min=0.0),
                RadialAperture(r_max=outer_radius, r_min=inner_radius),
            )
        else:
            raise ValueError(f"Unsupported aperture type '{aperture_type}'.")

        self._connector._optic.updater.update()

    def _set_dynamic_radius_data(self, surface: object, value: str) -> None:
        """Set the radius-column value on *surface*, respecting surface type.

        Args:
            surface: Target surface object.
            value: New radius value as a string-encoded float.
        """
        val = float(value)
        if surface.surface_type == "paraxial":
            surface.f = val
        elif surface.surface_type == "toroidal":
            surface.geometry.R_yz = be.array(val)
            surface.geometry.c_yz = 1.0 / val if val != 0 else 0.0
        elif surface.surface_type == "biconic":
            surface.geometry.Ry = be.array(val)
            surface.geometry.cy = 1.0 / val if val != 0 else 0.0
        else:
            optic = self._connector._optic
            row = optic.surfaces.surfaces.index(surface)
            optic.updater.set_radius(val, row)

    def _set_dynamic_conic_data(self, surface: object, value: str) -> None:
        """Set the conic-column value on *surface*, respecting surface type.

        Args:
            surface: Target surface object.
            value: New conic value as a string-encoded float.
        """
        val = float(value)
        if surface.surface_type == "paraxial":
            return
        if surface.surface_type == "toroidal":
            surface.geometry.k_yz = be.array(val)
        elif surface.surface_type == "biconic":
            surface.geometry.ky = be.array(val)
        elif hasattr(surface.geometry, "k"):
            optic = self._connector._optic
            row = optic.surfaces.surfaces.index(surface)
            optic.updater.set_conic(val, row)

    # ------------------------------------------------------------------
    # Public write API
    # ------------------------------------------------------------------

    def set_surface_data(self, row: int, col_idx: int, value_str: str) -> None:
        """Write a value to a specific LDE cell.

        Captures the current state for undo, dispatches to the appropriate
        write helper, updates the optic, and emits ``opticChanged``.

        Args:
            row: LDE row index (0-based).
            col_idx: Column index constant.
            value_str: The new value as entered by the user.
        """
        if not (0 <= row < self.get_surface_count()):
            return
        old_state = self._connector._capture_optic_state()
        try:
            c = self._connector
            surface = c._optic.surfaces.surfaces[row]
            handler_map = {
                c.COL_COMMENT: self._set_comment_data,
                c.COL_MATERIAL: self._set_material_data,
                c.COL_THICKNESS: self._set_thickness_data,
                c.COL_SEMI_DIAMETER: self._set_semi_diameter_data,
                c.COL_RADIUS: self._set_dynamic_radius_data,
                c.COL_CONIC: self._set_dynamic_conic_data,
            }
            handler = handler_map.get(col_idx)
            if handler:
                handler(surface, value_str)
            c._optic.updater.update()
            c._undo_redo_manager.add_state(old_state)
            c.set_modified(True)
            c.opticChanged.emit()
        except Exception as exc:
            logger.warning(
                "SurfaceService: Error setting data at (%d, %d) to '%s': %s",
                row,
                col_idx,
                value_str,
                exc,
            )
            self._connector._restore_optic_state(old_state)

    def set_surface_type(self, row: int, new_type: str) -> None:
        """Change the geometry type for a surface.

        Preserves compatible parameters (radius, conic) where possible.
        Captures an undo state before the change.

        Args:
            row: LDE row index of the surface to modify (Object and Image
                surfaces are rejected).
            new_type: Surface type string, e.g. ``"biconic"``.
        """
        if not (0 < row < self.get_surface_count() - 1):
            return
        new_type = new_type.lower().strip()
        if new_type not in self.AVAILABLE_SURFACE_TYPES:
            return

        old_state = self._connector._capture_optic_state()
        try:
            surface = self._connector._optic.surfaces.surfaces[row]
            old_geo = surface.geometry

            config_kwargs = {
                "radius": getattr(old_geo, "radius", float("inf")),
                "conic": getattr(old_geo, "k", 0.0),
            }

            config_handlers = {
                "biconic": self._get_biconic_config,
                "toroidal": self._get_toroidal_config,
                "even_asphere": self._get_polynomial_config,
                "odd_asphere": self._get_polynomial_config,
                "polynomial": self._get_polynomial_config,
                "chebyshev": self._get_chebyshev_config,
                "zernike": self._get_zernike_config,
            }

            handler = config_handlers.get(new_type)
            if handler:
                config_kwargs = handler(old_geo)

            new_geo = GeometryFactory.create(
                surface_type=new_type, cs=old_geo.cs, **config_kwargs
            )

            surface.geometry = new_geo
            surface.surface_type = new_type
            if new_type == "paraxial" and not hasattr(surface, "f"):
                surface.f = float("inf")

            self._connector._optic.updater.update()
            self._connector._undo_redo_manager.add_state(old_state)
            self._connector.set_modified(True)
            self._connector.opticChanged.emit()

        except Exception as exc:
            logger.warning("SurfaceService: Error setting surface type: %s", exc)
            self._connector._restore_optic_state(old_state)

    def add_surface(self, index: int = -1) -> None:
        """Insert a new standard surface before the image surface.

        Args:
            index: Insertion index in the surface list. ``-1`` (default) inserts
                before the image surface.
        """
        old_state = self._connector._capture_optic_state()
        num_rows = self.get_surface_count()
        insert_idx = num_rows - 1 if index == -1 or index >= num_rows else index
        if insert_idx <= 0:
            insert_idx = 1

        self._connector._optic.surfaces.add(
            surface_type="standard",
            radius=float("inf"),
            thickness=0.0,
            material="Air",
            comment="New Surface",
            index=insert_idx,
        )
        self._connector._optic.updater.update()
        self._connector._undo_redo_manager.add_state(old_state)
        self._connector.set_modified(True)
        self._connector.opticChanged.emit()

    def remove_surface(self, lde_row_index: int) -> None:
        """Remove a surface by its LDE row index.

        Object (row 0) and Image (last row) surfaces cannot be removed.

        Args:
            lde_row_index: LDE row index of the surface to remove.
        """
        if not (0 < lde_row_index < self.get_surface_count() - 1):
            logger.warning("SurfaceService: Cannot remove Object or Image surface.")
            return

        old_state = self._connector._capture_optic_state()
        try:
            self._connector._optic.surfaces.remove(lde_row_index)
            self._connector._optic.updater.update()
            self._connector._undo_redo_manager.add_state(old_state)
            self._connector.set_modified(True)
            self._connector.opticChanged.emit()
        except Exception:
            self._connector._restore_optic_state(old_state)

    def remove_surface_element(self, row: int) -> None:
        """Remove the full logical element containing *row* in one operation."""
        rows = self.get_group_rows(row)
        if not rows:
            self.remove_surface(row)
            return

        removable_rows = [
            group_row
            for group_row in rows
            if 0 < group_row < self.get_surface_count() - 1
        ]
        if not removable_rows:
            logger.warning("SurfaceService: Cannot remove Object or Image surface.")
            return

        old_state = self._connector._capture_optic_state()
        try:
            for group_row in reversed(removable_rows):
                self._connector._optic.surfaces.remove(group_row)
            self._connector._optic.updater.update()
            self._connector._undo_redo_manager.add_state(old_state)
            self._connector.set_modified(True)
            self._connector.opticChanged.emit()
        except Exception:
            self._connector._restore_optic_state(old_state)

    def insert_surface_sequence(
        self,
        index: int,
        surfaces: list[dict],
        stop_offset: int | None = None,
        group_name: str | None = None,
        group_role: str | None = None,
    ) -> None:
        """Insert a sequence of surfaces as a single undoable operation.

        Args:
            index: Insertion index in the optic surface list.
            surfaces: List of dicts describing each surface.
            stop_offset: Optional offset within *surfaces* to mark as stop.
        """
        if not surfaces:
            return

        old_state = self._connector._capture_optic_state()
        num_rows = self.get_surface_count()
        insert_idx = min(max(index, 1), max(num_rows - 1, 1))
        assigned_group_id = uuid.uuid4().hex if len(surfaces) > 1 else None
        existing_stop_surface = None
        with suppress(ValueError):
            existing_stop_surface = self._connector._optic.surfaces[
                self._connector._optic.surfaces.stop_index
            ]
        preserve_existing_stop = existing_stop_surface is not None

        try:
            for offset, spec in enumerate(surfaces):
                aperture = None
                semi_diameter = spec.get("semi_diameter")
                if semi_diameter not in (None, "", "Auto"):
                    aperture = configure_aperture(float(semi_diameter) * 2.0)

                material_name = str(spec.get("material", "Air"))
                material_reference = str(spec.get("material_reference", "")).strip()
                if (
                    material_reference
                    and material_name.strip().lower() not in {"air", "mirror"}
                ):
                    safe_material_name = OptilandMaterial.resolve_winlens_safe_name(
                        material_name,
                        material_reference,
                    )
                    resolved_name = safe_material_name or material_name
                    material_spec = OptilandMaterial(
                        resolved_name,
                        reference=material_reference,
                        robust_search=safe_material_name is not None,
                    )
                else:
                    material_spec = material_name

                geometry_kwargs = {
                    key: self._normalize_insert_value(value)
                    for key, value in spec.items()
                    if key
                    not in {
                        "surface_type",
                            "thickness",
                            "material",
                            "material_reference",
                            "comment",
                            "semi_diameter",
                    }
                }

                self._connector._optic.surfaces.add(
                    index=insert_idx + offset,
                    surface_type=str(spec.get("surface_type", "standard")),
                    thickness=float(spec.get("thickness", 0.0)),
                    material=material_spec,
                    comment=str(spec.get("comment", "Catalog Surface")),
                    group_id=assigned_group_id,
                    group_name=group_name,
                    group_role=group_role,
                    is_stop=(not preserve_existing_stop and stop_offset == offset),
                    aperture=aperture,
                    **geometry_kwargs,
                )

            if preserve_existing_stop and existing_stop_surface is not None:
                restored_stop_index = self._connector._optic.surfaces.index(
                    existing_stop_surface
                )
                self._connector._optic.surfaces.stop_index = restored_stop_index

            self._connector._optic.updater.update()
            self._connector._undo_redo_manager.add_state(old_state)
            self._connector.set_modified(True)
            self._connector.opticChanged.emit()
        except Exception:
            self._connector._restore_optic_state(old_state)
            raise

    def _normalize_insert_value(self, value):  # noqa: ANN001
        """Convert serialized insertion values into geometry-factory-friendly types."""
        if isinstance(value, str) and value.strip().lower() == "inf":
            return float("inf")
        if isinstance(value, list):
            return [self._normalize_insert_value(item) for item in value]
        if isinstance(value, dict):
            return {
                key: self._normalize_insert_value(item)
                for key, item in value.items()
            }
        return value

    def set_stop_surface(self, row: int) -> None:
        """Set the surface at *row* as the aperture stop.

        Args:
            row: LDE row index of the surface to set as stop.
        """
        if not (0 < row < self.get_surface_count() - 1):
            logger.warning("SurfaceService: Stop must be an intermediate surface.")
            return

        old_state = self._connector._capture_optic_state()
        try:
            self._connector._optic.surfaces.stop_index = row
            self._connector._optic.updater.update()
            self._connector._undo_redo_manager.add_state(old_state)
            self._connector.set_modified(True)
            self._connector.opticChanged.emit()
        except Exception as exc:
            logger.warning("SurfaceService: Error setting stop surface: %s", exc)
            self._connector._restore_optic_state(old_state)

    def get_surface_group_metadata(self, row: int) -> dict:
        """Return grouping metadata for a surface row."""
        if not (0 < row < self.get_surface_count() - 1):
            return {"group_id": None, "group_name": None, "group_role": None}
        surface = self._connector._optic.surfaces.surfaces[row]
        return {
            "group_id": getattr(surface, "group_id", None),
            "group_name": getattr(surface, "group_name", None),
            "group_role": getattr(surface, "group_role", None),
        }

    def get_group_rows(self, row: int) -> list[int]:
        """Return all LDE rows belonging to the same surface group as *row*."""
        if not (0 < row < self.get_surface_count() - 1):
            return []
        group_id = getattr(self._connector._optic.surfaces.surfaces[row], "group_id", None)
        if not group_id:
            return []
        return [
            idx
            for idx, surface in enumerate(self._connector._optic.surfaces.surfaces)
            if getattr(surface, "group_id", None) == group_id
        ]

    def create_surface_group(
        self,
        rows: list[int],
        group_name: str | None = None,
        group_role: str = "assembly",
    ) -> str | None:
        """Assign a new logical element group to contiguous surface rows."""
        cleaned_rows = sorted(
            {
                int(row)
                for row in rows
                if 0 < int(row) < self.get_surface_count() - 1
            }
        )
        if len(cleaned_rows) < 2:
            return None
        if cleaned_rows != list(range(cleaned_rows[0], cleaned_rows[-1] + 1)):
            raise ValueError("Element groups must be created from contiguous surfaces.")
        existing_group_ids = {
            str(group_id)
            for row in cleaned_rows
            if (group_id := getattr(self._connector._optic.surfaces.surfaces[row], "group_id", None))
        }
        if existing_group_ids:
            raise ValueError(
                "Surfaces already assigned to an element cannot be grouped again."
            )

        old_state = self._connector._capture_optic_state()
        group_id = uuid.uuid4().hex
        group_name = (group_name or f"Element {cleaned_rows[0]}").strip()
        try:
            for row in cleaned_rows:
                surface = self._connector._optic.surfaces.surfaces[row]
                surface.group_id = group_id
                surface.group_name = group_name
                surface.group_role = group_role
            self._connector._undo_redo_manager.add_state(old_state)
            self._connector.set_modified(True)
            self._connector.opticChanged.emit()
            return group_id
        except Exception:
            self._connector._restore_optic_state(old_state)
            raise

    def rename_surface_group(self, row: int, group_name: str) -> None:
        """Rename the logical element containing *row*."""
        rows = self.get_group_rows(row)
        if not rows:
            return
        old_state = self._connector._capture_optic_state()
        try:
            clean_name = group_name.strip()
            for group_row in rows:
                self._connector._optic.surfaces.surfaces[group_row].group_name = clean_name
            self._connector._undo_redo_manager.add_state(old_state)
            self._connector.set_modified(True)
            self._connector.opticChanged.emit()
        except Exception:
            self._connector._restore_optic_state(old_state)
            raise

    def ungroup_surface_element(self, row: int) -> None:
        """Clear the logical element metadata for the group containing *row*."""
        rows = self.get_group_rows(row)
        if not rows:
            return
        old_state = self._connector._capture_optic_state()
        try:
            for group_row in rows:
                surface = self._connector._optic.surfaces.surfaces[group_row]
                surface.group_id = None
                surface.group_name = None
                surface.group_role = None
            self._connector._undo_redo_manager.add_state(old_state)
            self._connector.set_modified(True)
            self._connector.opticChanged.emit()
        except Exception:
            self._connector._restore_optic_state(old_state)
            raise

    def duplicate_surface_element(
        self, row: int, target_index: int | None = None
    ) -> list[int]:
        """Duplicate the logical element containing *row*.

        The duplicate receives a fresh ``group_id`` and is inserted before
        ``target_index`` or, by default, directly after the original block.
        """
        rows = self.get_group_rows(row)
        if not rows:
            return []

        old_state = self._connector._capture_optic_state()
        surfaces = self._connector._optic.surfaces
        insert_idx = rows[-1] + 1 if target_index is None else int(target_index)
        insert_idx = min(max(insert_idx, 1), max(self.get_surface_count() - 1, 1))
        new_group_id = uuid.uuid4().hex
        cloned_surfaces: list[Surface] = []

        existing_stop_surface = None
        with suppress(ValueError):
            existing_stop_surface = surfaces[surfaces.stop_index]

        try:
            for src_row in rows:
                source_surface = surfaces.surfaces[src_row]
                clone = Surface.from_dict(source_surface.to_dict())
                clone.group_id = new_group_id
                clone.group_name = getattr(source_surface, "group_name", None)
                clone.group_role = getattr(source_surface, "group_role", None)
                clone.is_stop = False
                cloned_surfaces.append(clone)

            for offset, clone in enumerate(cloned_surfaces):
                surfaces.add(
                    new_surface=clone,
                    index=insert_idx + offset,
                    thickness=clone.thickness,
                )

            if existing_stop_surface is not None:
                surfaces.stop_index = surfaces.index(existing_stop_surface)

            self._connector._optic.updater.update()
            self._connector._undo_redo_manager.add_state(old_state)
            self._connector.set_modified(True)
            self._connector.opticChanged.emit()
            return list(range(insert_idx, insert_idx + len(cloned_surfaces)))
        except Exception:
            self._connector._restore_optic_state(old_state)
            raise

    def move_surface_element(self, row: int, target_index: int) -> list[int]:
        """Move the logical element containing *row* to a new insertion index."""
        rows = self.get_group_rows(row)
        if not rows:
            return []

        block_start = rows[0]
        block_end = rows[-1]
        insert_idx = min(max(int(target_index), 1), max(self.get_surface_count() - 1, 1))
        if block_start <= insert_idx <= block_end + 1:
            return rows

        old_state = self._connector._capture_optic_state()
        surfaces = self._connector._optic.surfaces
        block = [surfaces.surfaces[group_row] for group_row in rows]

        existing_stop_surface = None
        with suppress(ValueError):
            existing_stop_surface = surfaces[surfaces.stop_index]

        try:
            for group_row in reversed(rows):
                surfaces.remove(group_row)

            if insert_idx > block_end:
                insert_idx -= len(block)
            insert_idx = min(max(insert_idx, 1), max(len(surfaces) - 1, 1))

            for offset, surface in enumerate(block):
                surfaces.add(
                    new_surface=surface,
                    index=insert_idx + offset,
                    thickness=surface.thickness,
                )

            if existing_stop_surface is not None:
                surfaces.stop_index = surfaces.index(existing_stop_surface)

            self._connector._optic.updater.update()
            self._connector._undo_redo_manager.add_state(old_state)
            self._connector.set_modified(True)
            self._connector.opticChanged.emit()
            return list(range(insert_idx, insert_idx + len(block)))
        except Exception:
            self._connector._restore_optic_state(old_state)
            raise

    def flip_surface_element(self, row: int) -> list[int]:
        """Reverse the grouped element containing *row* in optical direction."""
        rows = self.get_group_rows(row)
        if not rows:
            return []

        old_state = self._connector._capture_optic_state()
        surfaces = self._connector._optic.surfaces
        original_block = [copy.deepcopy(surfaces.surfaces[group_row].to_dict()) for group_row in rows]
        stop_offset = next(
            (offset for offset, surface_data in enumerate(original_block) if surface_data.get("is_stop")),
            None,
        )
        original_thicknesses = [surface_data.get("thickness", 0.0) for surface_data in original_block]
        reversed_internal_thicknesses = list(reversed(original_thicknesses[:-1]))
        flipped_thicknesses = reversed_internal_thicknesses + [original_thicknesses[-1]]

        original_material_posts = [
            copy.deepcopy(surface_data["material_post"]) for surface_data in original_block
        ]
        flipped_material_posts = list(reversed(original_material_posts[:-1])) + [
            copy.deepcopy(original_material_posts[-1])
        ]

        try:
            flipped_block: list[dict] = []
            for new_offset, surface_data in enumerate(reversed(original_block)):
                flipped_surface = copy.deepcopy(surface_data)
                self._flip_surface_geometry_dict(flipped_surface["geometry"])
                flipped_surface["thickness"] = flipped_thicknesses[new_offset]
                flipped_surface["material_post"] = flipped_material_posts[new_offset]
                flipped_surface["is_stop"] = (
                    stop_offset is not None
                    and new_offset == len(original_block) - 1 - stop_offset
                )
                flipped_block.append(flipped_surface)

            for group_row in reversed(rows):
                surfaces.remove(group_row)

            insert_idx = rows[0]
            for offset, surface_data in enumerate(flipped_block):
                new_surface = Surface.from_dict(surface_data)
                surfaces.add(
                    new_surface=new_surface,
                    index=insert_idx + offset,
                    thickness=new_surface.thickness,
                )

            self._connector._optic.updater.update()
            self._connector._undo_redo_manager.add_state(old_state)
            self._connector.set_modified(True)
            self._connector.opticChanged.emit()
            return list(range(insert_idx, insert_idx + len(flipped_block)))
        except Exception:
            self._connector._restore_optic_state(old_state)
            raise

    # ------------------------------------------------------------------
    # Geometry parameter helpers (private)
    # ------------------------------------------------------------------

    def _flip_surface_geometry_dict(self, geometry_data: dict) -> None:
        """Flip a serialized geometry in-place for element reversal."""
        geometry_type = geometry_data.get("type")

        if geometry_type in {"Plane", "PlaneGrating"}:
            return

        if geometry_type == "StandardGeometry":
            geometry_data["radius"] = self._negate_finite_value(geometry_data.get("radius"))
            return

        if geometry_type == "EvenAsphere":
            geometry_data["radius"] = self._negate_finite_value(geometry_data.get("radius"))
            geometry_data["coefficients"] = [
                -float(coefficient) for coefficient in geometry_data.get("coefficients", [])
            ]
            return

        if geometry_type == "BiconicGeometry":
            geometry_data["radius_x"] = self._negate_finite_value(geometry_data.get("radius_x"))
            geometry_data["radius_y"] = self._negate_finite_value(geometry_data.get("radius_y"))
            return

        raise NotImplementedError(
            f"Element flip is not implemented for geometry type '{geometry_type}'."
        )

    def _negate_finite_value(self, value):  # noqa: ANN001
        """Negate a scalar unless it represents an infinite plane radius."""
        if value in (None, "", "Auto"):
            return value
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return value
        if numeric == float("inf") or numeric == float("-inf"):
            return value
        return -numeric

    def _parse_param_value(self, value_str: str) -> object:
        """Parse a string that may represent a list, tuple, or float.

        Args:
            value_str: The user-entered string to parse.

        Returns:
            A Python list/tuple (if the string starts with ``[`` or ``(``) or
            a float.
        """
        if isinstance(value_str, str):
            value_str = value_str.strip()
            if value_str.startswith(("[", "(")):
                return ast.literal_eval(value_str)
        return float(value_str)

    def _coerce_geometry_param_value(self, attr_name: str, value: object) -> object:
        """Convert parsed geometry values to the storage shape expected by the geometry.

        Sequence-like geometry parameters such as asphere coefficients must stay
        plain Python lists so they serialize cleanly to Optiland JSON.
        Scalar values continue to use the active backend array/scalar type.
        """
        if attr_name in {"coefficients", "coeffs_poly_y"}:
            return list(value) if isinstance(value, (list, tuple)) else [value]
        return be.array(value)

    def _update_biconic_geometry(self, surface: object, params_dict: dict) -> None:
        """Replace a plane geometry with a biconic using values from *params_dict*.

        Args:
            surface: The surface whose geometry will be replaced.
            params_dict: Dict containing ``"Radius X"`` and ``"Conic X"`` keys.
        """
        radius_y = getattr(surface.geometry, "radius", float("inf"))
        conic_y = getattr(surface.geometry, "k", 0.0)
        radius_x = self._parse_param_value(params_dict.get("Radius X", float("inf")))
        conic_x = self._parse_param_value(params_dict.get("Conic X", 0.0))
        new_geo = BiconicGeometry(
            coordinate_system=surface.geometry.cs,
            radius_x=radius_x,
            radius_y=radius_y,
            conic_x=conic_x,
            conic_y=conic_y,
        )
        surface.geometry = new_geo

    def _get_biconic_config(self, old_geo: object) -> dict:
        """Build a geometry-factory config dict for a biconic surface.

        Args:
            old_geo: The current geometry object (used to preserve values).

        Returns:
            A dict of keyword arguments for
            :class:`~optiland.geometries.BiconicGeometry`.
        """
        if hasattr(old_geo, "Rx"):
            return {
                "radius_x": getattr(old_geo, "Rx", 100.0),
                "radius_y": getattr(old_geo, "Ry", 100.0),
                "conic_x": getattr(old_geo, "kx", 0.0),
                "conic_y": getattr(old_geo, "ky", 0.0),
            }
        return {"radius_x": 100.0, "radius_y": 100.0}

    def _get_toroidal_config(self, old_geo: object) -> dict:
        """Build a geometry-factory config dict for a toroidal surface.

        Args:
            old_geo: The current geometry object.

        Returns:
            A dict of keyword arguments for the toroidal geometry factory.
        """
        if hasattr(old_geo, "R_rot"):
            return {
                "radius": getattr(old_geo, "R_rot", 100.0),
                "radius_y": getattr(old_geo, "R_yz", 100.0),
                "conic": getattr(old_geo, "k_yz", 0.0),
                "toroidal_coeffs_poly_y": getattr(old_geo, "coeffs_poly_y", []),
            }
        return {"radius": 100.0, "radius_y": 100.0}

    def _get_polynomial_config(self, old_geo: object) -> dict:
        """Build a geometry-factory config dict for polynomial-based surfaces.

        Args:
            old_geo: The current geometry object.

        Returns:
            A dict with ``radius``, ``conic``, and ``coefficients`` keys.
        """
        config = {
            "radius": getattr(old_geo, "radius", float("inf")),
            "conic": getattr(old_geo, "k", 0.0),
            "coefficients": getattr(old_geo, "c", []),
        }
        if config["radius"] == float("inf"):
            config["radius"] = 100.0
        return config

    def _get_chebyshev_config(self, old_geo: object) -> dict:
        """Build a geometry-factory config dict for a Chebyshev surface.

        Args:
            old_geo: The current geometry object.

        Returns:
            A polynomial config dict extended with ``norm_x`` and ``norm_y``.
        """
        config = self._get_polynomial_config(old_geo)
        config["norm_x"] = getattr(old_geo, "norm_x", 1.0)
        config["norm_y"] = getattr(old_geo, "norm_y", 1.0)
        return config

    def _get_zernike_config(self, old_geo: object) -> dict:
        """Build a geometry-factory config dict for a Zernike surface.

        Args:
            old_geo: The current geometry object.

        Returns:
            A polynomial config dict extended with ``norm_radius``.
        """
        config = self._get_polynomial_config(old_geo)
        config["norm_radius"] = getattr(old_geo, "norm_radius", 1.0)
        return config

    # ------------------------------------------------------------------
    # Public geometry-params API
    # ------------------------------------------------------------------

    def get_surface_geometry_params(self, row: int) -> dict:
        """Return the extra geometry parameters for the surface properties box.

        Only surfaces with entries in :attr:`EXTRA_PARAM_MAP` return
        non-empty dicts.

        Args:
            row: LDE row index (Object and Image rows return ``{}``).

        Returns:
            A dict mapping human-readable parameter labels to their current
            values.
        """
        if not (0 < row < self.get_surface_count() - 1):
            return {}
        surface = self._connector._optic.surfaces.surfaces[row]
        geometry = surface.geometry
        geo_class_name = geometry.__class__.__name__

        if surface.surface_type == "biconic" and geo_class_name == "Plane":
            return {"Radius X": float("inf"), "Conic X": 0.0}

        params = {}
        if geo_class_name in self.EXTRA_PARAM_MAP:
            for label, attr_name in self.EXTRA_PARAM_MAP[geo_class_name].items():
                if hasattr(geometry, attr_name):
                    params[label] = getattr(geometry, attr_name)
        return params

    def set_surface_geometry_params(self, row: int, params_dict: dict) -> None:
        """Apply extra geometry parameters from the surface properties box.

        Captures an undo state, applies all parameter values, updates the
        optic, and emits ``opticChanged``.

        Args:
            row: LDE row index (Object and Image rows are rejected).
            params_dict: A dict mapping human-readable labels to new values.
        """
        if not (0 < row < self.get_surface_count() - 1):
            return

        old_state = self._connector._capture_optic_state()
        try:
            surface = self._connector._optic.surfaces.surfaces[row]
            geometry = surface.geometry
            geo_class_name = geometry.__class__.__name__

            if surface.surface_type == "biconic" and geo_class_name == "Plane":
                self._update_biconic_geometry(surface, params_dict)
            elif geo_class_name in self.EXTRA_PARAM_MAP:
                for label, value_str in params_dict.items():
                    attr_name = self.EXTRA_PARAM_MAP[geo_class_name].get(label)
                    if attr_name and hasattr(geometry, attr_name):
                        try:
                            new_value = self._parse_param_value(value_str)
                            setattr(
                                geometry,
                                attr_name,
                                self._coerce_geometry_param_value(attr_name, new_value),
                            )

                            if (
                                geo_class_name == "BiconicGeometry"
                                and attr_name == "Rx"
                            ) or (
                                geo_class_name == "ToroidalGeometry"
                                and attr_name == "R_rot"
                            ):
                                geometry.radius = be.array(new_value)
                        except (ValueError, SyntaxError):
                            continue

            self._connector._optic.updater.update()
            self._connector._undo_redo_manager.add_state(old_state)
            self._connector.set_modified(True)
            self._connector.opticChanged.emit()

        except Exception as exc:
            logger.warning("SurfaceService: Error setting geometry params: %s", exc)
            self._connector._restore_optic_state(old_state)
