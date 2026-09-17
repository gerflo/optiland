"""Optic to Zemax Converter

Converts an Optiland Optic object into a ZemaxDataModel. This is the mirror
of ZemaxToOpticConverter and is the first stage of the write pipeline.

Kramer Harrison, 2024
"""

from __future__ import annotations

import math
import warnings
from pathlib import Path
from typing import TYPE_CHECKING, Any

import optiland.backend as be
from optiland.fileio.common import WL_D, compute_abbe_number, field_type_string, is_air
from optiland.fileio.zemax.model import ZemaxDataModel
from optiland.fileio.zemax.surfaces import (
    CoordinateBreakSurfaceHandler,
    get_handler_for_optiland_type,
)
from optiland.materials.ideal import IdealMaterial
from optiland.materials.material import Material
from optiland.physical_apertures import RadialAperture
from optiland.physical_apertures.base import DifferenceAperture

if TYPE_CHECKING:
    from optiland.optic import Optic

# Map from Optiland aperture type to Zemax operand string
_AP_TYPE_TO_OPERAND: dict[str, str] = {
    "EPD": "ENPD",
    "imageFNO": "FNUM",
    "paraxialImageFNO": "PFIL",
    "objectNA": "OBNA",
    "float_by_stop_size": "FLOA",
}

# Map from Optiland field type string to Zemax FTYP integer
_FIELD_TYPE_TO_FTYP: dict[str, int] = {
    "angle": 0,
    "object_height": 1,
    "paraxial_image_height": 2,
    "real_image_height": 3,
}

# Map from Optiland geometry str() to Optiland surface type string.
# "Planar" (flat surface) maps to "standard" since Zemax encodes it as
# TYPE STANDARD with CURV 0.
_GEOM_STR_TO_TYPE: dict[str, str] = {
    "Planar": "standard",
    "Standard": "standard",
    "Even Asphere": "even_asphere",
    "Odd Asphere": "odd_asphere",
    "Toroidal": "toroidal",
}


def _catalog_from_data_file(material: Material) -> str | None:
    """Return the manufacturer catalog named by a glass's data file, if any.

    A glass looked up by name alone (``Material("N-SF10")``) carries no
    ``reference``, yet its data file names the manufacturer:
    ``glass/schott/N-SF10.yml``. Imported catalogs nest one level deeper
    (``glass/winlens/schott/...``), so the catalog is the directory that holds
    the file.
    """
    data = getattr(material, "material_data", None)
    filename = data.get("filename") if isinstance(data, dict) else None
    if not filename:
        return None
    parts = Path(str(filename)).parts
    if len(parts) >= 3 and parts[0] == "glass":
        return parts[-2]
    return None


class OpticToZemaxConverter:
    """Converts an Optic object to a ZemaxDataModel.

    This is the mirror of ZemaxToOpticConverter and constitutes the first
    stage of the write pipeline (Optic -> ZemaxDataModel -> text lines).

    Args:
        optic: The Optic to convert.
    """

    def __init__(self, optic: Optic):
        self._optic = optic

    def convert(self) -> ZemaxDataModel:
        """Build and return the ZemaxDataModel for the optic.

        Returns:
            A populated ZemaxDataModel ready for ZemaxFileEncoder.
        """
        model = ZemaxDataModel()
        model.name = self._optic.name
        self._convert_aperture(model)
        self._convert_fields(model)
        self._convert_wavelengths(model)
        self._warn_pickups_solves()
        self._convert_surfaces(model)
        return model

    # ------------------------------------------------------------------
    # Aperture
    # ------------------------------------------------------------------

    def _convert_aperture(self, model: ZemaxDataModel) -> None:
        ap = self._optic.aperture
        if ap is None:
            return
        operand = _AP_TYPE_TO_OPERAND.get(ap.ap_type)
        if operand is None:
            warnings.warn(
                f"Unknown aperture type '{ap.ap_type}'; skipping aperture export.",
                UserWarning,
                stacklevel=3,
            )
            return
        model.aperture[ap.ap_type] = float(ap.value)

    # ------------------------------------------------------------------
    # Fields
    # ------------------------------------------------------------------

    def _convert_fields(self, model: ZemaxDataModel) -> None:
        field_type = field_type_string(self._optic)
        ftyp_int = _FIELD_TYPE_TO_FTYP.get(field_type, 0)

        fields = self._optic.fields
        n = fields.num_fields

        x_vals = [float(f.x) for f in fields]
        y_vals = [float(f.y) for f in fields]

        # Vignetting — try vx/vy, fallback to zeros
        try:
            vcx = [float(f.vx) for f in fields]
            vcy = [float(f.vy) for f in fields]
        except AttributeError:
            vcx = [0.0] * n
            vcy = [0.0] * n

        model.fields = {
            "num_fields": n,
            "type": field_type,
            "ftyp_int": ftyp_int,
            "x": x_vals,
            "y": y_vals,
            "weights": [1.0] * n,
            "vignette_compress_x": vcx,
            "vignette_compress_y": vcy,
            "vignette_decenter_x": [0.0] * n,
            "vignette_decenter_y": [0.0] * n,
            "vignette_tangent_angle": [0.0] * n,
        }

    # ------------------------------------------------------------------
    # Wavelengths
    # ------------------------------------------------------------------

    def _convert_wavelengths(self, model: ZemaxDataModel) -> None:
        wls = self._optic.wavelengths
        data: list[float] = []
        primary_index = 0
        for i, w in enumerate(wls):
            data.append(float(w.value))
            if w.is_primary:
                primary_index = i

        model.wavelengths = {
            "data": data,
            "num_wavelengths": len(data),
            "primary_index": primary_index,
        }

    # ------------------------------------------------------------------
    # Pickups / Solves warning
    # ------------------------------------------------------------------

    def _warn_pickups_solves(self) -> None:
        pickups = list(self._optic.pickups.pickups)
        solves = list(self._optic.solves.solves)
        if pickups:
            warnings.warn(
                f"Optic has {len(pickups)} pickup(s) that cannot be represented "
                "in a .zmx file; resolved values will be exported instead.",
                UserWarning,
                stacklevel=3,
            )
        if solves:
            warnings.warn(
                f"Optic has {len(solves)} solve(s) that cannot be represented "
                "in a .zmx file; resolved values will be exported instead.",
                UserWarning,
                stacklevel=3,
            )

    # ------------------------------------------------------------------
    # Surfaces
    # ------------------------------------------------------------------

    def _convert_surfaces(self, model: ZemaxDataModel) -> None:
        """Iterate optic surfaces and populate model.surfaces.

        For surfaces with non-trivial coordinate systems (tilts/decenters),
        synthetic COORDBRK entries are inserted before and after.
        """
        glass_catalogs: list[str] = []
        output_idx = 0
        cb_handler = CoordinateBreakSurfaceHandler()

        for surface_index, surface in enumerate(self._optic.surfaces):
            optiland_type = self._resolve_geometry_type(surface, output_idx)
            cs_angles = self._coordinate_break_angles(surface.geometry.cs)

            if cs_angles is not None:
                model.surfaces[output_idx] = cb_handler.format_cs(
                    dx=float(surface.geometry.cs.x),
                    dy=float(surface.geometry.cs.y),
                    dz=0.0,
                    rx_deg=cs_angles[0],
                    ry_deg=cs_angles[1],
                    rz_deg=cs_angles[2],
                )
                output_idx += 1

            raw = self._encode_surface_body(
                surface, optiland_type, output_idx, glass_catalogs, surface_index
            )
            model.surfaces[output_idx] = raw
            output_idx += 1

            if cs_angles is not None:
                cs = surface.geometry.cs
                model.surfaces[output_idx] = cb_handler.format_cs(
                    dx=-float(cs.x),
                    dy=-float(cs.y),
                    dz=0.0,
                    rx_deg=-cs_angles[0],
                    ry_deg=-cs_angles[1],
                    rz_deg=-cs_angles[2],
                )
                output_idx += 1

        if glass_catalogs:
            # Unique catalog names, preserving order
            model.glass_catalogs = list(dict.fromkeys(glass_catalogs))

    def _resolve_geometry_type(self, surface: Any, output_idx: int) -> str:
        """Map a surface's geometry to a Zemax-supported Optiland type string."""
        geom_str = str(surface.geometry)
        if surface.interaction_model.interaction_type == "thin_lens":
            optiland_type = "paraxial"
        else:
            optiland_type = _GEOM_STR_TO_TYPE.get(geom_str)
        if optiland_type is None:
            raise NotImplementedError(
                f"Surface {output_idx}: geometry type '{geom_str}' "
                "is not supported by the Zemax writer."
            )
        return optiland_type

    def _coordinate_break_angles(self, cs: Any) -> tuple[float, float, float] | None:
        """Return (rx, ry, rz) in degrees if *cs* has a non-trivial transform."""
        has_tilt = any(
            abs(float(getattr(cs, attr, 0.0))) > 1e-12 for attr in ("rx", "ry", "rz")
        )
        has_decenter = any(
            abs(float(getattr(cs, attr, 0.0))) > 1e-12 for attr in ("x", "y")
        )
        if not (has_tilt or has_decenter):
            return None
        return (
            math.degrees(float(cs.rx)),
            math.degrees(float(cs.ry)),
            math.degrees(float(cs.rz)),
        )

    def _encode_surface_body(
        self,
        surface: Any,
        optiland_type: str,
        output_idx: int,
        glass_catalogs: list[str],
        surface_index: int | None = None,
    ) -> dict[str, Any]:
        """Build the raw Zemax surface dict for a single optic surface."""
        handler = get_handler_for_optiland_type(optiland_type)
        raw = handler.format(surface)

        raw["DISZ"] = self._surface_thickness(surface, surface_index)

        if surface.is_stop:
            raw["STOP"] = True

        # Semi-aperture (DIAM)
        # For float_by_stop_size aperture, the stop surface must carry DIAM
        ap = self._optic.aperture
        if surface.is_stop and ap is not None and ap.ap_type == "float_by_stop_size":
            # DIAM is a semi-diameter; float_by_stop_size is a full diameter.
            raw["DIAM"] = float(ap.value) / 2.0
            # The aperture floats on this value, so it must not be recomputed.
            raw["DIAM_FIXED"] = True
        elif surface.semi_aperture is not None:
            raw["DIAM"] = float(surface.semi_aperture)

        # Physical aperture (CLAP)
        if surface.aperture is not None:
            clap = self._zemax_aperture(surface.aperture, output_idx)
            if clap is not None:
                raw["CLAP"] = clap

        # Glass — check the reflective flag first (mirror)
        is_reflective = getattr(
            getattr(surface, "interaction_model", None), "is_reflective", False
        )
        glass_entry = self._format_glass(
            surface.material_post, output_idx, glass_catalogs, is_reflective
        )
        if glass_entry is not None:
            raw["GLAS"] = glass_entry

        return raw

    def _surface_thickness(self, surface: Any, surface_index: int | None) -> Any:
        """Return the DISZ value for a surface: its thickness, or ``INFINITY``.

        The object surface is the exception. Its position lives in its
        coordinate system, and its ``thickness`` attribute is not kept in step
        with it: a finite object restored from a saved design reads
        ``thickness == 0``. Writing that put the object on top of the first
        surface, which Zemax rejects ("Entrance pupil cannot be located at
        object"), so the object's DISZ is its axial gap to the first surface.
        """
        surfaces = self._optic.surfaces.surfaces
        if surface_index == 0 and len(surfaces) > 1:
            if self._optic.object_surface.is_infinite:
                return "INFINITY"
            z_object = be.atleast_1d(be.array(surface.geometry.cs.z)).ravel()[0]
            z_first = be.atleast_1d(be.array(surfaces[1].geometry.cs.z)).ravel()[0]
            return float(z_first) - float(z_object)
        thickness = float(be.atleast_1d(be.array(surface.thickness)).ravel()[0])
        return "INFINITY" if be.isinf(thickness) else thickness

    def _zemax_aperture(self, aperture: Any, surf_idx: int) -> Any:
        """Map a physical aperture onto a Zemax circular aperture, if possible.

        A Zemax circular surface aperture is the annulus ``r_min <= r <= r_max``.
        A centred disc cut out of a centred radial aperture (a
        ``DifferenceAperture`` such as a mushroom stop) is exactly that
        annulus; it used to reach the encoder unconverted and was dropped
        without a word. A shape that still cannot be written is reported.
        """
        if isinstance(aperture, RadialAperture):
            return aperture
        if isinstance(aperture, DifferenceAperture):
            outer, cut = aperture.a, aperture.b
            if (
                type(outer) is RadialAperture
                and type(cut) is RadialAperture
                and float(cut.r_min) == 0.0
                and float(cut.r_max) < float(outer.r_max)
            ):
                return RadialAperture(
                    r_max=float(outer.r_max),
                    r_min=max(float(outer.r_min), float(cut.r_max)),
                )
        warnings.warn(
            f"Surface {surf_idx}: a {type(aperture).__name__} cannot be written "
            "as a Zemax surface aperture and is not exported.",
            UserWarning,
            stacklevel=4,
        )
        return None

    def _format_glass(
        self,
        mat: Any,
        surf_idx: int,
        glass_catalogs: list[str],
        is_reflective: bool = False,
    ) -> dict[str, Any] | None:
        """Build a GLAS operand dict for a material.

        Args:
            mat: The surface material (post).
            surf_idx: Output surface index (used in warnings).
            glass_catalogs: Mutable list to accumulate catalog names.
            is_reflective: True if the surface is a reflective (mirror) surface.

        Returns:
            A dict with keys ``name`` and optionally ``catalog``,
            or None for air.
        """
        # Mirror surface — detected via interaction_model.is_reflective. This must
        # precede the air check: the material following a mirror is the ambient
        # medium, so is_air() is True for a mirror in air.
        if is_reflective:
            return {"name": "MIRROR"}

        if is_air(mat):
            return None

        # Mirror material string fallback
        if isinstance(mat, str) and mat.lower() == "mirror":
            return {"name": "MIRROR"}

        # Catalog glass (Material from glass catalog). A glass looked up by name
        # alone has no reference, but its data file still names the
        # manufacturer; without it the export carried no GCAT line and Zemax
        # could not find the glass.
        if isinstance(mat, Material):
            catalog = mat.reference or _catalog_from_data_file(mat)
            if not catalog:
                return {"name": mat.name.upper()}
            catalog = catalog.upper()
            glass_catalogs.append(catalog)
            n_d, v_d = compute_abbe_number(mat, WL_D)
            return {"name": mat.name.upper(), "catalog": catalog, "n": n_d, "V": v_d}

        # AbbeMaterial or any other material -> MODEL glass
        n_d, v_num = compute_abbe_number(mat, float(self._optic.primary_wavelength))
        if isinstance(mat, IdealMaterial):
            # Zemax reads a model glass with Vd = 0 as a constant index. The
            # generic fallback of 99.99 for a flat dispersion curve would make
            # the medium dispersive there.
            v_num = 0.0

        mat_name = getattr(mat, "name", type(mat).__name__)
        warnings.warn(
            f"Surface {surf_idx}: glass '{mat_name}' has no Zemax catalog entry; "
            f"writing as MODEL glass (n={n_d:.6f}, V={v_num:.2f}). "
            "Round-trip fidelity is not guaranteed.",
            UserWarning,
            stacklevel=4,
        )
        return {"name": "MODEL", "n": n_d, "V": v_num}
