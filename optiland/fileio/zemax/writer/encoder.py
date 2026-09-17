"""Zemax File Encoder

Converts a ZemaxDataModel into a list of .zmx text lines in the order and
format expected by OpticStudio. The encoded lines are written to disk as
UTF-16 LE by save_zemax_file().

Kramer Harrison, 2024
"""

from __future__ import annotations

import math
import warnings
from typing import TYPE_CHECKING, Any

from optiland.physical_apertures import OffsetRadialAperture

if TYPE_CHECKING:
    from optiland.fileio.zemax.model import ZemaxDataModel

# ---------------------------------------------------------------------------
# Aperture type -> Zemax operand
# ---------------------------------------------------------------------------
_AP_TYPE_TO_OPERAND: dict[str, str] = {
    "EPD": "ENPD",
    "imageFNO": "FNUM",
    "paraxialImageFNO": "PFIL",
    "objectNA": "OBNA",
    "float_by_stop_size": "FLOA",
}

_FIELD_TYPE_TO_FTYP: dict[str, int] = {
    "angle": 0,
    "object_height": 1,
    "paraxial_image_height": 2,
    "real_image_height": 3,
}


def _fmt(value: float) -> str:
    """Format a float in Zemax scientific notation.

    Uses 17 significant digits, the IEEE-754 binary64 round-trip guarantee, so
    that ``save_zemax_file`` followed by ``load_zemax_file`` reproduces the
    original system bit-for-bit. The previous ``%.8E`` (9 significant digits)
    was lossy enough to matter: on ``HubbleTelescope`` (EFL ~5.76e4) a single
    save/load shifted real-ray image-surface intercepts by 1.8e-06 mm, which
    exceeds the 1e-06 mm agreement threshold used for cross-tool validation.
    """
    return f"{value:.16E}"


def _fmt_vals(values: list[float]) -> str:
    """Format a list of floats separated by spaces."""
    return " ".join(_fmt(v) for v in values)


class ZemaxFileEncoder:
    """Encodes a ZemaxDataModel as a list of .zmx text lines.

    Args:
        model: The ZemaxDataModel to encode.
    """

    def __init__(self, model: ZemaxDataModel):
        self._model = model

    def encode(self) -> list[str]:
        """Produce the complete list of .zmx text lines.

        Returns:
            A list of strings, one per line of the output file.
        """
        lines: list[str] = []
        self._encode_header(lines)
        self._encode_surfaces(lines)
        return lines

    # ------------------------------------------------------------------
    # Header block
    # ------------------------------------------------------------------

    def _encode_header(self, lines: list[str]) -> None:
        lines.append("VERS 240000 3 0")
        lines.append("MODE SEQ")
        if self._model.name:
            lines.append(f"NAME {self._model.name}")
        else:
            lines.append("NAME")
        lines.append("NOTE 0")
        lines.append("UNIT MM X W X CM MR CPMM")

        # Aperture operand
        self._encode_aperture(lines)

        # Fields header
        self._encode_fields_header(lines)

        # Wavelengths
        self._encode_wavelengths(lines)

        # Glass catalogs
        if self._model.glass_catalogs:
            lines.append("GCAT " + " ".join(self._model.glass_catalogs))

        # Field coordinate arrays
        fields = self._model.fields
        n = fields.get("num_fields", 0)
        if n > 0:
            zeros = [0.0] * n
            ones = [1.0] * n

            def _arr(key: str, default: list[float]) -> str:
                return " ".join(_fmt(v) for v in fields.get(key, default))

            lines.append("XFLN " + _arr("x", zeros))
            lines.append("YFLN " + _arr("y", zeros))
            lines.append("FWGN " + _arr("weights", ones))
            lines.append("VDXN " + _arr("vignette_decenter_x", zeros))
            lines.append("VDYN " + _arr("vignette_decenter_y", zeros))
            lines.append("VCXN " + _arr("vignette_compress_x", zeros))
            lines.append("VCYN " + _arr("vignette_compress_y", zeros))
            lines.append("VANN " + _arr("vignette_tangent_angle", zeros))

    def _encode_aperture(self, lines: list[str]) -> None:
        ap = self._model.aperture
        if not ap:
            return
        for ap_type, operand in _AP_TYPE_TO_OPERAND.items():
            if ap_type in ap:
                if operand == "FLOA":
                    lines.append("FLOA")
                elif operand in ("FNUM", "PFIL"):
                    # FNUM has a second argument for paraxial/real flag
                    flag = 1 if operand == "PFIL" else 0
                    lines.append(f"{operand} {_fmt(ap[ap_type])} {flag}")
                elif operand == "OBNA":
                    lines.append(f"OBNA {_fmt(ap[ap_type])} 0")
                else:
                    lines.append(f"{operand} {_fmt(ap[ap_type])}")
                break

    def _encode_fields_header(self, lines: list[str]) -> None:
        fields = self._model.fields
        n = fields.get("num_fields", 0)
        ftyp_int = fields.get(
            "ftyp_int",
            _FIELD_TYPE_TO_FTYP.get(fields.get("type", "angle"), 0),
        )
        # FTYP <type> <telecentric> <num_fields> <num_wavelengths> 0 0 0
        num_wl = self._model.wavelengths.get("num_wavelengths", 1)
        lines.append(f"FTYP {ftyp_int} 0 {n} {num_wl} 0 0 0")

    def _encode_wavelengths(self, lines: list[str]) -> None:
        wl_data = self._model.wavelengths
        data = wl_data.get("data", [])
        primary_index = wl_data.get("primary_index", 0)
        for i, w in enumerate(data):
            lines.append(f"WAVM {i + 1} {_fmt(w)} 1")
        lines.append(f"PWAV {primary_index + 1}")

    # ------------------------------------------------------------------
    # Surface blocks
    # ------------------------------------------------------------------

    def _encode_surfaces(self, lines: list[str]) -> None:
        for idx in sorted(self._model.surfaces.keys()):
            raw = self._model.surfaces[idx]
            lines.append(f"SURF {idx}")
            self._encode_surface(lines, raw)

    def _encode_surface(self, lines: list[str], raw: dict[str, Any]) -> None:
        surf_type = raw.get("TYPE", "STANDARD")
        lines.append(f"  TYPE {surf_type}")

        if raw.get("STOP"):
            lines.append("  STOP")

        curv = raw.get("CURV", 0.0)
        lines.append(f"  CURV {_fmt(curv)}")
        lines.append("  HIDE 0")
        lines.append("  MIRR 2 1")
        lines.append("  SLAB 0")

        self._encode_thickness(lines, raw)
        self._encode_conic(lines, raw)
        self._encode_glass_line(lines, raw)
        self._encode_diameter(lines, raw)
        self._encode_physical_aperture(lines, raw)
        self._encode_parameters(lines, raw)

    def _encode_thickness(self, lines: list[str], raw: dict[str, Any]) -> None:
        disz = raw.get("DISZ", 0.0)
        if disz == "INFINITY" or (isinstance(disz, float) and math.isinf(disz)):
            lines.append("  DISZ INFINITY")
        else:
            lines.append(f"  DISZ {_fmt(float(disz))}")

    def _encode_conic(self, lines: list[str], raw: dict[str, Any]) -> None:
        coni = raw.get("CONI", 0.0)
        if coni is not None and abs(float(coni)) > 1e-16:
            lines.append(f"  CONI {_fmt(float(coni))}")

    def _encode_glass_line(self, lines: list[str], raw: dict[str, Any]) -> None:
        glas = raw.get("GLAS")
        if glas is not None:
            lines.append(self._encode_glas(glas))

    def _encode_diameter(self, lines: list[str], raw: dict[str, Any]) -> None:
        diam = raw.get("DIAM")
        if diam is not None:
            lines.append(f"  DIAM {_fmt(float(diam))}")

    def _encode_physical_aperture(self, lines: list[str], raw: dict[str, Any]) -> None:
        clap = raw.get("CLAP")
        if clap is None:
            return
        if hasattr(clap, "r_min"):
            lines.append(f"  CLAP {_fmt(float(clap.r_min))} {_fmt(float(clap.r_max))}")
            if isinstance(clap, OffsetRadialAperture) and (
                clap.offset_x != 0.0 or clap.offset_y != 0.0
            ):
                lines.append(
                    f"  OBDC {_fmt(float(clap.offset_x))} {_fmt(float(clap.offset_y))}"
                )
        elif hasattr(clap, "x_min"):
            lines.append(f"  CLAP {_fmt(0.0)} {_fmt(float(clap.x_max))}")

    def _encode_parameters(self, lines: list[str], raw: dict[str, Any]) -> None:
        for i in range(1, 17):
            key = f"PARM_{i}"
            if key in raw:
                val = float(raw[key])
                if abs(val) > 1e-16:
                    lines.append(f"  PARM {i} {_fmt(val)}")

    def _encode_glas(self, glas: dict[str, Any]) -> str:
        name = glas.get("name", "")
        if name == "MIRROR":
            return "  GLAS MIRROR 0 0 0 0 0 0 0 0 0 0"
        if "catalog" not in glas and "n" in glas and "V" in glas:
            # MODEL glass
            return f"  GLAS MODEL 1 0 {_fmt(glas['n'])} {_fmt(glas['V'])} 0 0 0 0 0 0"
        if "n" in glas and "V" in glas:
            # Catalog glass: record Nd/Vd so an ambiguous name (present in
            # multiple GCAT catalogs) can be disambiguated on reload.
            return f"  GLAS {name} 0 0 {_fmt(glas['n'])} {_fmt(glas['V'])} 0 0 0 0 0 0"
        # Catalog glass without index data (e.g. round-tripped from another format)
        return f"  GLAS {name} 0 0 0 0 0 0 0 0 0 0"


# ---------------------------------------------------------------------------
# ZEMAX 2003 dialect
# ---------------------------------------------------------------------------

# ZEMAX 2003 ships Schott's pre-2000 glasses as SCHOTT and the lead-free
# N-glasses as SCHOTT_2000; the sample files of that release declare both.
_ZEMAX_2003_CATALOGS: dict[str, tuple[str, ...]] = {
    "SCHOTT": ("SCHOTT", "SCHOTT_2000"),
}
_ZEMAX_2003_MAX_FIELDS = 12
_ZEMAX_2003_MAX_WAVELENGTHS = 12
_ZEMAX_2003_VIGNETTING_KEYS = (
    "vignette_decenter_x",
    "vignette_decenter_y",
    "vignette_compress_x",
    "vignette_compress_y",
    "vignette_tangent_angle",
)


def _fmt_2003(value: float) -> str:
    """Format a float at full float64 precision with a three-digit exponent.

    ``1.0`` becomes ``1.0000000000000000E+000``, the exponent width ZEMAX 2003
    itself writes.
    """
    mantissa, exponent = f"{float(value):.16E}".split("E")
    return f"{mantissa}E{exponent[0]}{int(exponent[1:]):03d}"


class Zemax2003FileEncoder(ZemaxFileEncoder):
    """Encodes a ZemaxDataModel for ZEMAX-EE of January 2003.

    That release reads current OpticStudio output only partly. The operands
    written here, their order and their token counts follow the sample files
    shipped with it:

    - ``VERS 30106 149`` and ``UNIT MM NW NWC``. Test files that froze ZEMAX
      2003 on open all had a bare ``UNIT MM`` and a ``VERS`` line without its
      build number.
    - Fields and wavelengths as value lists (``XFLD``/``YFLD``/``FWGT``,
      ``WAVL``/``WWGT``) under a two-token ``FTYP``; at most 12 of each.
    - A mode on every ``DIAM`` (fixed for a floating stop), the solve slots on
      ``CURV``, a ``POPS`` line per surface, the ``BLNK``/``TOL``/``MNUM``/
      ``MOFF`` trailer, and ``___BLANK`` as the name of a model glass.

    Vignetting factors and decentred surface apertures have no operand in that
    format; they are left out with a warning.
    """

    def encode(self) -> list[str]:
        """Produce the complete list of .zmx text lines.

        Returns:
            A list of strings, one per line of the output file.

        Raises:
            ValueError: If the system has more fields or wavelengths than
                ZEMAX 2003 holds.
        """
        self._check_limits()
        lines: list[str] = []
        self._encode_header(lines)
        self._encode_surfaces(lines)
        self._encode_trailer(lines)
        return lines

    def _check_limits(self) -> None:
        n_fields = self._model.fields.get("num_fields", 0)
        n_wavelengths = len(self._model.wavelengths.get("data", []))
        if n_fields > _ZEMAX_2003_MAX_FIELDS:
            raise ValueError(
                f"ZEMAX 2003 holds at most {_ZEMAX_2003_MAX_FIELDS} fields; "
                f"this system has {n_fields}."
            )
        if n_wavelengths > _ZEMAX_2003_MAX_WAVELENGTHS:
            raise ValueError(
                f"ZEMAX 2003 holds at most {_ZEMAX_2003_MAX_WAVELENGTHS} "
                f"wavelengths; this system has {n_wavelengths}."
            )

    # ------------------------------------------------------------------
    # Header block
    # ------------------------------------------------------------------

    def _encode_header(self, lines: list[str]) -> None:
        zero, one = _fmt_2003(0.0), _fmt_2003(1.0)
        lines.append("VERS 30106 149")
        lines.append("MODE SEQ")
        lines.append(f"NAME {self._model.name}" if self._model.name else "NAME")
        lines.append("NOTE 1 Notes...")
        lines.append("NOTE 2  ")
        lines.append("NOTE 3  ")
        lines.append("UNIT MM NW NWC")
        self._encode_aperture(lines)
        lines.append("GFAC 0 0")
        lines.append("GCAT " + " ".join(self._catalogs()))
        lines.append("RAIM 1.0E-8 0 1 1 0 0")
        lines.append(f"PUSH {zero} {zero} {zero} 0")
        lines.append(f"SDMA {zero} 1 {zero}")
        self._encode_fields(lines)
        self._encode_wavelengths(lines)
        lines.append(f"POLS 1 {zero} {one} {zero} {zero} 1")
        lines.append("GLRS 1")
        lines.append(
            "GSTD 0 100.00000 100.00000 100.00000 100.00000 100.00000 100.00000 0"
        )
        tol = _fmt_2003(1e-6)
        lines.append(f"NSCD 100 500 {zero} {tol} 5 {tol} 0 0 0 0 {zero} 0")
        lines.append("COFN COATING.DAT SCATTER_PROFILE.DAT ABG_DATA.DAT")

    def _encode_aperture(self, lines: list[str]) -> None:
        ap = self._model.aperture
        for ap_type, operand in _AP_TYPE_TO_OPERAND.items():
            if ap_type not in ap:
                continue
            value = _fmt_2003(ap[ap_type])
            if operand == "FLOA":
                lines.append("FLOA")
            elif operand in ("FNUM", "PFIL"):
                # One FNUM operand, flagged real (0) or paraxial (1).
                lines.append(f"FNUM {value} {1 if operand == 'PFIL' else 0}")
            elif operand == "OBNA":
                lines.append(f"OBNA {value} 0")
            else:
                lines.append(f"{operand} {value}")
            return

    def _catalogs(self) -> list[str]:
        names: list[str] = []
        for catalog in self._model.glass_catalogs or ["SCHOTT"]:
            key = catalog.upper()
            names.extend(_ZEMAX_2003_CATALOGS.get(key, (key,)))
        return list(dict.fromkeys(names))

    def _encode_fields(self, lines: list[str]) -> None:
        fields = self._model.fields
        n = fields.get("num_fields", 0)
        ftyp = fields.get(
            "ftyp_int", _FIELD_TYPE_TO_FTYP.get(fields.get("type", "angle"), 0)
        )
        lines.append(f"FTYP {ftyp} 0")
        lines.append("ROPD 2")
        lines.append("PICB 1")
        if n == 0:
            # ZEMAX needs at least one field point.
            n, fields = 1, {"x": [0.0], "y": [0.0], "weights": [1.0]}

        def values(key: str, default: float) -> str:
            return " ".join(_fmt_2003(v) for v in fields.get(key, [default] * n))

        lines.append("XFLD " + values("x", 0.0))
        lines.append("YFLD " + values("y", 0.0))
        lines.append("FWGT " + values("weights", 1.0))

        if any(
            float(v) != 0.0
            for key in _ZEMAX_2003_VIGNETTING_KEYS
            for v in fields.get(key, [])
        ):
            warnings.warn(
                "ZEMAX 2003 has no operand for field vignetting factors; they "
                "are not exported.",
                UserWarning,
                stacklevel=2,
            )

    def _encode_wavelengths(self, lines: list[str]) -> None:
        wavelengths = self._model.wavelengths
        data = list(wavelengths.get("data", []))
        weights = list(wavelengths.get("weights") or [])
        if len(weights) != len(data):
            weights = [1.0] * len(data)
        if data:
            lines.append("WAVL " + " ".join(_fmt_2003(v) for v in data))
            lines.append("WWGT " + " ".join(_fmt_2003(w) for w in weights))
        lines.append(f"PWAV {wavelengths.get('primary_index', 0) + 1}")

    # ------------------------------------------------------------------
    # Surface blocks
    # ------------------------------------------------------------------

    def _encode_surfaces(self, lines: list[str]) -> None:
        for idx in sorted(self._model.surfaces.keys()):
            self._surface_index = idx
            lines.append(f"SURF {idx}")
            self._encode_surface(lines, self._model.surfaces[idx])

    def _encode_surface(self, lines: list[str], raw: dict[str, Any]) -> None:
        zero, one = _fmt_2003(0.0), _fmt_2003(1.0)
        if raw.get("STOP"):
            lines.append("  STOP")
        lines.append(f"  TYPE {raw.get('TYPE', 'STANDARD')}")
        lines.append(f"  CURV {_fmt_2003(raw.get('CURV', 0.0))} 0 {zero} {zero}")
        self._encode_parameters(lines, raw)
        self._encode_thickness(lines, raw)
        self._encode_glass_line(lines, raw)
        self._encode_conic(lines, raw)
        self._encode_diameter(lines, raw)
        lines.append(f"  POPS 0 0 0 0 0 0 0 0 1 1 {one} {one}")
        self._encode_physical_aperture(lines, raw)

    def _encode_parameters(self, lines: list[str], raw: dict[str, Any]) -> None:
        # That release writes every parameter a surface holds, zeros included.
        for i in range(1, 17):
            key = f"PARM_{i}"
            if key in raw:
                lines.append(f"  PARM {i} {_fmt_2003(float(raw[key]))}")

    def _encode_thickness(self, lines: list[str], raw: dict[str, Any]) -> None:
        disz = raw.get("DISZ", 0.0)
        if disz == "INFINITY" or (isinstance(disz, float) and math.isinf(disz)):
            lines.append("  DISZ INFINITY")
        else:
            lines.append(f"  DISZ {_fmt_2003(float(disz))}")

    def _encode_conic(self, lines: list[str], raw: dict[str, Any]) -> None:
        coni = raw.get("CONI", 0.0)
        if coni is not None and abs(float(coni)) > 1e-16:
            lines.append(f"  CONI {_fmt_2003(float(coni))}")

    def _encode_diameter(self, lines: list[str], raw: dict[str, Any]) -> None:
        diam = raw.get("DIAM")
        if diam is None:
            lines.append(f"  DIAM {_fmt_2003(0.0)} 0 0")
            return
        mode = 1 if raw.get("DIAM_FIXED") else 0
        lines.append(f"  DIAM {_fmt_2003(float(diam))} {mode} 0")

    def _encode_physical_aperture(self, lines: list[str], raw: dict[str, Any]) -> None:
        clap = raw.get("CLAP")
        if clap is None or not hasattr(clap, "r_min"):
            return
        if isinstance(clap, OffsetRadialAperture) and (
            clap.offset_x != 0.0 or clap.offset_y != 0.0
        ):
            warnings.warn(
                f"Surface {self._surface_index}: ZEMAX 2003 has no operand for a "
                "decentred surface aperture; the aperture is not exported rather "
                "than written centred.",
                UserWarning,
                stacklevel=2,
            )
            return
        lines.append(
            f"  CLAP {_fmt_2003(float(clap.r_min))} {_fmt_2003(float(clap.r_max))}"
        )

    def _encode_glas(self, glas: dict[str, Any]) -> str:
        name = glas.get("name", "")
        nd = float(glas.get("n", 0.0))
        vd = float(glas.get("V", 0.0))
        if name == "MIRROR":
            label, flags, nd, vd = "MIRROR", "0 0", 0.0, 0.0
        elif "catalog" not in glas and "n" in glas and "V" in glas:
            label, flags = "___BLANK", "1 0"
        else:
            label, flags = name, "0 0"
        return (
            f"  GLAS {label} {flags} {nd:.8f} {vd:.8f} 0.00000000 0 0 0 "
            "0.00000000 0.00000000 "
        )

    # ------------------------------------------------------------------
    # Trailer
    # ------------------------------------------------------------------

    def _encode_trailer(self, lines: list[str]) -> None:
        lines.append("BLNK ")
        lines.append("TOL TOFF   0   0              0              0   0")
        lines.append("MNUM 1")
        lines.append('MOFF   0   1 "" 0 0 0 1 1 0.0 0.0 ')
