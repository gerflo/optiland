"""Zemax File Exporter

Entry point for exporting an Optiland Optic to a Zemax .zmx file, written for
current OpticStudio or for ZEMAX-EE of January 2003.

Kramer Harrison, 2024
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from optiland.fileio.base import BaseOpticWriter
from optiland.fileio.zemax.writer.encoder import (
    Zemax2003FileEncoder,
    ZemaxFileEncoder,
)
from optiland.fileio.zemax.writer.formatter import OpticToZemaxConverter

if TYPE_CHECKING:
    from optiland.optic import Optic

# Re-export so zemax/__init__.py can import both from this module
__all__ = [
    "ZEMAX_DIALECTS",
    "OpticToZemaxConverter",
    "ZemaxWriter",
    "save_zemax_file",
]

#: Output dialects accepted by :func:`save_zemax_file`.
ZEMAX_DIALECTS = ("opticstudio", "zemax2003")


def save_zemax_file(optic: Optic, filepath: str, dialect: str = "opticstudio") -> None:
    """Export an Optic to a Zemax .zmx file.

    Warnings are issued via Python's ``warnings`` module for:

    - Glasses with no Zemax catalog entry (written as MODEL glass).
    - Pickups or solves that cannot be represented (resolved values exported).
    - Surface apertures, and in the ``"zemax2003"`` dialect vignetting factors,
      that the file cannot carry and that are therefore left out.

    Args:
        optic: The optic to export.
        filepath: Destination path (should end in ``.zmx``).
        dialect: ``"opticstudio"`` (default) writes the current format as UTF-8.
            ``"zemax2003"`` writes the format of ZEMAX-EE of January 2003, which
            reads current files only partly, as Windows-1252 with CRLF line
            ends; see :class:`~optiland.fileio.zemax.writer.encoder.
            Zemax2003FileEncoder`.

    Raises:
        ValueError: If ``dialect`` is unknown, or the system exceeds a limit of
            the chosen dialect (nothing is written then).
        NotImplementedError: If the optic contains a surface type not yet
            supported by the writer.
    """
    if dialect not in ZEMAX_DIALECTS:
        raise ValueError(
            f"Unknown Zemax dialect {dialect!r}; expected one of {ZEMAX_DIALECTS}."
        )
    model = OpticToZemaxConverter(optic).convert()

    if dialect == "zemax2003":
        lines = Zemax2003FileEncoder(model).encode()
        with open(
            filepath, "w", encoding="cp1252", errors="replace", newline="\r\n"
        ) as fh:
            fh.write("\n".join(lines) + "\n")
        return

    lines = ZemaxFileEncoder(model).encode()
    with open(filepath, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))


class ZemaxWriter(BaseOpticWriter):
    """BaseOpticWriter implementation for Zemax .zmx files.

    This thin wrapper around :func:`save_zemax_file` allows the Zemax writer
    to be used polymorphically via the BaseOpticWriter interface.

    Args:
        dialect: The output dialect; see :func:`save_zemax_file`.
    """

    def __init__(self, dialect: str = "opticstudio") -> None:
        self.dialect = dialect

    def write(self, optic: Optic, filepath: str) -> list[str]:
        """Write *optic* to a .zmx file at *filepath*.

        Args:
            optic: The optic to export.
            filepath: Destination path.

        Returns:
            An empty list (warnings are issued via the ``warnings`` module).
        """
        save_zemax_file(optic, filepath, dialect=self.dialect)
        return []
